"""Bounded process lifecycle, including codec/validation phases and orphan cleanup."""
import json,os,signal,subprocess,time
from pathlib import Path
from .store import atomic_json,home
from .safety import blocked,sample_from,validate
from .processes import members,cleanup
from .schedule import smart_guard,activity_stop

def run(command,cwd,out,name,policy,env=None,baseline_swap=None,max_seconds=None,smart_idle_minutes=None,min_available_gib=0):
    import psutil
    out=Path(out);start=time.monotonic();base_swap=psutil.swap_memory().used if baseline_swap is None else baseline_swap
    peak=0;swap_peak=0;available=psutil.virtual_memory().available;reason=None;last_write=0;last_registry=0
    registry=out/'owned-group.json';peak_power=0;power_sum=0;power_count=0
    activity=smart_guard(smart_idle_minutes)
    if activity:
        activity_stop(out,activity);return {'exit_code':130,'elapsed_s':0,'aborted':activity}
    last_activity_check=0
    policy={**policy,'min_available_gib':max(policy['min_available_gib'],min_available_gib)}
    preflight=blocked(policy,sample_from(home()/'telemetry.json'),out,psutil.virtual_memory().available/1024**3)
    if preflight:
        atomic_json(out/'guard-trip.json',{'reason':preflight,'time':time.time()});(out/'STOP').touch()
        return {'exit_code':130,'elapsed_s':0,'aborted':preflight}
    with (out/(name+'.log')).open('wb') as log,(out/(name+'.memory.jsonl')).open('w') as metrics:
        proc=subprocess.Popen(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:born=psutil.Process(proc.pid).create_time()
        except psutil.NoSuchProcess:born=0
        record={'pgid':proc.pid,'members':[{'pid':proc.pid,'born':born}]}
        atomic_json(registry,record)
        try:
            while True:
                now=time.monotonic();elapsed=now-start
                if (home()/'safety.json').exists():
                    try:
                        policy=validate(json.loads((home()/'safety.json').read_text()))
                        policy['min_available_gib']=max(policy['min_available_gib'],min_available_gib)
                    except (OSError,ValueError,TypeError):reason='保护配置无效，暂停计算'
                if now-last_registry>=.5:
                    fresh=members(proc.pid);known={(m['pid'],m['born']) for m in record['members']}
                    record['members']+= [m for m in fresh if (m['pid'],m['born']) not in known]
                    atomic_json(registry,record);last_registry=now
                if now-last_activity_check>=2:
                    activity=smart_guard(smart_idle_minutes)
                    if activity:activity_stop(out,activity)
                    last_activity_check=now
                if (out/'STOP').exists():reason=reason or '已请求停止'
                if log.tell()>512*1024*1024:reason='单阶段日志超过 512 MiB，暂停计算'
                vm=psutil.virtual_memory();growth=max(0,psutil.swap_memory().used-base_swap)/1024**3
                telemetry=sample_from(home()/'telemetry.json')
                check=blocked(policy,telemetry,out,vm.available/1024**3,growth,elapsed)
                # Thermal stop needs sustained threshold; worker latches it. Stale sensors/resources stop immediately.
                if check=='温度达到停止阈值':
                    if 'hot_since' not in locals():hot_since=now
                    if now-hot_since<policy['hold_seconds']:check=None
                else:hot_since=now
                reason=reason or check
                if max_seconds and elapsed>max_seconds:reason='媒体处理超时'
                if reason:
                    (out/'STOP').touch()
                    if reason!='已请求停止':atomic_json(out/'guard-trip.json',{'reason':reason,'time':time.time()})
                    break
                if now-last_write>=1:
                    available=min(available,vm.available);peak=max(peak,vm.used);swap_peak=max(swap_peak,growth)
                    w=telemetry.get('chip_w')
                    if isinstance(w,(float,int)) and 0<=w<2000 and telemetry.get('age_seconds',1e9)<policy['stale_seconds']:
                        power_sum+=w;power_count+=1;peak_power=max(peak_power,w)
                    metrics.write(json.dumps({'elapsed_s':elapsed,'ram_used':vm.used,'available_bytes':vm.available,'swap_growth_gib':growth})+'\n');metrics.flush();last_write=now
                if proc.poll() is not None:break
                time.sleep(.25)
        finally:
            # Also kill grandchildren that outlived a crashed launcher or ignored SIGTERM.
            cleanup(registry)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        result={'exit_code':proc.returncode,'elapsed_s':time.monotonic()-start,'aborted':reason,
                'system_ram_peak_gib':peak/1024**3,'min_available_gib':available/1024**3,'swap_growth_peak_gib':swap_peak,
                'chip_power_mean_w':power_sum/power_count if power_count else None,'chip_power_peak_w':peak_power}
        atomic_json(out/(name+'.result.json'),result)
        return result
