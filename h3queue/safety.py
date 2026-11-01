"""Queue policy guards. User thresholds are policies, not hardware specifications."""
import json, math, shutil, time
from pathlib import Path

DEFAULTS = dict(cpu_warn_c=85.0, gpu_warn_c=85.0, stop_c=95.0,
                hold_seconds=10, hysteresis_c=5.0, stop_on_overheat=True,
                require_telemetry=True, stale_seconds=20, min_disk_gib=15.0,
                min_available_gib=4.0, max_swap_growth_gib=8.0,
                max_runtime_hours=4.0, wall_multiplier=1.25, wall_overhead_w=20.0,
                price_per_kwh=0.60, sound=True)

def validate(raw):
    if not isinstance(raw,dict) or set(raw)-set(DEFAULTS):raise ValueError('Unknown or invalid safety policy')
    p={**DEFAULTS,**raw}
    ranges={'cpu_warn_c':(40,105),'gpu_warn_c':(40,105),'stop_c':(45,110),
      'hold_seconds':(3,120),'hysteresis_c':(1,15),'stale_seconds':(10,120),
      'min_disk_gib':(2,200),'min_available_gib':(1,64),'max_swap_growth_gib':(.25,16),
      'max_runtime_hours':(.05,24),'wall_multiplier':(1,3),'wall_overhead_w':(0,300),'price_per_kwh':(0,10)}
    for key,(lo,hi) in ranges.items():
        value=p[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError(f'{key} must be finite and within {lo}–{hi}')
    if p['stop_c']<max(p['cpu_warn_c'],p['gpu_warn_c']):raise ValueError('Stop threshold must be >= alert thresholds')
    for k in ('stop_on_overheat','require_telemetry','sound'):
        if not isinstance(p[k],bool):raise ValueError(k+' must be boolean')
    return p

def sample_from(path,now=None):
    now=time.time() if now is None else now
    try:
        d=json.loads(Path(path).read_text())
        if not isinstance(d,dict):raise ValueError('Invalid sensor object')
        stamp=d.get('time',0)
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp>now+2:raise ValueError('Invalid timestamp')
        d['age_seconds']=max(0,now-stamp)
        for key in ('cpu_c','gpu_c'):
            value=d.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<130:raise ValueError('Invalid temperature')
        return d
    except (OSError,ValueError,TypeError):return {'time':0,'age_seconds':1e9,'error':'传感器不可用或数据无效'}

def blocked(policy,sample,directory,available_gib=None,swap_growth_gib=None,runtime_s=0):
    p=validate(policy)
    if shutil.disk_usage(directory).free/1024**3 < p['min_disk_gib']:return '磁盘可用空间低于保留值'
    if available_gib is not None and available_gib<p['min_available_gib']:return '系统可用内存低于保留值'
    if swap_growth_gib is not None and swap_growth_gib>p['max_swap_growth_gib']:return '交换内存增长超过阈值'
    if runtime_s>p['max_runtime_hours']*3600:return '任务超过最长运行时限'
    if p['require_telemetry'] and sample.get('age_seconds',1e9)>p['stale_seconds']:return '温度监测失联，暂停计算'
    if p['stop_on_overheat'] and max(sample.get('cpu_c',0),sample.get('gpu_c',0))>=p['stop_c']:return '温度达到停止阈值'
    return None

class ThermalLatch:
    def __init__(self):self.warn_since=None;self.hot_since=None;self.level='normal'
    def update(self,s,p,now):
        if s.get('age_seconds',1e9)>p['stale_seconds']:
            self.warn_since=None;self.hot_since=None;self.level='unavailable';return self.level
        cpu,gpu=s['cpu_c'],s['gpu_c']
        warn=cpu>=p['cpu_warn_c'] or gpu>=p['gpu_warn_c'];hot=max(cpu,gpu)>=p['stop_c']
        self.warn_since=(self.warn_since if self.warn_since is not None else now) if warn else None
        self.hot_since=(self.hot_since if self.hot_since is not None else now) if hot else None
        if self.hot_since is not None and now-self.hot_since>=p['hold_seconds']:self.level='critical'
        elif self.warn_since is not None and now-self.warn_since>=p['hold_seconds']:self.level='warning'
        elif cpu<p['cpu_warn_c']-p['hysteresis_c'] and gpu<p['gpu_warn_c']-p['hysteresis_c']:self.level='normal'
        elif self.level=='unavailable':self.level='normal'
        return self.level
