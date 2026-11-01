import fcntl,json,os,signal,subprocess,sys,time,uuid
from pathlib import Path
from .store import db,get,setv,event,home,ROOT,atomic_json,digest
from .schedule import allowed,within,smart_state,runtime_state,activity_stop
from .estimate import machine,metric_identity
from .providers import provider_id
from .safety import blocked,sample_from
from .telemetry import Sampler


CHILDREN=[]
SAMPLE_NOT_BEFORE=0

def running_attempt(directory):
    # Recover supervision after worker restart; the unique absolute request path is the identity.
    token=str(Path(directory)/'request.json')
    try:
        rows=subprocess.check_output(['ps','-axo','pid=,command='],text=True,timeout=3).splitlines()
        return any(token in line and any(x in line for x in ('h3queue.supervisor','h3queue.executor','h3queue.resource_session','agent_session.py')) for line in rows)
    except (OSError,subprocess.SubprocessError):return True  # fail closed

def settle(c,row):
    d=Path(row['directory']);receipt=d/'receipt.json'
    if not receipt.exists() and running_attempt(d):return False
    trip=d/'guard-trip.json'
    if trip.exists():
        setv(c,'mode','paused');setv(c,'safety_latch',json.loads(trip.read_text()))
    result=json.loads(receipt.read_text()) if receipt.exists() else {'code':1,'error':'监督进程退出，未取得完成凭据'}
    verified=d/'verified.json';stopped=(d/'STOP').exists();j=c.execute('SELECT * FROM jobs WHERE id=?',(row['job_id'],)).fetchone()
    status='queued' if stopped else 'failed';err='用户或调度规则停止，当前段需重新生成' if stopped else result.get('error',f'进程退出码 {result["code"]}，查看日志')
    if not stopped and result['code']!=0 and (d/'error.json').exists():
        detail=json.loads((d/'error.json').read_text());err=detail.get('error',err)
        if detail.get('error_kind')=='deployment_changed':
            setv(c,'mode','paused');event(c,'deployment_blocked',j['id'],reason=err)
    if stopped and (d/'activity-stop.json').exists():err=json.loads((d/'activity-stop.json').read_text())['reason']+'；当前段需重新生成'
    if j['status']=='cancel_requested':status='cancelled'
    if trip.exists():status='failed';err=json.loads(trip.read_text()).get('reason','保护停止')
    if result['code']==0 and verified.exists():
        v=json.loads(verified.read_text())
        if Path(v['output']).is_file() and digest(v['output'])==v['sha']:
            status='completed';err=None;s=json.loads(j['spec'])
            c.execute('UPDATE jobs SET output=?,output_sha=? WHERE id=?',(v['output'],v['sha'],j['id']))
            c.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?)',(j['fingerprint'],v['output'],v['sha'],time.time()))
            if provider_id(s)=='h3':
                if v.get('chip_power_mean_w') is not None:
                    c.execute('INSERT OR REPLACE INTO energy_metrics VALUES(?,?,?,?)',(str(d),s['profile'],machine(),v['chip_power_mean_w']))
                c.execute('INSERT OR REPLACE INTO benchmarks VALUES(?,?,?,?,?,?,?,?)',(str(d),s['profile'],s['width'],s['height'],s['frames'],v['elapsed'],machine(),time.time()))
            else:
                key,units=metric_identity(s)
                c.execute('INSERT OR REPLACE INTO provider_metrics VALUES(?,?,?,?,?,?,?,?)',
                          (str(d),provider_id(s),key,units,v['elapsed'],machine(),v.get('chip_power_mean_w'),time.time()))
    c.execute('UPDATE jobs SET status=?,error=?,updated=? WHERE id=?',(status,err,time.time(),j['id']))
    c.execute('UPDATE attempts SET status=?,finished=?,elapsed=?,error=? WHERE id=?',
              ('interrupted' if stopped else status,time.time(),time.time()-row['started'],err,row['id']))
    event(c,'attempt_finished',j['id'],status=status,directory=str(d))
    return True

