"""Adversarial tests use tiny CPU subprocesses and isolated state; never real H3."""
import concurrent.futures,json,os,signal,sqlite3,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import psutil
from h3queue import safety
from h3queue.store import db,get,setv,home,atomic_json,ROOT
from h3queue.jobs import enqueue
from h3queue.cli import snapshot,control
from h3queue.telemetry import Energy,Sampler,finite,prune
from h3queue.processes import matches,signal_owned,members,cleanup
from h3queue.guarded_run import run
from h3queue.worker import tick
from h3queue.estimate import machine
import test_queue as queue_tests

class SafetyTests(unittest.TestCase):
    setUp=queue_tests.QueueTests.setUp
    tearDown=queue_tests.QueueTests.tearDown
    add=queue_tests.QueueTests.add
    status=queue_tests.QueueTests.status
    fixture=queue_tests.QueueTests.fixture
    run_until_settled=queue_tests.QueueTests.run_until_settled
    def policy(self):return {**safety.DEFAULTS,'require_telemetry':False,'min_disk_gib':2,'min_available_gib':1}
    def test_policy_rejects_nan_infinity_bool_unknown_and_inverted_thresholds(self):
        for invalid in ({'stop_c':float('nan')},{'stop_c':float('inf')},{'stop_c':True},{'unknown':1},{'stop_c':70},{'sound':1},{'hold_seconds':0}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):safety.validate(invalid)
    def test_sensor_rejects_malformed_future_and_nan(self):
        path=self.root/'sensor.json'
        for value in ([],{'time':200,'cpu_c':50,'gpu_c':40},{'time':100,'cpu_c':float('nan'),'gpu_c':40},{'time':100,'cpu_c':True,'gpu_c':40}):
            path.write_text(json.dumps(value));self.assertGreater(safety.sample_from(path,100)['age_seconds'],10000)
        path.write_text(json.dumps({'time':95,'cpu_c':50,'gpu_c':40}));self.assertEqual(safety.sample_from(path,100)['age_seconds'],5)
    def test_hysteresis_hold_critical_and_stale(self):
        p=safety.DEFAULTS;l=safety.ThermalLatch();s={'age_seconds':0,'cpu_c':86,'gpu_c':40}
        self.assertEqual(l.update(s,p,0),'normal');self.assertEqual(l.update(s,p,9),'normal')
        self.assertEqual(l.update(s,p,10),'warning');self.assertEqual(l.update({**s,'cpu_c':82},p,11),'warning')
        self.assertEqual(l.update({**s,'cpu_c':79},p,12),'normal')
        l.update({**s,'gpu_c':96},p,20);self.assertEqual(l.update({**s,'gpu_c':96},p,30),'critical')
        self.assertEqual(l.update({'age_seconds':25},p,31),'unavailable')
    def test_resource_limits_without_pressure_on_machine(self):
        p=self.policy();s={'age_seconds':0,'cpu_c':40,'gpu_c':40}
        with patch('h3queue.safety.shutil.disk_usage',return_value=SimpleNamespace(free=1024**3)):
            self.assertIn('磁盘',safety.blocked(p,s,self.root))
        self.assertIn('内存',safety.blocked(p,s,self.root,available_gib=.5))
        self.assertIn('交换',safety.blocked(p,s,self.root,swap_growth_gib=9))
        self.assertIn('时限',safety.blocked(p,s,self.root,runtime_s=15000))
        self.assertIn('失联',safety.blocked({**p,'require_telemetry':True},{},self.root))
    def test_energy_integrates_and_excludes_sleep_and_invalid_power(self):
        e=Energy();p=safety.DEFAULTS
        for t in range(0,3601,10):e.add(t,100,p)
        self.assertAlmostEqual(e.chip_wh,100);self.assertAlmostEqual(e.wall_wh,145);self.assertEqual(e.coverage_s,3600)
        e.add(4000,100,p);self.assertAlmostEqual(e.chip_wh,100)
        e.add(4001,float('nan'),p);e.add(4002,100,p);self.assertAlmostEqual(e.chip_wh,100)
        self.assertIsNone(finite(float('nan')));self.assertIsNone(finite(True))
    def test_telemetry_and_event_retention_bounded(self):
        now=time.time()
        with db() as c:
            c.executemany('INSERT INTO telemetry(time,data) VALUES(?,?)',[(now,'{}')]*20200+[(0,'{}')])
            c.executemany('INSERT INTO events(time,kind,data) VALUES(?,?,?)',[(now,'test','{}')]*20020)
            prune(c,now)
            self.assertEqual(c.execute('SELECT count(*) FROM telemetry').fetchone()[0],20160)
            self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],20000)
            self.assertGreater(c.execute('SELECT min(time) FROM telemetry').fetchone()[0],0)
    def test_parallel_enqueue_is_idempotent(self):
        def put(_):
            with db() as c:return enqueue(c,self.raw,'same')['id']
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:ids=list(pool.map(put,range(36)))
        self.assertEqual(len(set(ids)),1)
        with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
    def test_invalid_sensor_blocks_manual_and_auto(self):
        with db() as c:p=get(c,'safety');p['require_telemetry']=True;setv(c,'safety',p)
        with patch('h3queue.cli.ensure_worker'):
            for action in ('start','auto'):
                with self.assertRaises(ValueError):control(action)
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
    def test_guarded_postprocess_stop_and_term_resistant_child(self):
        out=self.root/'stop';out.mkdir();marker=out/'ready'
        command=[sys.executable,'-c',"import signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path("+repr(str(marker))+").touch();time.sleep(60)"]
        def stop():
            until=time.monotonic()+5
            while not marker.exists() and time.monotonic()<until:time.sleep(.02)
            (out/'STOP').touch()
        stopper=threading.Thread(target=stop);stopper.start();start=time.monotonic()
        result=run(command,self.root,out,'postprocess',self.policy());stopper.join()
        self.assertLess(time.monotonic()-start,6);self.assertIsNotNone(result['aborted'])
        record=json.loads((out/'owned-group.json').read_text());self.assertFalse(any(matches(p) for p in record['members']))
    def test_orphan_grandchild_reaped_and_unrelated_process_untouched(self):
        out=self.root/'orphans';out.mkdir();pidfile=out/'child'
        child="import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
        parent="import subprocess,time;from pathlib import Path;p=subprocess.Popen(["+repr(sys.executable)+",'-c',"+repr(child)+"]);Path("+repr(str(pidfile))+").write_text(str(p.pid));time.sleep(1.2)"
        other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
        try:
            run([sys.executable,'-c',parent],self.root,out,'render',self.policy())
            self.assertIsNone(other.poll());record=json.loads((out/'owned-group.json').read_text())
            self.assertGreaterEqual(len(record['members']),2);self.assertFalse(any(matches(p) for p in record['members']))
        finally:other.terminate();other.wait()
    def test_pid_reuse_guard_will_not_signal(self):
        item={'pid':os.getpid(),'born':psutil.Process().create_time()-100}
        with patch('h3queue.processes.os.killpg') as kill:
            self.assertFalse(signal_owned({'pgid':os.getpgrp(),'members':[item]},signal.SIGKILL));kill.assert_not_called()
    def test_live_invalid_policy_stops_and_writes_trip(self):
        out=self.root/'invalid';out.mkdir();(home()/'safety.json').write_text('{bad')
        r=run([sys.executable,'-c','import time;time.sleep(60)'],self.root,out,'media',self.policy())
        self.assertIn('配置无效',r['aborted']);self.assertTrue((out/'guard-trip.json').exists())
    def test_sustained_heat_stops_fake_render(self):
        out=self.root/'hot';out.mkdir();p={**self.policy(),'hold_seconds':3}
        # First preflight is cool; then sustained high samples, without heating the Mac.
        hot={'age_seconds':0,'cpu_c':96,'gpu_c':40};cool={**hot,'cpu_c':40};calls=[0]
        def sensor(*_):calls[0]+=1;return cool if calls[0]==1 else hot
        with patch('h3queue.guarded_run.sample_from',side_effect=sensor):
            start=time.monotonic();r=run([sys.executable,'-c','import time;time.sleep(60)'],self.root,out,'hot',p)
        self.assertIn('温度',r['aborted']);self.assertGreaterEqual(time.monotonic()-start,3)
    def test_safety_trip_latches_pause_after_cooling(self):
        jid=self.add();out=self.root/'trip';out.mkdir();atomic_json(out/'guard-trip.json',{'reason':'温度达到停止阈值','time':time.time()});atomic_json(out/'receipt.json',{'code':130})
        with db() as c:
            setv(c,'mode','manual');c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('a',jid,time.time(),'running',str(out)))
            c.execute("UPDATE jobs SET status='running',attempt_id='a' WHERE id=?",(jid,))
        tick();tick()
        with db() as c:self.assertEqual(get(c,'mode'),'paused');self.assertIsNotNone(get(c,'safety_latch'))
        self.assertEqual(self.status(jid)['status'],'failed')
    def test_two_workers_same_home_single_owner(self):
        env=dict(os.environ);first=subprocess.Popen([sys.executable,'-m','h3queue.worker'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+5
            while not (home()/'worker.json').exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual(json.loads((home()/'worker.json').read_text())['pid'],first.pid)
            other=subprocess.run([sys.executable,'-m','h3queue.worker'],cwd=ROOT,env=env,timeout=5,capture_output=True)
            self.assertEqual(other.returncode,0);self.assertEqual(json.loads((home()/'worker.json').read_text())['pid'],first.pid)
        finally:first.terminate();first.wait(timeout=8)
    def test_large_queue_bounded_status_and_requeued_eta(self):
        spec={**self.raw,'adapter':'profile'};now=time.time()
        with db() as c:
            c.executemany('INSERT INTO jobs(id,fingerprint,title,spec,status,priority,created,updated) VALUES(?,?,?,?,?,?,?,?)',[(str(i),str(i),'job',json.dumps(spec),'queued',0,now,now) for i in range(5000)])
            c.execute('INSERT INTO benchmarks VALUES(?,?,?,?,?,?,?,?)',('sample','native20',32,32,7,100,machine(),now))
            c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',('old','0',now-10000,'interrupted',str(self.root)))
            c.execute("UPDATE jobs SET attempt_id='old' WHERE id='0'")
        started=time.perf_counter();r=snapshot();elapsed=time.perf_counter()-started
        self.assertEqual(r['total_jobs'],5000);self.assertEqual(len(r['jobs']),200)
        self.assertEqual(r['estimate_seconds'],500000);self.assertLess(elapsed,2)
        (ROOT/'.build').mkdir(exist_ok=True);atomic_json(ROOT/'.build/adversarial-performance.json',{'jobs':5000,'returned_jobs':200,'snapshot_seconds':elapsed,'json_bytes':len(json.dumps(r))})
    @patch('h3queue.telemetry.platform.system',return_value='Darwin')
    def test_sampler_recovers_from_initial_database_lock(self, _platform):
        from h3queue import telemetry
        actual=telemetry.db;calls=[0]
        def flaky():
            calls[0]+=1
            if calls[0]==1:raise sqlite3.OperationalError('database is locked')
            return actual()
        sampler=Sampler(self.base)
        with patch('h3queue.telemetry.db',side_effect=flaky):
            sampler.start()
            try:
                deadline=time.monotonic()+4
                while calls[0]<2 and time.monotonic()<deadline:time.sleep(.05)
                self.assertGreaterEqual(calls[0],2);self.assertTrue(sampler.thread.is_alive())
            finally:sampler.close()
    def test_historical_energy_calibration_never_launches_render(self):
        import contextlib,io
        from h3queue.cli import main
        metric=self.root/'history.json';atomic_json(metric,{'exit_code':0,'chip_power_w':{'mean':100}})
        with db() as c:c.execute('INSERT INTO benchmarks VALUES(?,?,?,?,?,?,?,?)',(str(metric),'native20',32,32,7,100,machine(),time.time()))
        with patch('h3queue.cli.ensure_worker') as worker,contextlib.redirect_stdout(io.StringIO()):main(['calibrate-energy'])
        worker.assert_not_called()
        with db() as c:self.assertEqual(c.execute('SELECT chip_w FROM energy_metrics').fetchone()[0],100);self.assertEqual(get(c,'mode'),'paused')
    @patch('h3queue.telemetry.platform.system',return_value='Darwin')
    def test_sampler_handles_nonfinite_power_and_shuts_down_child(self, _platform):
        binary=self.base/'H3/tools/macmon/macmon';binary.parent.mkdir(parents=True)
        binary.write_text('#!'+sys.executable+'\nimport json,time\nwhile True:\n print(json.dumps({"temp":{"cpu_temp_avg":40,"gpu_temp_avg":40},"all_power":float("nan")}),flush=True);time.sleep(.1)\n');binary.chmod(0o755)
        sampler=Sampler(self.base);sampler.start()
        try:
            deadline=time.monotonic()+5
            while not (home()/'telemetry.json').exists() and time.monotonic()<deadline:time.sleep(.05)
            d=json.loads((home()/'telemetry.json').read_text());self.assertIsNone(d['chip_w']);self.assertTrue(sampler.thread.is_alive())
        finally:sampler.close()
        self.assertFalse(sampler.thread.is_alive());self.assertIsNotNone(sampler.proc.poll())

if __name__=='__main__':unittest.main()
