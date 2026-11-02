"""Linux platform contracts with real-shaped synthetic sysfs, never host stress."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from h3queue.cli import control, main
from h3queue.linux_telemetry import read_sample, sysfs_temperatures
from h3queue.safety import DEFAULTS, blocked, sample_from
from h3queue.store import atomic_json, db, get, home, setv


class LinuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'H3_QUEUE_HOME':str(self.root/'state')},clear=False);self.env.start();home().mkdir(parents=True)
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def sensor(self,group,name,value):
        p=self.root/'class/hwmon'/group;p.mkdir(parents=True)
        (p/'name').write_text(name);(p/'temp1_input').write_text(value)
        return p/'temp1_input'
    def test_real_sensor_values_and_conservative_maximum(self):
        self.sensor('hwmon0','coretemp','52000');self.sensor('hwmon1','cpu_thermal','61000')
        self.sensor('hwmon2','gpu_thermal','70000');self.sensor('hwmon3','nvme','120000')
        with patch('h3queue.linux_telemetry.shutil.which',return_value=None):s=read_sample(self.root)
        self.assertEqual((s['cpu_c'],s['gpu_c']),(61,70));self.assertIsNone(s['chip_w'])
        atomic_json(home()/'telemetry.json',s)
        self.assertNotIn('error',sample_from(home()/'telemetry.json'))
    def test_shared_soc_sensor_is_real_not_synthetic_cpu_fallback(self):
        self.sensor('hwmon0','soc_thermal','62000')
        values,_=sysfs_temperatures(self.root)
        self.assertEqual(values['cpu'][0][0],62);self.assertEqual(values['gpu'][0][0],62)
    def test_missing_or_invalid_sensor_fails_closed(self):
        self.sensor('hwmon0','cpu','nan')
        with patch('h3queue.linux_telemetry.shutil.which',return_value=None):s=read_sample(self.root)
        atomic_json(home()/'telemetry.json',s)
        self.assertIn('error',sample_from(home()/'telemetry.json'))
        self.assertEqual(blocked({**DEFAULTS,'min_disk_gib':2},sample_from(home()/'telemetry.json'),home()),'温度监测失联，暂停计算')
    def test_nvidia_all_devices_required_and_no_fake_energy(self):
        self.sensor('hwmon0','cpu','55000')
        with patch('h3queue.linux_telemetry.shutil.which',return_value='/fake/nvidia-smi'),patch('h3queue.linux_telemetry.subprocess.run',return_value=subprocess.CompletedProcess([],0,'65, 80\n72, 40\n','')):
            s=read_sample(self.root)
        self.assertEqual(s['gpu_c'],72);self.assertEqual(s['gpu_percent'],80);self.assertIsNone(s['chip_w'])
        with patch('h3queue.linux_telemetry.shutil.which',return_value='/fake/nvidia-smi'),patch('h3queue.linux_telemetry.subprocess.run',return_value=subprocess.CompletedProcess([],0,'65, 80\nN/A, N/A\n','')):
            self.assertIsNone(read_sample(self.root)['gpu_c'])
    def test_explicit_sysfs_override_and_invalid_override_no_fallback(self):
        path=self.sensor('hwmon0','unusual-chip','58000')
        with patch.dict(os.environ,{'H3_QUEUE_CPU_TEMP_PATHS':json.dumps([str(path)])}):
            self.assertEqual(sysfs_temperatures(self.root)[0]['cpu'][0][0],58)
        with patch.dict(os.environ,{'H3_QUEUE_CPU_TEMP_PATHS':'["/tmp/not-a-sensor"]'}):
            values,errors=sysfs_temperatures(self.root);self.assertFalse(values['cpu']);self.assertTrue(errors)
    def test_sampler_publishes_and_shuts_down_without_macmon(self):
        from h3queue.telemetry import Sampler
        import time
        self.sensor('hwmon0','cpu','55000');self.sensor('hwmon1','gpu','60000')
        with patch('h3queue.linux_telemetry.shutil.which',return_value=None):sample=read_sample(self.root)
        with patch('h3queue.telemetry.platform.system',return_value='Linux'),patch('h3queue.linux_telemetry.read_sample',return_value=sample):
            sampler=Sampler(self.root);sampler.start()
            try:
                deadline=time.monotonic()+3
                while not (home()/'telemetry.json').exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertEqual(sample_from(home()/'telemetry.json')['gpu_c'],60)
                self.assertIsNone(sampler.proc)
            finally:sampler.close()
            self.assertFalse(sampler.thread.is_alive())
        with db() as c:self.assertEqual(get(c,'mode'),'paused')

    def test_headless_modes_do_not_silently_assume_desktop_idle(self):
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
        with patch('h3queue.cli.platform.system',return_value='Linux'),patch('h3queue.cli.ensure_worker'):
            with self.assertRaisesRegex(ValueError,'macOS-only'):control('smart')
            with self.assertRaisesRegex(ValueError,'no-idle'):control('auto')
            with self.assertRaisesRegex(ValueError,'macOS-only'):main(['launch-agent','install'])
        with db() as c:self.assertEqual(get(c,'mode'),'paused')
    def test_shell_launcher_handles_paths_with_spaces_and_explicit_python(self):
        import sys
        from h3queue.store import ROOT
        with tempfile.TemporaryDirectory(prefix='idledock launch ') as tmp:
            # The checkout launcher remains POSIX and usable without zsh.
            result=subprocess.run(['/bin/sh',str(ROOT/'queue'),'providers'],capture_output=True,text=True,
                                  cwd=tmp,env={**os.environ,'H3_QUEUE_PYTHON':sys.executable})
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['concurrency'],1)


if __name__=='__main__':unittest.main()
