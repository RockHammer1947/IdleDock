"""Fail-closed Linux sensors. GPU board power is never labelled as chip power."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time

from .store import atomic_json, db, event, get, home, setv
from .safety import sample_from


def temperature(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 < value < 130 else None
    except (TypeError, ValueError):
        return None


def sysfs_temperatures(root=Path('/sys')):
    """Return maxima and source paths, ignoring disk/ACPI ambient sensors.

    Explicit paths select real millidegree sysfs readings on unusual boards;
    they are never a substitute constant or a way to bypass missing telemetry.
    """
    values = {'cpu': [], 'gpu': []}
    errors = []
    for device in values:
        override = os.environ.get('H3_QUEUE_'+device.upper()+'_TEMP_PATHS')
        if override is not None:
            try:
                paths = json.loads(override)
                if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
                    raise ValueError('expected a nonempty JSON array of sysfs paths')
                for name in paths:
                    path = Path(name)
                    if not path.is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                        raise ValueError('temperature paths must resolve under /sys')
                    value = temperature(float(path.read_text()) / 1000)
                    if value is None:raise ValueError('invalid temperature: '+str(path))
                    values[device].append((value, str(path)))
            except (OSError, ValueError, TypeError) as exc:
                values[device] = []
                errors.append(device+': '+str(exc))
    for directory in sorted((root/'class/hwmon').glob('hwmon*')):
        try:name = (directory/'name').read_text().strip().lower()
        except OSError:continue
        for path in sorted(directory.glob('temp*_input')):
            try:
                label_path = path.with_name(path.name.replace('_input', '_label'))
                label = label_path.read_text().strip().lower() if label_path.exists() else ''
                text = name+' '+label
                devices = []
                if re.search(r'coretemp|k10temp|cpu|package|soc|tj[-_ ]?thermal', text):devices.append('cpu')
                if re.search(r'nvidia|gpu|amdgpu|soc|tj[-_ ]?thermal', text):devices.append('gpu')
                value = temperature(float(path.read_text()) / 1000)
                for device in devices:
                    if value is not None and 'H3_QUEUE_'+device.upper()+'_TEMP_PATHS' not in os.environ:
                        values[device].append((value, str(path)))
            except (OSError, ValueError):continue
    for directory in sorted((root/'class/thermal').glob('thermal_zone*')):
        try:
            name = (directory/'type').read_text().strip().lower()
            path = directory/'temp';value = temperature(float(path.read_text())/1000)
            for device, pattern in (('cpu', r'cpu|soc|tj[-_ ]?thermal'), ('gpu', r'gpu|soc|tj[-_ ]?thermal')):
                if value is not None and re.search(pattern, name) and 'H3_QUEUE_'+device.upper()+'_TEMP_PATHS' not in os.environ:
                    values[device].append((value, str(path)))
        except (OSError, ValueError):continue
    return values, errors


def read_sample(root=Path('/sys')):
    import psutil
    values, errors = sysfs_temperatures(root)
    gpu_percent = None
    # Explicit GPU sysfs mapping takes precedence; nvidia-smi is the default
    # discrete/GB10 GPU temperature source when the driver exposes that field.
    binary = os.environ.get('H3_QUEUE_NVIDIA_SMI') or shutil.which('nvidia-smi')
    if binary:
        try:
            result = subprocess.run([binary, '--query-gpu=temperature.gpu,utilization.gpu', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=4, check=True)
            rows = [line.split(',') for line in result.stdout.strip().splitlines()]
            temps = [temperature(row[0].strip()) for row in rows if len(row)==2]
            if not rows or len(temps)!=len(rows) or any(t is None for t in temps):
                raise ValueError('NVIDIA temperature unavailable for one or more GPUs')
            if 'H3_QUEUE_GPU_TEMP_PATHS' not in os.environ:
                values['gpu'].extend((t, 'nvidia-smi') for t in temps)
            try:
                utilization = [float(row[1].strip()) for row in rows]
                if all(math.isfinite(v) and 0<=v<=100 for v in utilization):gpu_percent=max(utilization)
            except ValueError:pass  # Some drivers expose temperature but no utilization.
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append('nvidia-smi: '+str(exc))
            # Do not silently protect a subset of GPUs if the driver reports
            # another GPU whose temperature cannot be read.
            if 'H3_QUEUE_GPU_TEMP_PATHS' not in os.environ:values['gpu']=[]
    vm = psutil.virtual_memory()
    for device in values:
        if not values[device]:errors.append(device+' temperature missing; inspect sysfs or configure H3_QUEUE_'+device.upper()+'_TEMP_PATHS')
    return {'time': time.time(), 'cpu_c': max((v for v,_ in values['cpu']), default=None),
            'gpu_c': max((v for v,_ in values['gpu']), default=None), 'chip_w': None,
            'ram_used_gib': vm.used/1024**3, 'ram_total_gib': vm.total/1024**3,
            'gpu_percent': gpu_percent, 'source': 'linux-sysfs+nvidia-smi',
            'temperature_sources': {k:[p for _,p in v] for k,v in values.items()}, 'sensor_errors': errors}


def run_sampler(sampler):
    from .telemetry import prune
    last_level = None
    last_write = 0
    while not sampler.stop_event.is_set():
        try:
            sample = read_sample()
            atomic_json(home()/'telemetry.json', sample)
            valid = sample_from(home()/'telemetry.json')
            with db() as c:
                level = sampler.latch.update(valid, get(c, 'safety'), time.monotonic())
                sample['level'] = level
                if level != last_level:
                    alert = {'sequence':get(c, 'thermal_alert').get('sequence',0)+1,
                             'level':level, 'time':sample['time'], 'cpu_c':sample['cpu_c'], 'gpu_c':sample['gpu_c']}
                    setv(c, 'thermal_alert', alert);event(c, 'thermal_'+level, **alert)
                    last_level = level
                if time.time()-last_write >= 30:
                    c.execute('INSERT INTO telemetry(time,data) VALUES(?,?)', (sample['time'], json.dumps(sample)))
                    prune(c, sample['time']);last_write=time.time()
            atomic_json(home()/'telemetry.json', sample)
        except (OSError, ValueError, TypeError, sqlite3.Error):
            # Previous sample ages out; missing sensors never become zero C.
            pass
        sampler.stop_event.wait(3)
