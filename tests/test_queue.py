import contextlib,io,json,os,sqlite3,subprocess,sys,tempfile,time,unittest,wave
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from h3queue.store import db,get,setv,digest,ROOT
from h3queue.jobs import enqueue
from h3queue.schedule import within,allowed,minutes
from h3queue.worker import tick
from h3queue.cli import control
from h3queue.system_tools import require_tool

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'H3_QUEUE_HOME':str(self.root/'state')});self.env.start()
        self.base=self.root/'deployment';self.base.mkdir()
        self.raw={'profile':'native20','width':32,'height':32,'frames':7,'prompt':'test'}
        with db() as c:
            setv(c,'deployment',str(self.base));policy=get(c,'safety');policy['require_telemetry']=False;policy['min_disk_gib']=2;policy['min_available_gib']=1;setv(c,'safety',policy)
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def add(self,raw=None):
        with db() as c:return enqueue(c,raw or self.raw,'test')['id']
    def status(self,jid):
        with db() as c:return dict(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    def test_default_paused_and_dedup(self):
        a=self.add();b=self.add();self.assertEqual(a,b)
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
        tick();self.assertEqual(self.status(a)['status'],'queued')
    def test_pause_stop_and_retry_semantics(self):
        jid=self.add();out=self.root/'attempt';out.mkdir()
        with db() as c:
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('a',jid,time.time(),'running',str(out)))
        with patch('h3queue.cli.ensure_worker'):
            control('pause');self.assertFalse((out/'STOP').exists())
            control('stop');self.assertTrue((out/'STOP').exists())
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
    def test_status_distinguishes_finish_then_pause_from_immediate_stop(self):
        from h3queue.cli import snapshot
        jid=self.add();out=self.root/'ui-status';out.mkdir()
        with db() as c:
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('ui',jid,time.time(),'running',str(out)))
            c.execute("UPDATE jobs SET status='running',attempt_id='ui' WHERE id=?",(jid,))
        with patch('h3queue.cli.ensure_worker'):
            control('pause');self.assertFalse(snapshot()['active']['stop_requested'])
            control('stop');self.assertTrue(snapshot()['active']['stop_requested'])
    def test_frame_and_audio_validation(self):
        with self.assertRaises(ValueError):self.add({**self.raw,'frames':8})
        with self.assertRaises(ValueError):self.add({**self.raw,'width':33})
        engine=self.root/'h3';engine.write_bytes(b'engine');portrait=self.root/'portrait';portrait.write_bytes(b'photo');audio=self.root/'a.wav'
        with wave.open(str(audio),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'')
        with self.assertRaises(ValueError):self.add({**self.raw,'adapter':'native-audio','frames':73,'engine':str(engine),'portrait':str(portrait),'audio':str(audio)})
    def test_cross_midnight_and_timezone(self):
        w={'start':'23:00','end':'07:00','timezone':'Asia/Shanghai'}
        for hour,expected in [(22,False),(23,True),(0,True),(6,True),(7,False)]:
            self.assertEqual(within(w,datetime(2026,10,27,hour,0,tzinfo=ZoneInfo('Asia/Shanghai'))),expected)
        self.assertTrue(within(w,datetime(2026,10,26,16,0,tzinfo=ZoneInfo('UTC'))))
        self.assertFalse(allowed('paused',w,False,0)[0]);self.assertTrue(allowed('manual',w,True,99,idle=0)[0])
        with self.assertRaises(ValueError):minutes('24:00')
    def test_stale_attempt_recovery(self):
        jid=self.add();out=self.root/'stale';out.mkdir()
        with db() as c:
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('a',jid,time.time(),'running',str(out)))
            c.execute("UPDATE jobs SET status='running',attempt_id='a' WHERE id=?",(jid,))
        tick();self.assertEqual(self.status(jid)['status'],'failed')
    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with db() as c:setv(c,'mode','manual');raise RuntimeError()
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
    def test_cache_corruption_is_not_reused(self):
        jid=self.add();output=self.root/'video.mp4';output.write_bytes(b'valid')
        with db() as c:
            c.execute("UPDATE jobs SET status='completed',output=?,output_sha=? WHERE id=?",(str(output),digest(output),jid))
        output.write_bytes(b'corrupt');self.assertEqual(self.add(),jid)
        self.assertEqual(self.status(jid)['status'],'failed')
    def test_auto_requires_both_window_and_idle(self):
        window={'start':'00:00','end':'00:00','timezone':'Asia/Shanghai'}
        self.assertFalse(allowed('auto',window,True,10,idle=599)[0])
        self.assertTrue(allowed('auto',window,True,10,idle=600)[0])
        self.assertTrue(allowed('auto',window,False,10,idle=0)[0])
    def test_window_end_requests_owned_stop(self):
        jid=self.add();out=self.root/'active';out.mkdir()
        with db() as c:
            setv(c,'mode','auto');setv(c,'stop_at_end',True)
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('a',jid,time.time(),'running',str(out)))
        with patch('h3queue.worker.within',return_value=False),patch('h3queue.worker.running_attempt',return_value=True):tick()
        self.assertTrue((out/'STOP').exists())
    def test_stop_during_restoration_keeps_completed_video(self):
        from h3queue.store import atomic_json
        jid=self.add();out=self.root/'restoring';out.mkdir();video=out/'video.mp4';video.write_bytes(b'verified')
        atomic_json(out/'verified.json',{'output':str(video),'sha':digest(video),'elapsed':10})
        atomic_json(out/'receipt.json',{'code':0});(out/'STOP').touch()
        with db() as c:
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('a',jid,time.time(),'running',str(out)))
            c.execute("UPDATE jobs SET status='running',attempt_id='a' WHERE id=?",(jid,))
        tick();self.assertEqual(self.status(jid)['status'],'completed')
    def test_cache_fingerprint_changes_with_prompt(self):
        a=self.add();b=self.add({**self.raw,'prompt':'different'})
        self.assertNotEqual(a,b)
    def fixture(self,slow=False):
        base=self.base
        for path in ['Qwen3.8/.venv/bin','H3/minimax-h3-mlx/.venv/bin']:
            p=base/path;p.mkdir(parents=True);(p/'python').write_text('#!/bin/sh\nexec '+sys.executable+' \"$@\"\n');(p/'python').chmod(0o755)
        (base/'agent_session.py').write_text('''import os,sys,subprocess,json\nfrom pathlib import Path\nout=Path(sys.argv[-1]).parent\n(out/'fake-qwen-stopped').touch()\ntry:\n e=dict(os.environ);e['LOCAL_MODEL_SESSION_TARGET']='h3'\n code=subprocess.run(sys.argv[3:],env=e).returncode\nfinally:(out/'fake-qwen-restored').touch()\nsys.exit(code)\n''')
        (base/'H3/generate_fast.py').write_text('''import sys,subprocess,time\nfrom pathlib import Path\na=sys.argv;output=a[a.index('--out')+1]\n(Path(output).parent/'fake-engine-started').touch()\n'''+('time.sleep(60)\n' if slow else '')+'''subprocess.run(['''+repr(require_tool('ffmpeg'))+''','-v','error','-f','lavfi','-i','color=c=blue:s=32x32:r=24','-f','lavfi','-i','anullsrc=r=32000:cl=mono','-t','0.3','-c:v','libx264','-c:a','aac',output],check=True)\n''')
        (base/'H3/resource_monitor.py').write_text('''import subprocess,time,json\nfrom pathlib import Path\nOUT=Path('.')\ndef run(name,cmd,cwd,metadata=None,env=None):\n start=time.monotonic()\n with (OUT/(name+'.log')).open('w') as f:\n  p=subprocess.Popen(['/usr/bin/time','-l',*cmd],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);code=p.wait()\n d={'exit_code':code,'elapsed_s':time.monotonic()-start};(OUT/(name+'.result.json')).write_text(json.dumps(d));return d\n''')
    def run_until_settled(self,jid,timeout=20):
        until=time.time()+timeout
        while time.time()<until:
            tick();s=self.status(jid)
            if s['status'] not in ['running','cancel_requested']:return s
            time.sleep(.15)
        self.fail('Attempt did not settle')
    def test_real_supervisor_fake_backend_success_and_cache(self):
        self.fixture();jid=self.add()
        with db() as c:setv(c,'mode','manual')
        tick();self.assertEqual(self.status(jid)['status'],'running')
        result=self.run_until_settled(jid);self.assertEqual(result['status'],'completed',result)
        out=Path(result['output']).parent;self.assertTrue((out/'fake-qwen-restored').exists())
        with db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM benchmarks').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM cache').fetchone()[0],1)
        self.assertEqual(self.add(),jid)
    def test_immediate_stop_releases_child_and_preserves_queue(self):
        self.fixture(slow=True);jid=self.add()
        with db() as c:setv(c,'mode','manual')
        tick();row=self.status(jid)
        with db() as c:out=Path(c.execute('SELECT directory FROM attempts WHERE id=?',(row['attempt_id'],)).fetchone()[0])
        deadline=time.time()+10
        while not (out/'fake-engine-started').exists() and time.time()<deadline:time.sleep(.1)
        self.assertTrue((out/'fake-engine-started').exists(),(out/'session.log').read_text())
        with patch('h3queue.cli.ensure_worker'):control('stop')
        result=self.run_until_settled(jid);self.assertEqual(result['status'],'queued')
        self.assertTrue((out/'fake-qwen-restored').exists())
        self.assertFalse((out/'verified.json').exists())
        with db() as c:self.assertEqual(get(c,'mode'),'paused')

if __name__=='__main__':unittest.main()
