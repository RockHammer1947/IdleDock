"""End-to-end fake ComfyUI HTTP server, owned process cleanup and provenance."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import zipfile
from unittest.mock import patch

import test_providers as provider_tests
from h3queue.store import ROOT, db, get, setv, atomic_json
from h3queue.providers.command import register
from h3queue.cli import control
from h3queue.jobs import normalize
from h3queue.integrity import validate_spec, DeploymentChanged
from h3queue.processes import matches

FAKE = r'''
import argparse,json,os,time
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
p=argparse.ArgumentParser();p.add_argument('--listen');p.add_argument('--port',type=int);p.add_argument('--input-directory');p.add_argument('--output-directory');p.add_argument('--disable-auto-launch',action='store_true');a=p.parse_args()
root=Path(a.output_directory);workflow={};submitted=False
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  global workflow,submitted
  d=json.loads(self.rfile.read(int(self.headers['Content-Length'])));workflow=d['prompt'];submitted=True
  (root/'started').write_text(str(os.getpid()));self.send_response(200);self.end_headers();self.wfile.write(b'{"prompt_id":"fake-id","node_errors":{}}')
 def do_GET(self):
  if self.path=='/system_stats':d={'system':{'comfyui_version':'test-only'}}
  else:
   text=workflow.get('1',{}).get('inputs',{}).get('text','hello')
   if text=='slow':d={}
   elif text=='fail':d={'fake-id':{'status':{'status_str':'error','completed':False}}}
   else:
    (root/'result.txt').write_text(text)
    filename='../escape' if text=='escape' else 'result.txt'
    d={'fake-id':{'status':{'status_str':'success','completed':True},'outputs':{'1':{'images':[{'filename':filename,'subfolder':'','type':'output'}]}}}}
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps(d).encode())
HTTPServer((a.listen,a.port),Handler).serve_forever()
'''


class ComfyTests(unittest.TestCase):
    setUpBase=provider_tests.ProviderTests.setUp
    tearDown=provider_tests.ProviderTests.tearDown
    add=provider_tests.ProviderTests.add
    row=provider_tests.ProviderTests.row
    out=provider_tests.ProviderTests.out
    start=provider_tests.ProviderTests.start
    settle=provider_tests.ProviderTests.settle
    wait_file=provider_tests.ProviderTests.wait_file
    def setUp(self):
        self.setUpBase()
        self.comfy=self.root/'fake comfy';self.comfy.mkdir()
        (self.comfy/'main.py').write_text(FAKE)
        for name in ('server.py','execution.py'):(self.comfy/name).write_text('# fake pinned dependency\n')
        self.install=self.root/'prepared'
        subprocess.run([sys.executable,str(ROOT/'scripts/prepare-comfyui.py'),str(self.install),
                        '--comfy-root',str(self.comfy),'--comfy-python',sys.executable],check=True,capture_output=True)
        register(self.install/'provider.json')
        with db() as c:setv(c,'deployment',str(self.install/'deployment'))
        workflow=self.root/'workflow.json';atomic_json(workflow,{'1':{'class_type':'FakeSave','inputs':{'text':'hello'}}})
        self.raw={'provider':'comfyui','assets':{'workflow':str(workflow)},'payload':{}}
    def test_success_collects_hashed_outputs_and_preserves_workflow(self):
        jid=self.add();out=self.start(jid);row=self.settle(jid)
        self.assertEqual(row['status'],'completed',row)
        with zipfile.ZipFile(row['output']) as archive:
            result=json.loads(archive.read('manifest.json'));self.assertEqual(result['comfy_version'],'test-only')
            self.assertEqual(archive.read('outputs/'+result['artifacts'][0]['path']),b'hello')
        self.assertEqual(len(result['artifacts'][0]['sha256']),64)
        info=json.loads((out/'comfy-job.json').read_text())
        import psutil
        self.assertFalse(psutil.pid_exists(info['server_pid']))
        self.assertTrue((out/'comfy-history.json').exists())
    def test_stop_cleans_owned_server_and_retry_uses_new_attempt(self):
        self.raw['payload']={'inputs':{'1':{'text':'slow'}}}
        jid=self.add();out=self.start(jid);self.wait_file(out/'artifacts/comfy-output/started')
        pid=int((out/'artifacts/comfy-output/started').read_text())
        import psutil
        born=psutil.Process(pid).create_time()
        with patch('h3queue.cli.ensure_worker'):control('stop')
        self.assertEqual(self.settle(jid)['status'],'queued')
        self.assertFalse(matches({'pid':pid,'born':born}));self.assertFalse((out/'verified.json').exists())
        # New attempt, original evidence retained; do not modify fixed payload.
        newer=self.start(jid);self.wait_file(newer/'artifacts/comfy-output/started')
        self.assertNotEqual(newer,out)
        with patch('h3queue.cli.ensure_worker'):control('stop')
        self.assertEqual(self.settle(jid)['status'],'queued');self.assertTrue((out/'render.log').exists())
    def test_engine_failure_and_unsafe_artifacts_fail_without_cache(self):
        for text in ('fail','escape'):
            jid=self.add({**self.raw,'payload':{'inputs':{'1':{'text':text}}}})
            self.start(jid);row=self.settle(jid)
            self.assertEqual(row['status'],'failed',row)
            with db() as c:self.assertEqual(c.execute('select count(*) from cache where fingerprint=?',(row['fingerprint'],)).fetchone()[0],0)
    def test_workflow_and_installation_are_pinned(self):
        s=normalize(self.raw,self.install/'deployment');validate_spec(s)
        (self.comfy/'server.py').write_text('# changed\n')
        with self.assertRaises(DeploymentChanged):validate_spec(s)
        s=normalize(self.raw,self.install/'deployment')
        Path(self.raw['assets']['workflow']).write_text('{}')
        with self.assertRaises(DeploymentChanged):validate_spec(s)
    def test_prepare_does_not_register_start_or_overwrite(self):
        with db() as c:self.assertEqual(get(c,'mode'),'paused');self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0],0)
        result=subprocess.run([sys.executable,str(ROOT/'scripts/prepare-comfyui.py'),str(self.install),
                        '--comfy-root',str(self.comfy),'--comfy-python',sys.executable],capture_output=True)
        self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
