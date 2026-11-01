"""Explicit, audited retry preparation; never silently accepts new input/model bytes."""
import json, shutil, time
from pathlib import Path
from .store import digest, event, atomic_json
from .jobs import normalize, fingerprint
from .integrity import validate_inputs, validate_spec


def recipe(spec):
    return {k:v for k,v in spec.items() if k not in ('deployment_pins', 'reuse_render')}


def prepare_retry(c, row, refresh_deployment=False, reuse_render=False):
    if row['status'] not in ('failed', 'cancelled'):
        raise ValueError('Only failed/cancelled jobs can retry')
    old=json.loads(row['spec']);validate_inputs(old)
    spec=normalize(old, old['deployment']) if refresh_deployment else dict(old)
    spec.pop('reuse_render', None)
    validate_spec(spec)
    if recipe(spec) != recipe(old):
        raise ValueError('Render parameters changed; enqueue a new request instead')
    key=fingerprint(spec)
    duplicate=c.execute('SELECT id FROM jobs WHERE fingerprint=? AND id!=?', (key,row['id'])).fetchone()
    if duplicate:raise ValueError('Equivalent request already exists: '+duplicate['id'])
    if reuse_render:
        if old.get('provider','h3')!='h3':raise ValueError('--reuse-render is only supported by H3')
        attempt=c.execute('SELECT directory FROM attempts WHERE id=? AND job_id=?', (row['attempt_id'],row['id'])).fetchone()
        if not attempt:raise ValueError('No previous attempt to recover')
        source=Path(attempt['directory'])
        if old.get('reuse_render'):
            # A stopped delivery retry can still refer to the original successful
            # render. Never reuse the interrupted attempt's partial delivery.
            prior=old['reuse_render'];source=Path(prior['directory'])
            if not c.execute('SELECT 1 FROM attempts WHERE job_id=? AND directory=?',(row['id'],str(source))).fetchone():
                raise ValueError('Recovery source does not belong to this job')
            for name,sha in prior['sha256'].items():
                if digest(source/name)!=sha:raise ValueError('Original recovery source changed')
        previous=json.loads((source/'request.json').read_text())
        result=json.loads((source/'render.result.json').read_text())
        if spec['adapter']!='native-audio' or recipe(previous['spec'])!=recipe(spec):
            raise ValueError('Recovery requires the exact same native audio render')
        if result['exit_code']!=0 or result.get('aborted') or (source/'STOP').exists() or (source/'guard-trip.json').exists():
            raise ValueError('Interrupted or failed renders cannot be reused')
        if 'audio-drive invariant PASS' not in (source/'render.log').read_text():
            raise ValueError('Audio-drive invariant missing from source')
        names=('request.json','video.mp4','render.log','render.result.json')
        spec['reuse_render']={'directory':str(source),'sha256':{name:digest(source/name) for name in names}}
    # Execution-only reuse provenance does not alter the content fingerprint.
    c.execute("UPDATE jobs SET spec=?,fingerprint=?,status='queued',error=NULL,updated=? WHERE id=?",
              (json.dumps(spec),key,time.time(),row['id']))
    event(c,'retry_prepared',row['id'],refresh_deployment=refresh_deployment,reuse_render=reuse_render,
          old_fingerprint=row['fingerprint'],fingerprint=key,old_pins=old['deployment_pins'],pins=spec['deployment_pins'])


def reuse_raw(spec,out):
    reuse=spec['reuse_render'];source=Path(reuse['directory'])
    if set(reuse['sha256'])!={'request.json','video.mp4','render.log','render.result.json'}:
        raise ValueError('Incomplete recovery provenance')
    for name,sha in reuse['sha256'].items():
        if name not in ('request.json','video.mp4','render.log','render.result.json') or digest(source/name)!=sha:
            raise ValueError('Recovery source changed: '+name)
    previous=json.loads((source/'request.json').read_text())
    result=json.loads((source/'render.result.json').read_text())
    if recipe(previous['spec'])!=recipe(spec) or result['exit_code']!=0 or result.get('aborted'):
        raise ValueError('Invalid render recovery provenance')
    for name in ('video.mp4','render.log','render.result.json'):
        shutil.copy2(source/name,out/name)
        if digest(out/name)!=reuse['sha256'][name]:raise ValueError('Recovery copy mismatch')
    atomic_json(out/'reused-render.json',reuse)
    return result
