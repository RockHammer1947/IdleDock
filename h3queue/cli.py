import argparse,json,os,subprocess,sys,time,plistlib
from pathlib import Path
from .store import db,get,setv,event,home,ROOT,digest,atomic_json
from .jobs import enqueue,import_avatar
from .estimate import estimate,machine
from .safety import validate,sample_from,blocked
from .schedule import minutes,allowed,idle_seconds,smart_state,runtime_state

def ensure_worker():
    home().mkdir(parents=True,exist_ok=True)
    with db() as c:
        if time.time()-get(c,'worker_heartbeat')<8:return
    with (home()/'worker.log').open('ab') as log:
        subprocess.Popen([sys.executable,'-m','h3queue.worker'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)

def control(action):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if action in ('start','auto','smart'):
            problem=blocked(get(c,'safety'),sample_from(home()/'telemetry.json'),home())
            if problem:raise ValueError(problem)
            setv(c,'safety_latch',None)
        mode={'start':'manual','auto':'auto','smart':'smart','pause':'paused','stop':'paused'}[action];setv(c,'mode',mode)
        if action=='stop':
            for row in c.execute("SELECT directory FROM attempts WHERE status='running'"):(Path(row[0])/'STOP').touch()
        runtime_state(mode,get(c,'smart_idle_minutes'))
        event(c,'control',action=action)
    ensure_worker()
    return {'mode':mode,'action':action}

def snapshot():
    with db() as c:
        settings={r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}
        from .providers import resolve,provider_id
        from .estimate import metric_identity
        benches={};generic={};powers={}
        for r in c.execute('SELECT * FROM benchmarks WHERE machine=?',(machine(),)):benches.setdefault(r['profile'],[]).append(r)
        for r in c.execute('SELECT * FROM provider_metrics WHERE machine=?',(machine(),)):generic.setdefault((r['provider'],r['metric_key']),[]).append(r)
        for r in c.execute('SELECT profile,AVG(chip_w) w FROM energy_metrics WHERE machine=? GROUP BY profile',(machine(),)):powers[('h3',r['profile'])]=r['w']
        for key,rows in generic.items():
            values=[r['chip_w'] for r in rows if r['chip_w'] is not None]
            if values:powers[key]=sum(values)/len(values)
        cache={}
        def est(s):
            name=provider_id(s);key,units=metric_identity(s)
            identity=(name,key,units,s.get('width'),s.get('height'),s.get('frames'))
            if identity not in cache:cache[identity]=estimate(c,s,benches.get(key,[]) if name=='h3' else generic.get((name,key),[]))
            return cache[identity]
        def elapsed_for(row):
            if not row['started'] or row['status'] not in ('running','cancel_requested'):return 0
            try:
                phase=json.loads((Path(row['directory'])/'phase.json').read_text())
                return max(0,time.time()-phase['time']) if phase['phase']=='running' else 0
            except (OSError,ValueError,KeyError,TypeError):return max(0,time.time()-row['started'])
        counts={k:0 for k in ['queued','running','completed','failed','cancelled','cancel_requested']}
        counts.update({r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM jobs GROUP BY status')})
        total=low=high=energy=0;unknown=energy_unknown=0
        for r in c.execute("SELECT j.spec,j.status,a.started,a.directory FROM jobs j LEFT JOIN attempts a ON j.attempt_id=a.id WHERE j.status IN ('queued','running','cancel_requested')"):
            spec=json.loads(r['spec']);e=est(spec)
            elapsed=elapsed_for(r)
            if e['seconds'] is None:unknown+=1;energy_unknown+=1;continue
            seconds=max(0,e['seconds']-elapsed);total+=seconds
            low+=max(0,e['low']-elapsed);high+=max(0,e['high']-elapsed)
            power=powers.get((provider_id(spec),metric_identity(spec)[0]))
            if power is None:energy_unknown+=1
            else:energy+=(power*settings['safety']['wall_multiplier']+settings['safety']['wall_overhead_w'])*seconds/3600000
        jobs=[];active=None
        query="SELECT j.id,title,j.status,output,j.error,j.spec,a.started,a.directory FROM jobs j LEFT JOIN attempts a ON j.attempt_id=a.id ORDER BY CASE WHEN j.status IN ('running','cancel_requested') THEN 0 WHEN j.status='queued' THEN 1 ELSE 2 END,priority DESC,created,j.id LIMIT 200"
        for r in c.execute(query):
            j=dict(r);spec=json.loads(j.pop('spec'));j.update(resolve(spec).describe(spec))
            j.update(estimate=est(spec),progress=None,log=None,phase=None)
            if j['directory']:j['log']=str(Path(j['directory'])/'session.log')
            if j['status'] in ('running','cancel_requested'):
                directory=Path(j['directory']);j['stop_requested']=(directory/'STOP').exists()
                j['elapsed']=elapsed_for(r);active=j
                try:j['phase']=json.loads((directory/'phase.json').read_text())['phase']
                except (OSError,ValueError,KeyError):pass
                log=directory/'render.log'
                if provider_id(spec)=='h3' and log.exists():
                    import re
                    with log.open('rb') as f:f.seek(max(0,log.stat().st_size-10000));tail=f.read().decode(errors='replace')
                    match=re.findall(r'(?:denois\w*|step)\s*[: ]?\s*(\d+)\s*/\s*(\d+)',tail,re.I)
                    if match and int(match[-1][1])>0:j['progress']=min(1,int(match[-1][0])/int(match[-1][1]))
            jobs.append(j)
        idle=idle_seconds();smart=smart_state(settings['smart_idle_minutes'],idle)
        limit=settings['smart_idle_minutes'] if settings['mode']=='smart' else settings['idle_minutes']
        _,reason=allowed(settings['mode'],settings['window'],settings['require_idle'],limit,idle)
        if active and settings['mode']=='smart':
            reason='智能生成中 · 操作电脑后停止' if not (Path(active['directory'])/'activity-stop.json').exists() else '检测到操作，正在停止当前段'
        if settings['safety_latch']:reason=settings['safety_latch']['reason']+' · 需手动恢复'
        t=sample_from(home()/'telemetry.json');t['stale']=t['age_seconds']>settings['safety']['stale_seconds']
        return {'settings':settings,'counts':counts,'total_jobs':sum(counts.values()),'jobs':jobs,'active':active,
                'estimate_seconds':round(total),'estimate_low':round(low),'estimate_high':round(high),'unknown_estimates':unknown,
                'energy_remaining_kwh':energy if not energy_unknown else None,'energy_unknown_jobs':energy_unknown,
                'energy_cost_estimate':energy*settings['safety']['price_per_kwh'] if not energy_unknown else None,'telemetry':t,'smart':smart,
                'reason':reason,'worker_alive':time.time()-settings['worker_heartbeat']<8,'database':str(home()/'queue.sqlite3')}

def main(argv=None):
    p=argparse.ArgumentParser(description='Local compute queue. JSON output; enqueue/register never enable execution.')
    sub=p.add_subparsers(dest='command',required=True)
    for n in ('status','start','pause','stop','auto','smart','init','worker','doctor','calibrate-energy','providers'):sub.add_parser(n)
    a=sub.add_parser('register-provider');a.add_argument('file');a.add_argument('--replace',action='store_true')
    a=sub.add_parser('enqueue-batch');a.add_argument('file');a.add_argument('--priority',type=int,default=0)
    a=sub.add_parser('smart-config');a.add_argument('--idle-minutes',type=int,required=True)
    a=sub.add_parser('safety');a.add_argument('--set',action='append',default=[],metavar='KEY=JSON_VALUE')
    a=sub.add_parser('enqueue');a.add_argument('file');a.add_argument('--title',default='本地任务');a.add_argument('--priority',type=int,default=0)
    a=sub.add_parser('import-avatar');a.add_argument('folder')
    a=sub.add_parser('schedule');a.add_argument('--start',required=True);a.add_argument('--end',required=True);a.add_argument('--timezone',default='Asia/Shanghai');a.add_argument('--idle-minutes',type=int,default=10);a.add_argument('--no-idle',action='store_true');a.add_argument('--finish-current',action='store_true')
    for n in ('retry','cancel','prioritize','reveal','delete'):
        a=sub.add_parser(n);a.add_argument('id')
        if n=='retry':
            a.add_argument('--refresh-deployment',action='store_true',help='Accept reviewed deployment pins; input/model hashes must remain unchanged')
            a.add_argument('--reuse-render',action='store_true',help='Recover a successful raw native render and redo delivery only')
    a=sub.add_parser('configure');a.add_argument('--deployment',required=True)
    a=sub.add_parser('launch-agent');a.add_argument('action',choices=['install','remove'])
    args=p.parse_args(argv);cmd=args.command
    if cmd in ('start','pause','stop','auto','smart'):result=control(cmd)
    elif cmd=='status':result=snapshot()
    elif cmd=='providers':
        from .providers import catalog
        with db() as c:result={'providers':catalog(get(c,'deployment')),'concurrency':1,'policy':'serial_nonpreemptive'}
    elif cmd=='register-provider':
        from .providers.command import register
        result=register(args.file,args.replace)
    elif cmd=='enqueue-batch':
        if Path(args.file).stat().st_size>4*1024**2:raise ValueError('Batch JSON exceeds 4 MiB')
        from .jobs import enqueue_batch
        with db() as c:result=enqueue_batch(c,json.loads(Path(args.file).read_text()),args.priority)
        ensure_worker()
    elif cmd=='smart-config':
        if not 1<=args.idle_minutes<=240:raise ValueError('智能模式空闲等待须为 1–240 分钟')
        with db() as c:
            setv(c,'smart_idle_minutes',args.idle_minutes);runtime_state(get(c,'mode'),args.idle_minutes);event(c,'smart_configured',idle_minutes=args.idle_minutes)
        result={'saved':True,'smart_idle_minutes':args.idle_minutes,'note':'保存不启用；smart 才开启智能模式'}
    elif cmd=='safety':
        with db() as c:
            policy=get(c,'safety')
            for change in args.set:
                key,value=change.split('=',1)
                if key not in policy:raise ValueError('Unknown policy key: '+key)
                policy[key]=json.loads(value)
            policy=validate(policy);setv(c,'safety',policy);event(c,'safety_configured')
            atomic_json(home()/'safety.json',policy)
        result=policy
    elif cmd=='calibrate-energy':
        import math
        imported=0
        with db() as c:
            for r in c.execute('SELECT source,profile,machine FROM benchmarks').fetchall():
                try:
                    source=Path(r['source']);m=json.loads(source.read_text()) if source.is_file() else json.loads((source/'render.result.json').read_text())
                    power=m.get('chip_power_mean_w',m.get('chip_power_w',{}).get('mean'))
                    if m.get('exit_code')==0 and isinstance(power,(int,float)) and math.isfinite(power) and 0<power<2000:
                        c.execute('INSERT OR REPLACE INTO energy_metrics VALUES(?,?,?,?)',(r['source'],r['profile'],r['machine'],power));imported+=1
                except (OSError,ValueError,TypeError):continue
        result={'imported_power_samples':imported,'note':'Reads successful local benchmarks only; no generation'}
    elif cmd=='init':
        with db() as c:mode=get(c,'mode')
        ensure_worker();result={'home':str(home()),'status':'initialized','mode':mode}
    elif cmd=='worker':
        from .worker import main as work
        work();return
    elif cmd=='enqueue':
        if Path(args.file).stat().st_size>262144:raise ValueError('Request JSON exceeds 256 KiB')
        with db() as c:result=enqueue(c,json.loads(Path(args.file).read_text()),args.title,args.priority)
        ensure_worker()
    elif cmd=='import-avatar':
        with db() as c:result=import_avatar(c,args.folder)
    elif cmd=='schedule':
        from zoneinfo import ZoneInfo
        minutes(args.start);minutes(args.end);ZoneInfo(args.timezone)
        if not 0<=args.idle_minutes<=1440:raise ValueError('idle-minutes must be 0–1440')
        with db() as c:
            setv(c,'window',{'start':args.start,'end':args.end,'timezone':args.timezone});setv(c,'idle_minutes',args.idle_minutes)
            setv(c,'require_idle',not args.no_idle);setv(c,'stop_at_end',not args.finish_current);event(c,'schedule_configured')
        result={'saved':True,'note':'配置不自动启用；auto 才启用时段运行'}
    elif cmd=='configure':
        target=Path(args.deployment).expanduser().resolve()
        if not (target/'agent_session.py').is_file():raise ValueError('Deployment agent_session.py not found')
        with db() as c:setv(c,'deployment',str(target))
        result={'deployment':str(target)}
    elif cmd=='delete':
        from .deletion import delete_job
        result=delete_job(args.id)
    elif cmd in ('retry','cancel','prioritize','reveal'):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM jobs WHERE id=?',(args.id,)).fetchone()
            if not r:raise ValueError('Job not found')
            if cmd=='reveal':
                path=r['output']
                if not path and r['attempt_id']:path=c.execute('SELECT directory FROM attempts WHERE id=?',(r['attempt_id'],)).fetchone()[0]
                if not path:raise ValueError('尚无输出目录')
                subprocess.run(['/usr/bin/open','-R',path],check=True)
            elif cmd=='prioritize':c.execute('UPDATE jobs SET priority=priority+1,updated=? WHERE id=?',(time.time(),args.id))
            elif cmd=='retry':
                from .recovery import prepare_retry
                prepare_retry(c,r,args.refresh_deployment,args.reuse_render)
            elif r['status'] in ('running','cancel_requested'):
                a=c.execute('SELECT directory FROM attempts WHERE id=?',(r['attempt_id'],)).fetchone();(Path(a[0])/'STOP').touch()
                c.execute("UPDATE jobs SET status='cancel_requested' WHERE id=?",(args.id,))
            elif r['status']!='completed':c.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?",(time.time(),args.id))
            event(c,cmd,args.id)
        result={'id':args.id,'action':cmd}
    elif cmd=='launch-agent':
        label='local.queue-mac-h3.worker';path=Path.home()/'Library/LaunchAgents'/f'{label}.plist';domain=f'gui/{os.getuid()}'
        if args.action=='install':
            path.parent.mkdir(exist_ok=True,parents=True)
            content={'Label':label,'ProgramArguments':[sys.executable,'-m','h3queue.worker'],'WorkingDirectory':str(ROOT),
                     'EnvironmentVariables':{'H3_QUEUE_HOME':str(home()),**{k:os.environ[k] for k in ('H3_QUEUE_FFMPEG','H3_QUEUE_FFPROBE','H3_QUEUE_MACMON','PATH') if k in os.environ}},'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},
                     'StandardOutPath':str(home()/'launchd.log'),'StandardErrorPath':str(home()/'launchd.log')}
            path.write_bytes(plistlib.dumps(content));subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
        else:
            control('stop');subprocess.run(['launchctl','bootout',domain+'/'+label],check=False);path.unlink(missing_ok=True)
        result={'action':args.action,'path':str(path)}
    elif cmd=='doctor':
        from .providers import catalog
        from .system_tools import find_tool
        import importlib.util,platform
        with db() as c:base=Path(get(c,'deployment'))
        result={'python':sys.executable,'sqlite':str(home()/'queue.sqlite3'),'deployment':str(base),'providers':catalog(base),
                'platform':{'system':platform.system(),'machine':platform.machine(),'python_version':platform.python_version()},
                'psutil':importlib.util.find_spec('psutil') is not None,
                'tools':{name:find_tool(name,base) for name in ('ffmpeg','ffprobe','macmon')},
                'dependencies':{str(x):x.exists() for x in [base/'agent_session.py',base/'H3/generate_fast.py',base/'H3/resource_monitor.py',base/'H3/minimax-h3-mlx/.venv/bin/python']}}
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(1)
