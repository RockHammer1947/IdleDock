"""PID birth-time checks prevent stale PID or process-group collateral damage."""
import json,os,signal,time
from pathlib import Path
from .store import atomic_json

def members(pgid):
    import psutil
    result=[]
    for p in psutil.process_iter(['pid']):
        try:
            if os.getpgid(p.pid)==pgid:result.append({'pid':p.pid,'born':p.create_time()})
        except (ProcessLookupError,PermissionError,psutil.Error):pass
    return result

def matches(item):
    import psutil
    try:return abs(psutil.Process(item['pid']).create_time()-item['born'])<.001 and psutil.Process(item['pid']).status()!=psutil.STATUS_ZOMBIE
    except (psutil.Error,KeyError,TypeError):return False

def signal_owned(record,sig):
    pgid=record['pgid']
    # Require a surviving, previously recorded member of the same group before signaling.
    if not any(matches(p) and _group(p['pid'])==pgid for p in record.get('members',[])):return False
    try:os.killpg(pgid,sig);return True
    except ProcessLookupError:return False

def _group(pid):
    try:return os.getpgid(pid)
    except ProcessLookupError:return None

def cleanup(registry,grace=3):
    try:record=json.loads(Path(registry).read_text())
    except (OSError,ValueError):return
    if not signal_owned(record,signal.SIGTERM):return
    until=time.monotonic()+grace
    while time.monotonic()<until:
        if not any(matches(m) for m in record['members']):return
        time.sleep(.1)
    signal_owned(record,signal.SIGKILL)
    until=time.monotonic()+2
    while time.monotonic()<until:
        if not any(matches(m) for m in record['members']):return
        time.sleep(.05)
    out=Path(registry).parent
    atomic_json(out/'guard-trip.json',{'reason':'子进程无法停止，需检查机器进程','time':time.time()})
    (out/'STOP').touch()
    raise RuntimeError('Owned child still alive after SIGKILL')
