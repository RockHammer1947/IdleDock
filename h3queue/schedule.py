from datetime import datetime
from zoneinfo import ZoneInfo
import math, re, subprocess, json, time
from .store import home, atomic_json

_UNSET=object()

def minutes(value):
    if not re.fullmatch(r'\d{2}:\d{2}',value):raise ValueError('时间格式必须为 HH:MM')
    h,m=map(int,value.split(':'))
    if h>23 or m>59:raise ValueError('时间超出范围')
    return h*60+m

def within(window,now=None):
    zone=ZoneInfo(window['timezone']);now=now or datetime.now(zone)
    now=now.astimezone(zone);minute=now.hour*60+now.minute
    start,end=minutes(window['start']),minutes(window['end'])
    if start==end:return True
    return start<=minute<end if start<end else minute>=start or minute<end

def idle_seconds():
    try:
        out=subprocess.check_output(['/usr/sbin/ioreg','-r','-c','IOHIDSystem'],text=True,timeout=3)
        match=re.search(r'"HIDIdleTime"\s*=\s*(\d+)',out)
        return int(match[1])/1e9 if match else None
    except (OSError,subprocess.SubprocessError,ValueError):return None

def smart_state(idle_minutes,idle=_UNSET):
    current=idle_seconds() if idle is _UNSET else idle
    valid=isinstance(current,(int,float)) and not isinstance(current,bool) and math.isfinite(current) and current>=0
    remaining=max(0,idle_minutes*60-current) if valid else None
    ready=valid and remaining==0
    return {'idle_seconds':current if valid else None,'remaining_seconds':remaining,'ready':ready,
            'reason':('智能模式：空闲已达标' if ready else f'智能模式：再空闲 {max(1,math.ceil(remaining/60))} 分钟后开始') if valid else '无法读取键鼠空闲状态，等待恢复'}

def allowed(mode,window,require_idle,idle_minutes,idle=_UNSET):
    if mode=='manual':return True,'手动运行'
    if mode=='smart':
        state=smart_state(idle_minutes,idle);return state['ready'],state['reason']
    if mode!='auto':return False,'已暂停'
    if not within(window):return False,'等待运行时段'
    if require_idle:
        state=smart_state(idle_minutes,idle)
        if not state['ready']:return False,'等待机器闲置' if state['idle_seconds'] is not None else state['reason']
    return True,'自动运行'

def runtime_state(mode,idle_minutes):
    atomic_json(home()/'runtime.json',{'mode':mode,'smart_idle_minutes':idle_minutes,'time':time.time()})

def activity_stop(out,reason):
    marker=out/'activity-stop.json'
    if not marker.exists():atomic_json(marker,{'reason':reason,'time':time.time()})
    (out/'STOP').touch()

def smart_guard(fallback_minutes=None):
    """Read cheap worker control snapshot; do not block resource checks on SQLite."""
    path=home()/'runtime.json';required=fallback_minutes is not None
    try:
        state=json.loads(path.read_text())
        if state['mode'] not in ('paused','manual','auto','smart'):raise ValueError('Invalid mode')
        if state['mode']!='smart':return None
        required=True
        age=time.time()-state['time'];minutes=state['smart_idle_minutes']
        if not 0<=age<=10 or not isinstance(minutes,int) or not 1<=minutes<=240:raise ValueError('Invalid controller state')
    except (OSError,ValueError,KeyError,TypeError):
        return '智能调度状态失联，等待重新调度' if required else None
    state=smart_state(minutes)
    if not state['ready']:return '检测到键鼠操作，重新等待空闲' if state['idle_seconds'] is not None else state['reason']
    return None
