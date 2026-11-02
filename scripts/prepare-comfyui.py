"""Prepare a trusted command provider for an existing local ComfyUI install.

Does not register, enqueue, start a worker or run ComfyUI. Never overwrites.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path)
    p.add_argument('--comfy-root',type=Path,required=True)
    p.add_argument('--comfy-python',type=Path,required=True)
    args=p.parse_args()
    root=args.comfy_root.expanduser().resolve();python=args.comfy_python.expanduser().absolute()
    required=[root/name for name in ('main.py','server.py','execution.py')]
    if not all(path.is_file() for path in required) or not python.is_file():
        p.error('Supply an existing ComfyUI checkout and its installed Python environment')
    directory=args.directory.expanduser().resolve();directory.mkdir(parents=True,exist_ok=False)
    deployment=directory/'deployment';deployment.mkdir()
    shutil.copyfile(ROOT/'examples/standalone-deployment/agent_session.py',deployment/'agent_session.py')
    config=directory/'comfy-config.json';config.write_text(json.dumps({'comfy_root':str(root),'comfy_python':str(python),'extra_args':[]},indent=2))
    runner=ROOT/'examples/comfyui/runner.py'
    manifest={'protocol':1,'id':'comfyui','label':'ComfyUI (owned local server)','revision':'2026-11-02-v1',
        'argv':[sys.executable,str(runner),'--request','{request}','--output','{output}','--config',str(config)],
        'dependencies':[str(runner),str(config),str(python),*[str(path) for path in required]],
        'resources':{'device':'gpu','min_available_gib':4},'output':'comfy-result.zip','output_kind':'file'}
    (directory/'provider.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'prepared':str(directory),'deployment':str(deployment),
        'note':'Review configuration; configure/register explicitly. No inference started.'}))


if __name__=='__main__':main()
