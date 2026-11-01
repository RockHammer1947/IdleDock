"""Per-attempt durable supervisor; wrapper lifetime includes Qwen restoration."""
import json,os,subprocess,sys,time
from pathlib import Path
from .store import atomic_json,ROOT
from .processes import cleanup,matches
from .integrity import validate_spec,DeploymentChanged
from .providers import provider_id

def main(path):
    path=Path(path);request=json.loads(path.read_text());out=path.parent;s=request['spec'];base=Path(s['deployment'])
    if (out/'STOP').exists():
        atomic_json(out/'receipt.json',{'code':130,'finished':time.time()});return
    # Reject changed dependencies before stopping/restoring Qwen for a doomed task.
    try:validate_spec(s)
    except (ValueError,OSError) as e:
        atomic_json(out/'error.json',{'error':str(e),'error_kind':'deployment_changed'})
        atomic_json(out/'receipt.json',{'code':1,'error':str(e),'error_kind':'deployment_changed','finished':time.time()});return
    if provider_id(s)=='h3':
        cmd=[str(base/'Qwen3.8/.venv/bin/python'),str(base/'agent_session.py'),'h3','--',
             str(base/'H3/minimax-h3-mlx/.venv/bin/python'),'-m','h3queue.executor',str(path)]
    else:
        cmd=[sys.executable,'-m','h3queue.resource_session',str(path)]
    atomic_json(out/'phase.json',{'phase':'waiting_resource','time':time.time()})
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT);env['PYTHONUNBUFFERED']='1'
    with (out/'session.log').open('ab') as log:
        proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        atomic_json(out/'wrapper.json',{'pid':proc.pid,'command':cmd})
        while proc.poll() is None:
            inner=out/'inner.json'
            if inner.exists():
                try:
                    info=json.loads(inner.read_text())
                    if not matches({'pid':info['pid'],'born':info.get('born',0)}):cleanup(out/'owned-group.json')
                except (OSError,ValueError,KeyError,TypeError):
                    (out/'STOP').touch();cleanup(out/'owned-group.json')
            time.sleep(.5)
        cleanup(out/'owned-group.json')
        code=proc.returncode
    atomic_json(out/'receipt.json',{'code':code,'finished':time.time()})

if __name__=='__main__':
    try:main(sys.argv[1])
    except Exception as e:
        atomic_json(Path(sys.argv[1]).parent/'receipt.json',{'code':1,'error':str(e),'finished':time.time()})
        raise
