"""Smart idle scheduling; no real H3 work or input events are generated."""
import contextlib,io,json,os,subprocess,sys,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import test_queue as queue_tests
from h3queue.store import db,get,setv,home,atomic_json
from h3queue.schedule import allowed,smart_state,idle_seconds,smart_guard,runtime_state
from h3queue.cli import main,control,snapshot
from h3queue import worker
from h3queue.guarded_run import run

class SmartTests(unittest.TestCase):
    setUp=queue_tests.QueueTests.setUp
    tearDown=queue_tests.QueueTests.tearDown
    add=queue_tests.QueueTests.add
    status=queue_tests.QueueTests.status
    def test_smart_threshold_independent_of_daily_window(self):
        for idle,expected in [(0,False),(599.9,False),(600,True),(3600,True)]:
            with patch('h3queue.schedule.within',return_value=False) as window:
                self.assertEqual(allowed('smart',{},False,10,idle=idle)[0],expected);window.assert_not_called()
        self.assertFalse(allowed('paused',{},False,10,idle=3600)[0])
    @patch('h3queue.schedule.platform.system',return_value='Darwin')
    def test_missing_invalid_or_unreadable_idle_fails_closed(self, _platform):
        for idle in [None,-1,float('nan'),float('inf'),True]:
            self.assertFalse(smart_state(10,idle)['ready']);self.assertIsNone(smart_state(10,idle)['remaining_seconds'])
        with patch('h3queue.schedule.subprocess.check_output',return_value='HID data missing'):
            self.assertIsNone(idle_seconds());self.assertFalse(allowed('smart',{},False,10)[0])
        with patch('h3queue.schedule.subprocess.check_output',side_effect=subprocess.TimeoutExpired('ioreg',3)):
            self.assertIsNone(idle_seconds())
        with patch('h3queue.schedule.subprocess.check_output',return_value='"HIDIdleTime" = 610000000000'):
            self.assertEqual(idle_seconds(),610)
    def test_migration_preserves_pause_and_existing_settings(self):
        with db() as c:
            setv(c,'idle_minutes',25);c.execute("DELETE FROM settings WHERE key='smart_idle_minutes'");c.execute('PRAGMA user_version=2')
        with db() as c:
            self.assertEqual(get(c,'smart_idle_minutes'),10);self.assertEqual(get(c,'idle_minutes'),25);self.assertEqual(get(c,'mode'),'paused')
    def test_config_only_does_not_enable_or_start_worker(self):
        with patch('h3queue.cli.ensure_worker') as ensure,contextlib.redirect_stdout(io.StringIO()):main(['smart-config','--idle-minutes','15'])
        ensure.assert_not_called()
        with db() as c:self.assertEqual(get(c,'mode'),'paused');self.assertEqual(get(c,'smart_idle_minutes'),15)
        for value in ['0','241']:
            with self.assertRaises(ValueError):main(['smart-config','--idle-minutes',value])
        with db() as c:self.assertEqual(get(c,'smart_idle_minutes'),15)
    @patch('h3queue.schedule.platform.system',return_value='Darwin')
    def test_explicit_mode_switch_and_stop_override_smart(self, _platform):
        with patch('h3queue.cli.ensure_worker'):
            control('smart');self.assertEqual(json.loads((home()/'runtime.json').read_text())['mode'],'smart')
            control('stop')
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
        with patch('h3queue.schedule.idle_seconds',return_value=0):self.assertIsNone(smart_guard(10))
    def test_status_countdown_and_save_does_not_reset_idle(self):
        with patch('h3queue.cli.idle_seconds',return_value=125):s=snapshot()
        self.assertEqual(s['smart']['remaining_seconds'],475);self.assertEqual(s['settings']['mode'],'paused')
    def test_worker_starts_when_idle_stops_on_input_and_requeues(self):
        jid=self.add();fake=Mock(pid=999999);fake.poll.return_value=None
        with db() as c:setv(c,'mode','smart')
        try:
            with patch('h3queue.worker.subprocess.Popen',return_value=fake) as launch,patch('h3queue.worker.running_attempt',return_value=True),patch('h3queue.schedule.idle_seconds',return_value=599):
                worker.tick();launch.assert_not_called()
            with patch('h3queue.worker.subprocess.Popen',return_value=fake) as launch,patch('h3queue.schedule.idle_seconds',return_value=600):
                worker.tick();self.assertEqual(launch.call_count,1)
            with db() as c:out=Path(c.execute('SELECT directory FROM attempts').fetchone()[0])
            self.assertEqual(json.loads((out/'request.json').read_text())['smart_idle_minutes'],10)
            with patch('h3queue.worker.running_attempt',return_value=True),patch('h3queue.schedule.idle_seconds',return_value=0):worker.tick()
            self.assertTrue((out/'STOP').exists());self.assertTrue((out/'activity-stop.json').exists())
            atomic_json(out/'receipt.json',{'code':130})
            with patch('h3queue.schedule.idle_seconds',return_value=0):worker.tick()
            self.assertEqual(self.status(jid)['status'],'queued')
            with db() as c:self.assertEqual(get(c,'mode'),'smart')
            with patch('h3queue.worker.subprocess.Popen',return_value=fake) as launch,patch('h3queue.schedule.idle_seconds',return_value=599):
                worker.tick();launch.assert_not_called()
            with patch('h3queue.worker.subprocess.Popen',return_value=fake),patch('h3queue.schedule.idle_seconds',return_value=600):worker.tick()
            with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM attempts').fetchone()[0],2)
        finally:worker.CHILDREN.clear()
    def test_guard_stops_without_worker_poll_and_preserves_smart_mode(self):
        out=self.root/'smart-render';out.mkdir();runtime_state('smart',10)
        with db() as c:policy=get(c,'safety')
        calls=[0]
        def idle():calls[0]+=1;return 600 if calls[0]<=2 else 0
        with patch('h3queue.schedule.idle_seconds',side_effect=idle):
            r=run([sys.executable,'-c','import time;time.sleep(60)'],self.root,out,'render',policy,smart_idle_minutes=10)
        self.assertTrue((out/'activity-stop.json').exists());self.assertFalse((out/'guard-trip.json').exists());self.assertIsNotNone(r['aborted'])
        self.assertLess(r['elapsed_s'],6)
    def test_stale_controller_and_missing_idle_block_smart(self):
        atomic_json(home()/'runtime.json',{'mode':'smart','smart_idle_minutes':10,'time':time.time()-30})
        self.assertIn('失联',smart_guard(10));self.assertIn('失联',smart_guard())
        runtime_state('smart',10)
        with patch('h3queue.schedule.idle_seconds',return_value=None):self.assertIn('无法读取',smart_guard(10))
    def test_smart_still_obeys_thermal_stop(self):
        jid=self.add()
        with db() as c:setv(c,'mode','smart')
        with patch('h3queue.schedule.idle_seconds',return_value=600),patch('h3queue.worker.blocked',return_value='温度达到停止阈值'),patch('h3queue.worker.subprocess.Popen') as launch:
            worker.tick();launch.assert_not_called()
        with db() as c:self.assertEqual(get(c,'mode'),'paused');self.assertIsNotNone(get(c,'safety_latch'))
        self.assertEqual(self.status(jid)['status'],'queued')

if __name__=='__main__':unittest.main()