def tick():
    CHILDREN[:]=[p for p in CHILDREN if p.poll() is None]
    request=None
    with db() as c:
        c.execute('BEGIN IMMEDIATE');setv(c,'worker_heartbeat',time.time())
        active=c.execute("SELECT * FROM attempts WHERE status='running' ORDER BY started LIMIT 1").fetchone()
        sample=sample_from(home()/'telemetry.json');policy=get(c,'safety')
        alert=get(c,'thermal_alert');mode=get(c,'mode');smart_minutes=get(c,'smart_idle_minutes')
        runtime_state(mode,smart_minutes)
        if active:
            # The independent executor repeats these checks if worker dies or DB is busy.
            reason=blocked(policy,sample,home())
            if reason=='温度达到停止阈值' and alert.get('level')!='critical':reason=None
            if reason:
                (Path(active['directory'])/'STOP').touch();setv(c,'mode','paused');setv(c,'safety_latch',{'reason':reason,'time':time.time()})
            if get(c,'mode')=='auto' and get(c,'stop_at_end') and not within(get(c,'window')):
                (Path(active['directory'])/'STOP').touch();setv(c,'reason','时段结束，正在释放算力')
            if get(c,'mode')=='smart':
                state=smart_state(smart_minutes)
                if not state['ready']:
                    activity_stop(Path(active['directory']),'检测到键鼠操作，重新等待空闲' if state['idle_seconds'] is not None else state['reason'])
                    setv(c,'reason','检测到操作，正在停止当前段')
            settle(c,active);return
        ok,reason=allowed(get(c,'mode'),get(c,'window'),get(c,'require_idle'),smart_minutes if mode=='smart' else get(c,'idle_minutes'))
        setv(c,'reason',reason)
        if not ok:return
        if policy['require_telemetry'] and sample.get('time',0)<SAMPLE_NOT_BEFORE:
            setv(c,'reason','等待监测首次采样');return
        reason=blocked(policy,sample,home())
        if reason:
            setv(c,'mode','paused');setv(c,'safety_latch',{'reason':reason,'time':time.time()});event(c,'safety_blocked',reason=reason);return
        job=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC,created,id LIMIT 1").fetchone()
        if not job:
            setv(c,'reason','队列为空' if get(c,'mode')=='manual' else '等待新任务');return
        aid=uuid.uuid4().hex;directory=home()/'runs'/job['id']/aid;directory.mkdir(parents=True)
        request=directory/'request.json';atomic_json(request,{'job_id':job['id'],'attempt_id':aid,'spec':json.loads(job['spec']),'safety':policy,'smart_idle_minutes':smart_minutes if mode=='smart' else None})
        c.execute('INSERT INTO attempts(id,job_id,started,status,directory) VALUES(?,?,?,?,?)',(aid,job['id'],time.time(),'running',str(directory)))
        c.execute("UPDATE jobs SET status='running',attempt_id=?,updated=?,error=NULL WHERE id=?",(aid,time.time(),job['id']))
        event(c,'attempt_started',job['id'],attempt_id=aid)
    if request:
        with (request.parent/'supervisor.log').open('ab') as log:
            python=sys.executable
            proc=subprocess.Popen([python,'-m','h3queue.supervisor',str(request)],cwd=ROOT,stdin=subprocess.DEVNULL,
                                  stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        CHILDREN.append(proc)
        with db() as c:c.execute('UPDATE attempts SET pid=? WHERE id=?',(proc.pid,aid))

def main():
    global SAMPLE_NOT_BEFORE
    home().mkdir(parents=True,exist_ok=True)
    with (home()/'worker.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        atomic_json(home()/'worker.json',{'pid':os.getpid(),'started':time.time()})
        import threading
        stopping=threading.Event()
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stopping.set())
        with db() as c:deployment=get(c,'deployment')
        SAMPLE_NOT_BEFORE=time.time()
        sampler=Sampler(deployment);sampler.start();last_error=None
        try:
            while not stopping.is_set():
                try:tick();last_error=None
                except Exception as e:
                    # STOP files still work if SQLite is full or locked.
                    for request in (home()/'runs').glob('*/*/request.json'):
                        if not (request.parent/'receipt.json').exists():
                            try:(request.parent/'STOP').touch()
                            except OSError:pass
                    try:
                        with db() as c:
                            setv(c,'mode','paused');setv(c,'reason',str(e))
                            if str(e)!=last_error:event(c,'worker_error',error=str(e))
                    except Exception:pass
                    if str(e)!=last_error:print('Worker error:',e,flush=True)
                    last_error=str(e)
                stopping.wait(5 if last_error else 2)
        finally:sampler.close()

if __name__=='__main__':main()
