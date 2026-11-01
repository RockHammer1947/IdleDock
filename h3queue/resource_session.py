"""Cancellable cooperative lease for new providers, compatible with agent_session.py.

Uses exactly the existing deployment lock and service helpers. Legacy H3 still
runs through its unmodified wrapper, preserving all queued deployment pins.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .store import atomic_json,home
from .providers import resolve
from .integrity import validate_spec,DeploymentChanged
from .safety import blocked,sample_from,validate
from .schedule import smart_guard,activity_stop


def stop_reason(request,out):
    if (out/'STOP').exists():return '已请求停止'
    activity=smart_guard(request.get('smart_idle_minutes'))
    if activity:
        activity_stop(out,activity);return activity
    policy=request['safety']
    if (home()/'safety.json').exists():policy=validate(json.loads((home()/'safety.json').read_text()))
    reason=blocked(policy,sample_from(home()/'telemetry.json'),out)
    if reason:
        atomic_json(out/'guard-trip.json',{'reason':reason,'time':time.time()});(out/'STOP').touch()
    return reason


def run(path):
    path=Path(path);request=json.loads(path.read_text());out=path.parent;spec=request['spec']
    base=Path(spec['deployment']);device=resolve(spec).resources(spec)['device']
    atomic_json(out/'phase.json',{'phase':'waiting_resource','time':time.time()})
    with (base/'.codex-inference.lock').open('a+') as lease:
        while True:
            if stop_reason(request,out):return 130
            try:
                fcntl.flock(lease.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:time.sleep(.2)
        try:
            # Files may have changed while another model held the lease.
            try:validate_spec(spec)
            except (OSError,ValueError) as exc:raise DeploymentChanged(str(exc)) from exc
            if stop_reason(request,out):return 130
            module_spec=importlib.util.spec_from_file_location('queue_deployment_session',base/'agent_session.py')
            session=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(session)
            before=session.service('status') if device=='gpu' else {'running':False}
            old=before.get('state') or {};restore=bool(before['running'])
            try:
                if restore:
                    atomic_json(out/'phase.json',{'phase':'preparing','time':time.time()})
                    session.service('stop')
                if stop_reason(request,out):return 130
                env=dict(os.environ);env['LOCAL_MODEL_SESSION_TARGET']='h3' if device=='gpu' else 'cpu'
                return subprocess.run([sys.executable,'-m','h3queue.executor',str(path)],env=env).returncode
            finally:
                if restore:
                    atomic_json(out/'phase.json',{'phase':'restoring','time':time.time()})
                    session.service('start',old['profile'],bool(old.get('prefix_cache')))
                    session.ready(old['profile'])
        finally:fcntl.flock(lease.fileno(),fcntl.LOCK_UN)


if __name__=='__main__':
    try:sys.exit(run(sys.argv[1]))
    except Exception as exc:
        from .integrity import DeploymentChanged
        atomic_json(Path(sys.argv[1]).parent/'error.json',{'error':str(exc),'error_kind':'deployment_changed' if isinstance(exc,DeploymentChanged) else 'session'})
        raise
