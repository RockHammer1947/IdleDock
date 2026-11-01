import json,os,subprocess,tempfile,time,unittest,wave
from pathlib import Path
from unittest.mock import patch
from h3queue.store import db,setv,digest,atomic_json
from h3queue.jobs import enqueue,normalize
from h3queue.integrity import validate_spec,DeploymentChanged
from h3queue.recovery import prepare_retry,reuse_raw
from h3queue.executor import normalization_command
from h3queue.supervisor import main as supervise
from h3queue.worker import settle

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'H3_QUEUE_HOME':str(self.root/'state')});self.env.start()
        self.base=self.root/'base';(self.base/'H3').mkdir(parents=True)
        for name in ['agent_session.py','H3/generate_fast.py','H3/resource_monitor.py']:(self.base/name).write_text('original')
        for name in ['engine','portrait']:(self.root/name).write_bytes(name.encode())
        self.audio=self.root/'drive.wav'
        with wave.open(str(self.audio),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\0\0'*564336)
        self.raw={'profile':'native20','adapter':'native-audio','width':32,'height':32,'frames':294,'prompt':'test',
            'engine':str(self.root/'engine'),'portrait':str(self.root/'portrait'),'audio':str(self.audio),
            'trim_s':0.9403333333333315,'delivery_frames':314,'delivery_height':32}
        with db() as c:
            setv(c,'deployment',str(self.base));self.jid=enqueue(c,self.raw,'recovery')['id']
            c.execute("UPDATE jobs SET status='failed' WHERE id=?",(self.jid,))
        self.out=self.root/'old-attempt';self.out.mkdir()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def row(self,c):return c.execute('SELECT * FROM jobs WHERE id=?',(self.jid,)).fetchone()
    def prior(self):
        with db() as c:
            spec=json.loads(self.row(c)['spec'])
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('a',self.jid,time.time(),'failed',str(self.out)))
            c.execute("UPDATE jobs SET attempt_id='a' WHERE id=?",(self.jid,))
        atomic_json(self.out/'request.json',{'spec':spec})
        atomic_json(self.out/'render.result.json',{'exit_code':0,'aborted':None,'elapsed_s':100})
        (self.out/'render.log').write_text('audio-drive invariant PASS')
        (self.out/'video.mp4').write_bytes(b'original-render')
    def test_native_pins_follow_used_entrypoints(self):
        s=normalize(self.raw,self.base)
        self.assertEqual([Path(p).name for p,_ in s['deployment_pins']],['agent_session.py'])
        (self.base/'H3/generate_fast.py').write_text('profile-only update')
        validate_spec(s)
        (self.root/'engine').write_bytes(b'changed engine')
        with self.assertRaises(DeploymentChanged):validate_spec(s)
    def test_refresh_requires_review_and_never_accepts_changed_input(self):
        (self.base/'agent_session.py').write_text('reviewed update')
        with db() as c:
            with self.assertRaises(DeploymentChanged):prepare_retry(c,self.row(c))
            prepare_retry(c,self.row(c),refresh_deployment=True)
            self.assertEqual(self.row(c)['status'],'queued')
            c.execute("UPDATE jobs SET status='failed' WHERE id=?",(self.jid,))
        (self.root/'portrait').write_bytes(b'different person')
        with db() as c:
            with self.assertRaises(DeploymentChanged):prepare_retry(c,self.row(c),refresh_deployment=True)
            self.assertEqual(self.row(c)['status'],'failed')
    def test_reuse_retains_job_and_history_and_checks_source_hash(self):
        self.prior()
        with db() as c:
            prepare_retry(c,self.row(c),refresh_deployment=True,reuse_render=True)
            s=json.loads(self.row(c)['spec'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT status FROM attempts').fetchone()[0],'failed')
        new=self.root/'new';new.mkdir();reuse_raw(s,new)
        self.assertEqual((new/'video.mp4').read_bytes(),b'original-render')
        (self.out/'video.mp4').write_bytes(b'tampered')
        with self.assertRaises(ValueError):reuse_raw(s,new)
    def test_dependency_error_precedes_wrapper_and_pauses_queue(self):
        self.prior();(self.base/'agent_session.py').write_text('changed')
        with patch('h3queue.supervisor.subprocess.Popen') as popen:
            supervise(self.out/'request.json');popen.assert_not_called()
        with db() as c:
            setv(c,'mode','manual')
            row=c.execute("SELECT * FROM attempts WHERE id='a'").fetchone();settle(c,row)
            self.assertEqual(json.loads(c.execute("SELECT value FROM settings WHERE key='mode'").fetchone()[0]),'paused')
            self.assertIn('agent_session.py',self.row(c)['error'])
    def test_stopped_delivery_retry_can_reuse_original_render(self):
        self.prior()
        with db() as c:
            prepare_retry(c,self.row(c),reuse_render=True)
            s=json.loads(self.row(c)['spec'])
            stopped=self.root/'stopped';stopped.mkdir();(stopped/'STOP').touch()
            atomic_json(stopped/'request.json',{'spec':s})
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('b',self.jid,time.time(),'failed',str(stopped)))
            c.execute("UPDATE jobs SET status='failed',attempt_id='b' WHERE id=?",(self.jid,))
            prepare_retry(c,self.row(c),reuse_render=True)
            self.assertEqual(json.loads(self.row(c)['spec'])['reuse_render']['directory'],str(self.out))
    def test_worker_waits_for_new_sampler_before_claim(self):
        from h3queue.worker import tick
        from h3queue.store import get
        now=time.time()
        with db() as c:
            setv(c,'mode','manual');c.execute("UPDATE jobs SET status='queued' WHERE id=?",(self.jid,))
        with patch('h3queue.worker.SAMPLE_NOT_BEFORE',now),patch('h3queue.worker.sample_from',return_value={'time':now-10,'age_seconds':10,'cpu_c':40,'gpu_c':40}):
            tick()
        with db() as c:
            self.assertEqual(self.row(c)['status'],'queued')
            self.assertEqual(get(c,'reason'),'等待监测首次采样')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)
    def test_fractional_trim_keeps_314_frames_and_zero_start(self):
        from h3queue.system_tools import require_tool
        ff=require_tool('ffmpeg');fp=require_tool('ffprobe')
        source=self.root/'raw.mp4';output=self.root/'delivery.mp4'
        subprocess.run([ff,'-v','error','-f','lavfi','-i','color=c=blue:s=32x32:r=24','-frames:v','294','-c:v','libx264','-threads','2',str(source)],check=True,timeout=30)
        subprocess.run(normalization_command(ff,self.raw,source,output),check=True,timeout=30)
        streams=json.loads(subprocess.check_output([fp,'-v','error','-count_frames','-show_streams','-of','json',str(output)]))['streams']
        video=next(x for x in streams if x['codec_type']=='video');audio=next(x for x in streams if x['codec_type']=='audio')
        self.assertEqual(int(video['nb_read_frames']),314)
        self.assertEqual(float(video['start_time']),0)
        self.assertAlmostEqual(float(video['duration']),314/30,places=5)
        self.assertLess(abs(float(audio['duration'])-314/30),0.025)

if __name__=='__main__':unittest.main()
