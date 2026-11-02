"""Owned, per-attempt ComfyUI server; never submits to an existing service.

Run through IdleDock's registered GPU provider and shared resource session.
The server and all its children inherit the guarded runner's process group.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time
import zipfile
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler, Request

import psutil

MAX_JSON = 16*1024**2


def read_json(path):
    if Path(path).stat().st_size > MAX_JSON:raise ValueError('JSON exceeds 16 MiB')
    return json.loads(Path(path).read_text())


def api(port, path, payload=None):
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = Request('http://127.0.0.1:'+str(port)+path, data=body,
                      headers={'Content-Type':'application/json'})
    # Local inference must not pass through HTTP_PROXY from a shell environment.
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        data = response.read(MAX_JSON+1)
        if len(data)>MAX_JSON:raise ValueError('ComfyUI response exceeds 16 MiB')
        return json.loads(data)



def owns_listener(pid, port):
    denied = None
    try:
        if any(c.status==psutil.CONN_LISTEN and c.laddr.ip=='127.0.0.1' and c.laddr.port==port
               for c in psutil.Process(pid).net_connections(kind='tcp')):
            return True
    except psutil.AccessDenied as exc:
        denied = exc
    # On macOS libproc may omit sockets without raising AccessDenied. Query
    # the same child with lsof on both an empty result and permission denial.
    if sys.platform!='darwin':
        if denied:raise RuntimeError('Cannot verify owned ComfyUI listening socket; process socket access is required') from denied
        return False
    binary=shutil.which('lsof')
    if not binary:raise RuntimeError('Cannot verify owned ComfyUI listening socket; lsof is required on macOS')
    result=subprocess.run([binary,'-nP','-a','-p',str(pid),'-iTCP:'+str(port),'-sTCP:LISTEN','-Fpn'],
                          capture_output=True,text=True,timeout=3)
    lines=result.stdout.splitlines()
    return result.returncode==0 and 'p'+str(pid) in lines and 'n127.0.0.1:'+str(port) in lines


def prepare_workflow(request, input_dir):
    spec = request['spec'];assets = spec['assets']
    if 'workflow' not in assets:raise ValueError('assets.workflow must be an API-format workflow JSON')
    workflow = read_json(assets['workflow'])
    if not isinstance(workflow, dict) or not workflow or any(not isinstance(v, dict) or
            not isinstance(v.get('class_type'), str) or not isinstance(v.get('inputs'), dict) for v in workflow.values()):
        raise ValueError('Export ComfyUI workflow in API format (node IDs with class_type and inputs)')
    payload = spec.get('payload', {})
    if set(payload)-{'inputs'}:raise ValueError('Only payload.inputs node input overrides are supported')
    changes = payload.get('inputs', {})
    if not isinstance(changes, dict):raise ValueError('payload.inputs must be an object')
    for node, inputs in changes.items():
        if node not in workflow or not isinstance(inputs, dict) or set(inputs)-set(workflow[node]['inputs']):
            raise ValueError('Input overrides must refer to existing workflow nodes and inputs')
        workflow[node]['inputs'].update(inputs)
    import shutil
    for name, source in assets.items():
        if name=='workflow':continue
        if not name or Path(name).name!=name or name in ('.','..') or '\\' in name:
            raise ValueError('Additional asset keys must be plain input filenames')
        shutil.copyfile(source, input_dir/name)
    return workflow


def artifacts(history, output_dir):
    found = []
    for values in history.get('outputs', {}).values():
        for items in values.values():
            if not isinstance(items, list):continue
            for item in items:
                if not isinstance(item, dict) or item.get('type')!='output' or 'filename' not in item:continue
                filename = item['filename'];subfolder = item.get('subfolder', '')
                if not isinstance(filename, str) or Path(filename).name!=filename or '\\' in filename:
                    raise ValueError('Unsafe ComfyUI artifact filename')
                if not isinstance(subfolder, str) or Path(subfolder).is_absolute() or '..' in Path(subfolder).parts or '\\' in subfolder:
                    raise ValueError('Unsafe ComfyUI artifact subfolder')
                path = (output_dir/subfolder/filename).resolve()
                if not path.is_relative_to(output_dir.resolve()) or not path.is_file() or path.stat().st_size==0:
                    raise ValueError('Missing, empty or external ComfyUI artifact')
                if str(path) in {a['path'] for a in found}:continue
                digest=hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024), b''):digest.update(block)
                found.append({'path':str(path), 'sha256':digest.hexdigest(), 'bytes':path.stat().st_size})
    if not found:raise ValueError('Workflow produced no saved output files; use an output/save node')
    return found


def run(request_path, output_path, config_path):
    if os.environ.get('LOCAL_MODEL_SESSION_TARGET')!='h3':raise RuntimeError('Use the IdleDock GPU resource session')
    request = read_json(request_path);config = read_json(config_path)
    attempt = Path(request_path).resolve().parent
    root = Path(config['comfy_root']).resolve()
    python = Path(config['comfy_python'])
    # Isolated paths per attempt preserve failed output and prevent overwrites.
    input_dir=attempt/'comfy-input';output_dir=attempt/'artifacts/comfy-output'
    input_dir.mkdir(exist_ok=False);output_dir.mkdir(parents=True,exist_ok=False)
    workflow = prepare_workflow(request, input_dir)
    (attempt/'comfy-workflow.json').write_text(json.dumps(workflow, allow_nan=False))
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0));port=reservation.getsockname()[1]
    command=[str(python),str(root/'main.py'),'--listen','127.0.0.1','--port',str(port),
             '--input-directory',str(input_dir),'--output-directory',str(output_dir),'--disable-auto-launch']
    # Extra engine flags are trusted installation configuration, never job text.
    extra=config.get('extra_args', [])
    if not isinstance(extra,list) or not all(isinstance(v,str) for v in extra):raise ValueError('Invalid extra_args')
    # Cannot replace ownership/listening/directories with extra configuration.
    if any(v.split('=')[0] in ('--listen','--port','--input-directory','--output-directory','--auto-launch') for v in extra):
        raise ValueError('extra_args cannot override server ownership or input/output paths')
    command+=extra
    server = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL)
    # No start_new_session: the queue's PID-birth checked process group owns
    # server and grandchildren, including on SIGKILL/crashed runner recovery.
    try:
        deadline=time.monotonic()+180;next_report=0
        while True:
            if server.poll() is not None:raise RuntimeError('Dedicated ComfyUI server exited during startup; see render.log')
            if time.monotonic()>deadline:raise TimeoutError('ComfyUI startup exceeded 180 seconds')
            try:
                # Prove our child owns the listening socket. Never connect to
                # another user's server in the port-allocation race.
                listening=owns_listener(server.pid,port)
                if listening:
                    stats=api(port, '/system_stats');break
                if time.monotonic()>=next_report:
                    print('Waiting for owned ComfyUI listener',server.pid,port,flush=True)
                    next_report=time.monotonic()+5
            except (OSError, ValueError, psutil.Error) as exc:
                if time.monotonic()>=next_report:
                    print('ComfyUI startup probe:',type(exc).__name__,str(exc),flush=True)
                    next_report=time.monotonic()+5
            time.sleep(.25)
        result=api(port, '/prompt', {'prompt':workflow,'client_id':request['attempt_id']})
        prompt_id=result.get('prompt_id')
        if not isinstance(prompt_id,str) or not prompt_id or result.get('node_errors'):
            raise RuntimeError('ComfyUI rejected workflow: '+json.dumps(result)[:4000])
        (attempt/'comfy-job.json').write_text(json.dumps({'prompt_id':prompt_id,'server_pid':server.pid,'port':port}))
        while True:
            if server.poll() is not None:raise RuntimeError('Dedicated ComfyUI server exited before completion')
            history=api(port, '/history/'+quote(prompt_id, safe='')).get(prompt_id)
            if history:
                (attempt/'comfy-history.json').write_text(json.dumps(history))
                status=history.get('status', {})
                if status.get('status_str')=='error':raise RuntimeError('ComfyUI workflow failed; see comfy-history.json')
                if status.get('completed'):
                    files=artifacts(history,output_dir)
                    # One primary artifact makes cached integrity cover all
                    # saved media as well as the provenance manifest.
                    manifest={'prompt_id':prompt_id,'artifacts':[
                        {**item,'path':str(Path(item['path']).relative_to(output_dir))} for item in files],
                        'comfy_version':stats.get('system',{}).get('comfyui_version'),
                        'acceptance':'Saved files and SHA256 only; media/visual quality not reviewed'}
                    with zipfile.ZipFile(output_path, 'x', compression=zipfile.ZIP_STORED) as archive:
                        archive.writestr('manifest.json',json.dumps(manifest,indent=2))
                        for item in files:
                            archive.write(item['path'],'outputs/'+str(Path(item['path']).relative_to(output_dir)))
                    return
            time.sleep(.5)
    finally:
        # The outer guard also cleans the owned process group. Reap the direct
        # child on ordinary exceptions without leaving a resident GPU server.
        if server.poll() is None:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args();run(args.request,args.output,args.config)


if __name__=='__main__':main()
