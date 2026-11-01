import json, math, time, uuid, wave
from pathlib import Path
from .store import digest,event,home
from .estimate import estimate,machine

def normalize(raw,deployment):
    from .providers import resolve
    if not isinstance(raw,dict):raise ValueError('Request must be a JSON object')
    if raw.get('schema_version',1)!=1:raise ValueError('Unsupported request schema_version')
    return resolve(raw).normalize(raw,deployment)

def fingerprint(spec):
    import hashlib
    return hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def enqueue(c,raw,title,priority=0):
    from .store import get
    spec=normalize(raw,get(c,'deployment'));key=fingerprint(spec)
    if len(title)>240:raise ValueError('Title exceeds 240 characters')
    if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
    old=c.execute('SELECT * FROM jobs WHERE fingerprint=?',(key,)).fetchone()
    if old:
        status=old['status']
        if status=='completed' and (not old['output'] or not Path(old['output']).is_file() or digest(old['output'])!=old['output_sha']):
            status='failed'
            c.execute("UPDATE jobs SET status='failed',error='缓存文件缺失或校验不匹配',updated=? WHERE id=?",(time.time(),old['id']))
            c.execute('DELETE FROM cache WHERE fingerprint=?',(key,))
            event(c,'cache_invalidated',old['id'])
        return {'id':old['id'],'reused_request':True,'status':status}
    cache=c.execute('SELECT * FROM cache WHERE fingerprint=?',(key,)).fetchone()
    valid=cache and Path(cache['output']).is_file() and digest(cache['output'])==cache['sha']
    jid=uuid.uuid4().hex[:12];now=time.time();status='completed' if valid else 'queued'
    c.execute('INSERT INTO jobs(id,fingerprint,title,spec,status,priority,created,updated,output,output_sha) VALUES(?,?,?,?,?,?,?,?,?,?)',
              (jid,key,title,json.dumps(spec),status,int(priority),now,now,cache['output'] if valid else None,cache['sha'] if valid else None))
    event(c,'enqueued',jid,cache_hit=bool(valid))
    return {'id':jid,'status':status,'estimate':estimate(c,spec)}


def enqueue_batch(c,raw,priority=0):
    """All-or-nothing import; each paragraph is an independently retryable job."""
    if not isinstance(raw,dict) or raw.get('schema_version')!=1:raise ValueError('Batch requires schema_version: 1')
    items=raw.get('jobs')
    if not isinstance(items,list) or not 1<=len(items)<=500:raise ValueError('Batch requires 1–500 jobs')
    defaults=raw.get('defaults',{})
    if not isinstance(defaults,dict):raise ValueError('Batch defaults must be an object')
    if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
    c.execute('SAVEPOINT batch_import')
    try:
        results=[]
        for index,item in enumerate(items,1):
            if not isinstance(item,dict) or not isinstance(item.get('request'),dict):raise ValueError('Each batch job requires a request object')
            results.append(enqueue(c,{**defaults,**item['request']},item.get('title',f'批量任务 · {index:03}'),item.get('priority',priority)))
        c.execute('RELEASE batch_import')
    except BaseException:
        c.execute('ROLLBACK TO batch_import');c.execute('RELEASE batch_import');raise
    return {'imported':len(results),'jobs':results,'note':'沿用当前运行模式；导入不启用运行'}

def import_avatar(c,folder):
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text());parent=folder.parent;records=[]
    for j in plan['jobs']:
        if 'reuse' in j:
            command=json.loads((parent/'sample-v1/command.json').read_text())
            audio=command[command.index('--audio-drive')+1]
            raw=dict(profile='native20',adapter='native-audio',width=1280,height=736,frames=209,seed=42,
                     prompt=command[command.index('-p')+1],engine=str(parent/'engine/h3'),portrait=plan['portrait'],audio=audio,
                     trim_s=0,delivery_frames=j['frames'],delivery_height=720)
            video=Path(j['reuse']);metric=parent/'sample-v1/video.result.json'
        else:
            raw=dict(profile='native20',adapter='native-audio',width=1280,height=736,frames=j['native_frames'],seed=42,
                     prompt=j['prompt'],engine=str(parent/'engine/h3'),portrait=plan['portrait'],audio=j['drive'],
                     trim_s=j['trim_s'],delivery_frames=j['frames'],delivery_height=720)
            video=folder/j['id']/'preview-720p.mp4';metric=folder/j['id']/'video.result.json'
        result=enqueue(c,raw,f'{folder.name} · {j["id"]} · {j["start_frame"]/30:.2f}s');jid=result['id']
        approved='reuse' in j
        complete=approved or (folder/j['id']/'complete.json').exists()
        if complete and video.is_file():
            sha=digest(video);key=c.execute('SELECT fingerprint FROM jobs WHERE id=?',(jid,)).fetchone()[0]
            if not approved:
                expected=json.loads((folder/j['id']/'complete.json').read_text())['sha256']
                if sha!=expected:raise ValueError('Imported output hash mismatch')
            c.execute('UPDATE jobs SET status=?,output=?,output_sha=?,updated=? WHERE id=?',('completed',str(video),sha,time.time(),jid))
            c.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?)',(key,str(video),sha,time.time()))
            if metric.exists():
                m=json.loads(metric.read_text())
                if m['exit_code']==0:
                    if m.get('chip_power_w',{}).get('mean') is not None:
                        c.execute('INSERT OR REPLACE INTO energy_metrics VALUES(?,?,?,?)',(str(metric),'native20',machine(),m['chip_power_w']['mean']))
                    c.execute('INSERT OR IGNORE INTO benchmarks VALUES(?,?,?,?,?,?,?,?)',
                       (str(metric),'native20',1280,736,raw['frames'],m['elapsed_s'],machine(),time.time()))
            event(c,'imported_completed',jid,visual_review='approved' if approved else 'pending')
        result['status']=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()[0]
        records.append(result)
    return {'imported':len(records),'jobs':records}
