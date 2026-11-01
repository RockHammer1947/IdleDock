"""Provider-neutral executor. The session owns resources, this process owns children."""
import json
import math
import os
import sys
import time
from pathlib import Path
from .store import atomic_json,digest
from .integrity import validate_spec,DeploymentChanged
from .providers import resolve,provider_id
from .execution import ExecutionContext
# Compatibility for existing H3 callers/tests.
from .h3_executor import normalization_command


def execute(path):
    path=Path(path);request=json.loads(path.read_text());spec=request['spec'];out=path.parent
    provider=resolve(spec);resources=provider.resources(spec)
    expected='h3' if resources['device']=='gpu' else 'cpu'
    if os.environ.get('LOCAL_MODEL_SESSION_TARGET')!=expected:raise RuntimeError('A matching local resource session is required')
    import psutil
    atomic_json(out/'inner.json',{'pid':os.getpid(),'born':psutil.Process().create_time(),'time':time.time()})
    if (out/'STOP').exists():return 130
    validate_spec(spec)
    atomic_json(out/'phase.json',{'phase':'running','provider':provider_id(spec),'time':time.time()})
    context=ExecutionContext(path,request,resources)
    try:artifact=provider.run(context)
    except InterruptedError:return 130
    if (out/'STOP').exists():return 130
    output=Path(artifact['output']).resolve()
    if not output.is_relative_to(out.resolve()) or not output.is_file() or digest(output)!=artifact['sha']:
        raise ValueError('Provider returned an invalid artifact')
    elapsed=artifact['elapsed']
    if not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0:raise ValueError('Invalid provider elapsed time')
    artifact.update(provider=provider_id(spec),output_kind=provider.describe(spec)['output_kind'])
    atomic_json(out/'verified.json',artifact)
    atomic_json(out/'phase.json',{'phase':'restoring','provider':provider_id(spec),'time':time.time()})
    return 0


if __name__=='__main__':
    try:sys.exit(execute(sys.argv[1]))
    except Exception as e:
        atomic_json(Path(sys.argv[1]).parent/'error.json',{'error':str(e),'error_kind':'deployment_changed' if isinstance(e,DeploymentChanged) else 'execution'})
        raise
