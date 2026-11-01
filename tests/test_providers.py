"""Integration tests use tiny WAVs and fake local runtimes, never model inference."""
import contextlib
import fcntl
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from h3queue.store import db,get,setv,atomic_json,digest,ROOT
from h3queue.jobs import enqueue,enqueue_batch,normalize,fingerprint
from h3queue.cli import snapshot,control,main
from h3queue.providers import resolve,catalog
from h3queue.providers.command import register
from h3queue.integrity import validate_spec,DeploymentChanged
from h3queue.worker import tick
from h3queue.recovery import prepare_retry
from h3queue.estimate import estimate
from h3queue.artifacts import audio_metadata


def wav(path,silent=False):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000)
        w.writeframes((b'\x00\x00' if silent else b'\xe8\x03')*2400)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'H3_QUEUE_HOME':str(self.root/'state')});self.env.start()
        self.base=self.root/'base';(self.base/'TTS/model').mkdir(parents=True)
        (self.base/'TTS/model/config.json').write_text('{}')
        self.fake=self.root/'fake_tts.py'
        self.fake.write_text('''import json,sys,wave,time\nfrom pathlib import Path\na=sys.argv;r=Path(a[a.index('--request')+1]);s=json.loads(r.read_text())['spec'];o=Path(a[a.index('--output')+1])\n(r.parent/'fake-engine-started').touch()\nif s['text']=='slow':time.sleep(60)\nif s['text']=='fail':raise RuntimeError('fake failure')\nwith wave.open(str(o),'wb') as w:\n w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\\xe8\\x03'*2400)\n''')
        python=self.root/'fake-python'
        python.write_text('#!/bin/sh\nexec "'+sys.executable+'" "'+str(self.fake)+'" "$@"\n');python.chmod(0o755)
        self.config={'family':'Fake','runtime':'mlx-audio','python':str(python),'model_path':'model','languages':['zh','en']}
        self.profiles={'fake':self.config,'clone':{**self.config,'reference':True}}
        atomic_json(self.base/'TTS/profiles.json',self.profiles)
        self.state=self.base/'qwen.json';atomic_json(self.state,{'running':True,'state':{'profile':'balanced','prefix_cache':False}})
        (self.base/'agent_session.py').write_text('''import json\nfrom pathlib import Path\nROOT=Path(__file__).parent\ndef service(action,profile=None,prefix_cache=False):\n p=ROOT/'qwen.json';s=json.loads(p.read_text())\n if action=='status':return s\n if action=='stop':\n  s['running']=False;(ROOT/'stopped').touch()\n if action=='start':\n  s={'running':True,'state':{'profile':profile,'prefix_cache':prefix_cache}};(ROOT/'restored').touch()\n p.write_text(json.dumps(s))\ndef ready(profile):pass\n''')
        self.raw={'provider':'tts','profile':'fake','text':'hello','language':'en'}
        with db() as c:
            setv(c,'deployment',str(self.base));policy=get(c,'safety');policy.update(require_telemetry=False,min_disk_gib=2,min_available_gib=1);setv(c,'safety',policy)
    def tearDown(self):
        # Tests that start work must settle it before leaving the temporary deployment.
        self.env.stop();self.tmp.cleanup()
    def add(self,raw=None):
        with db() as c:return enqueue(c,raw or self.raw,'test')['id']
    def row(self,jid):
        with db() as c:return dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    def out(self,jid):
        with db() as c:return Path(c.execute('SELECT directory FROM attempts WHERE id=?',(self.row(jid)['attempt_id'],)).fetchone()[0])
    def start(self,jid):
        with db() as c:setv(c,'mode','manual')
        tick();return self.out(jid)
    def settle(self,jid,timeout=15):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            tick();row=self.row(jid)
            if row['status'] not in ('running','cancel_requested'):return row
            time.sleep(.1)
        self.fail('Task did not settle')
    def wait_file(self,path):
        until=time.monotonic()+8
        while not path.exists() and time.monotonic()<until:time.sleep(.05)
        self.assertTrue(path.exists(),str(path))
    def command(self,name='fake-command',device='cpu',script=None,kind='json'):
        runner=self.root/(name+'.py')
        runner.write_text(script or "import json,sys\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text());Path(sys.argv[2]).write_text(json.dumps(r['spec']['payload']))\n")
        manifest={'id':name,'protocol':1,'revision':'v1','label':'Fake compute','argv':[sys.executable,str(runner),'{request}','{output}'],
                  'output':'result.'+('wav' if kind=='audio' else 'json'),'output_kind':kind,'resources':{'device':device},'dependencies':[str(runner)]}
        file=self.root/(name+'.json');atomic_json(file,manifest);register(file)
        return {'provider':name,'payload':{'text':'$(touch NEVER) `echo never`'}},file
    def test_legacy_h3_fingerprint_remains_identical(self):
        from h3queue.providers.h3 import normalize as legacy
        raw={'profile':'native20','prompt':'test','width':32,'height':32,'frames':7}
        self.assertEqual(fingerprint(normalize(raw,self.base)),fingerprint(legacy(raw,self.base)))
        self.assertEqual(normalize({**raw,'provider':'h3'},self.base),legacy(raw,self.base))
    def test_paused_mixed_import_and_audio_snapshot(self):
        h3={'profile':'native20','prompt':'test','width':32,'height':32,'frames':7}
        a=self.add();b=self.add(h3);tick();s=snapshot()
        self.assertEqual(s['counts']['queued'],2);self.assertEqual(s['settings']['mode'],'paused')
        jobs={j['id']:j for j in s['jobs']}
        self.assertEqual(jobs[a]['output_kind'],'audio');self.assertIsNone(jobs[a]['seconds'])
        self.assertEqual(jobs[b]['output_kind'],'video');self.assertEqual(s['unknown_estimates'],2)
    def test_tts_success_restores_qwen_and_separates_metrics(self):
        jid=self.add();out=self.start(jid);row=self.settle(jid)
        self.assertEqual(row['status'],'completed',row)
        self.assertEqual(audio_metadata(row['output'])['audio_seconds'],.3)
        self.assertTrue((self.base/'restored').exists())
        self.assertFalse(json.loads(self.state.read_text())['state']['prefix_cache'])
        self.assertEqual(self.add(),jid)
        with db() as c:
            self.assertEqual(c.execute('select count(*) from benchmarks').fetchone()[0],0)
            self.assertEqual(c.execute('select count(*) from provider_metrics').fetchone()[0],1)
            self.assertEqual(estimate(c,json.loads(row['spec']))['samples'],1)
        self.assertEqual(json.loads((out/'verified.json').read_text())['provider'],'tts')
    def test_stop_tts_preserves_wrapper_restoration_and_attempt(self):
        jid=self.add({**self.raw,'text':'slow'});out=self.start(jid);self.wait_file(out/'fake-engine-started')
        with patch('h3queue.cli.ensure_worker'):control('stop')
        row=self.settle(jid);self.assertEqual(row['status'],'queued');self.assertTrue((self.base/'restored').exists())
        self.assertFalse((out/'verified.json').exists())
    def test_failure_retry_new_attempt_preserves_evidence(self):
        jid=self.add({**self.raw,'text':'fail'});old=self.start(jid);self.assertEqual(self.settle(jid)['status'],'failed')
        self.assertTrue((self.base/'restored').exists())
        with db() as c:prepare_retry(c,c.execute('select * from jobs where id=?',(jid,)).fetchone())
        tick();self.assertNotEqual(self.out(jid),old);self.assertEqual(self.settle(jid)['status'],'failed')
        self.assertTrue((old/'render.log').exists())
    def test_waiting_shared_lock_is_cancellable_without_touching_qwen(self):
        jid=self.add()
        with (self.base/'.codex-inference.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            out=self.start(jid);self.wait_file(out/'phase.json');time.sleep(.3)
            self.assertFalse((out/'fake-engine-started').exists());self.assertFalse((self.base/'stopped').exists())
            with patch('h3queue.cli.ensure_worker'):control('stop')
            self.assertEqual(self.settle(jid)['status'],'queued')
            self.assertFalse((self.base/'stopped').exists())
    def test_two_providers_use_the_same_lock(self):
        raw,_=self.command(device='cpu');jid=self.add(raw)
        with (self.base/'.codex-inference.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);out=self.start(jid);self.wait_file(out/'phase.json');time.sleep(.3)
            self.assertFalse((out/'artifacts/result.json').exists())
        self.assertEqual(self.settle(jid)['status'],'completed')
        self.assertFalse((self.base/'stopped').exists())
    def test_gpu_command_restores_qwen_and_payload_is_data(self):
        raw,_=self.command(device='gpu');jid=self.add(raw);out=self.start(jid);row=self.settle(jid)
        self.assertEqual(row['status'],'completed',row)
        self.assertEqual(json.loads(Path(row['output']).read_text()),raw['payload'])
        self.assertTrue((self.base/'restored').exists());self.assertFalse((out/'NEVER').exists())
    def test_priority_and_single_active_across_providers(self):
        a=self.add({**self.raw,'text':'slow'});raw,_=self.command()
        with db() as c:b=enqueue(c,raw,'urgent',priority=5)['id']
        out=self.start(b);self.assertEqual(self.row(a)['status'],'queued')
        self.assertEqual(self.settle(b)['status'],'completed')
        with db() as c:setv(c,'mode','paused')
    def test_batch_rollback_and_dedup(self):
        with db() as c:
            with self.assertRaises(ValueError):enqueue_batch(c,{'schema_version':1,'defaults':self.raw,'jobs':[{'request':{}},{'request':{'profile':'missing'}}]})
            self.assertEqual(c.execute('select count(*) from jobs').fetchone()[0],0)
            result=enqueue_batch(c,{'schema_version':1,'defaults':self.raw,'jobs':[{'request':{}},{'request':{}}]})
            self.assertEqual(result['jobs'][0]['id'],result['jobs'][1]['id']);self.assertEqual(get(c,'mode'),'paused')
    def test_reference_profile_and_input_changes_fail_closed(self):
        path=self.root/'reference.wav';wav(path)
        raw={**self.raw,'profile':'clone','reference_audio':str(path),'reference_text':'hello'}
        spec=normalize(raw,self.base);validate_spec(spec);wav(path,silent=True)
        with self.assertRaises(DeploymentChanged):validate_spec(spec)
        with self.assertRaises(ValueError):normalize(raw,self.base)
        with self.assertRaises(ValueError):normalize({**self.raw,'profile':'clone'},self.base)
    def test_model_change_is_not_accepted_by_refresh(self):
        jid=self.add();(self.base/'TTS/model/config.json').write_text('{"changed":true}')
        with db() as c:
            c.execute("update jobs set status='failed' where id=?",(jid,))
            with self.assertRaises(DeploymentChanged):prepare_retry(c,c.execute('select * from jobs where id=?',(jid,)).fetchone(),True)
    def test_profile_changes_isolated_and_no_parameter_refresh(self):
        jid=self.add();spec=json.loads(self.row(jid)['spec'])
        self.profiles['clone']['languages']=['fr'];atomic_json(self.base/'TTS/profiles.json',self.profiles);validate_spec(spec)
        self.profiles['fake']['languages']=['en'];atomic_json(self.base/'TTS/profiles.json',self.profiles)
        with self.assertRaises(DeploymentChanged):validate_spec(spec)
        with db() as c:
            c.execute("update jobs set status='failed' where id=?",(jid,))
            with self.assertRaises(ValueError):prepare_retry(c,c.execute('select * from jobs where id=?',(jid,)).fetchone(),True)
    def test_command_dependency_and_assets_pinned(self):
        raw,manifest=self.command();asset=self.root/'input.txt';asset.write_text('old');raw['assets']={'source':str(asset)}
        spec=normalize(raw,self.base);asset.write_text('new')
        with self.assertRaises(DeploymentChanged):validate_spec(spec)
        raw.pop('assets');spec=normalize(raw,self.base)
        (self.root/'fake-command.py').write_text('changed')
        with self.assertRaises(DeploymentChanged):validate_spec(spec)
    def test_manifest_validation_and_registration_do_not_run(self):
        raw,file=self.command();self.assertFalse((self.base/'stopped').exists())
        with self.assertRaises(ValueError):register(file)
        manifest=json.loads(file.read_text());manifest['argv'][0]='python';atomic_json(file,manifest)
        with self.assertRaises(ValueError):register(file,True)
        with self.assertRaises(ValueError):normalize({'provider':'../escape'},self.base)
        with self.assertRaises(ValueError):normalize({**self.raw,'schema_version':2},self.base)
        with self.assertRaises(ValueError):normalize({**self.raw,'options':{'ref_audio':'other'}},self.base)
    def test_audio_validator_rejects_silent_truncated_and_external_outputs(self):
        from h3queue.artifacts import verify
        from types import SimpleNamespace
        path=self.root/'bad.wav';wav(path,silent=True)
        with self.assertRaises(ValueError):audio_metadata(path)
        wav(path);path.write_bytes(path.read_bytes()[:-50])
        with self.assertRaises(ValueError):audio_metadata(path)
        with self.assertRaises(ValueError):verify(SimpleNamespace(out=self.root/'other'),path,'file')
    def test_cli_catalog_and_batch_do_not_enable_computation(self):
        file=self.root/'batch.json';atomic_json(file,{'schema_version':1,'defaults':self.raw,'jobs':[{'request':{}}]})
        with patch('h3queue.cli.ensure_worker'),contextlib.redirect_stdout(io.StringIO()):main(['enqueue-batch',str(file)])
        s=snapshot();self.assertEqual(s['settings']['mode'],'paused');self.assertIsNone(s['active'])
        self.assertIn('tts',[p['id'] for p in catalog(self.base)])
    def test_existing_v3_rows_survive_migration(self):
        jid=self.add();before=self.row(jid)
        c=sqlite3.connect(self.root/'state/queue.sqlite3');c.execute('drop table provider_metrics');c.execute('pragma user_version=3');c.commit();c.close()
        with db() as c:self.assertEqual(c.execute('pragma user_version').fetchone()[0],4)
        self.assertEqual(before,self.row(jid))

    def test_public_standalone_example_without_model_environment(self):
        demo=self.root/'standalone example'
        subprocess.run([sys.executable,str(ROOT/'scripts/prepare-demo.py'),str(demo)],check=True,capture_output=True)
        register(demo/'provider.json')
        with db() as c:setv(c,'deployment',str(demo/'deployment'))
        jid=self.add(json.loads((demo/'request.json').read_text()))
        self.start(jid);row=self.settle(jid)
        self.assertEqual(row['status'],'completed',row)
        self.assertEqual(json.loads(Path(row['output']).read_text()),{'received':{'text':'Hello, local queue!'}})
        self.assertFalse((self.base/'stopped').exists())


if __name__=='__main__':unittest.main()
