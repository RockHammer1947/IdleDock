"""One low-rate macmon reader; bounded history and honest chip/wall energy labels."""
import json,math,os,selectors,sqlite3,subprocess,threading,time,platform
from pathlib import Path
from .store import home,db,get,setv,event,atomic_json
from .safety import DEFAULTS,ThermalLatch,sample_from
from .system_tools import find_tool

def finite(value,lo=0,hi=2000):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and lo<=value<=hi else None

def prune(c,now):
    c.execute('DELETE FROM telemetry WHERE time < ?',(now-7*86400,))
    c.execute('DELETE FROM telemetry WHERE id NOT IN (SELECT id FROM telemetry ORDER BY id DESC LIMIT 20160)')
    c.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 20000)')

class Energy:
    def __init__(self):self.previous=None;self.chip_wh=0.;self.wall_wh=0.;self.coverage_s=0.
    def add(self,stamp,power,p):
        if not isinstance(power,(int,float)) or not math.isfinite(power) or not 0<=power<2000:
            self.previous=None;return
        if self.previous:
            t,w=self.previous;dt=stamp-t
            if 0<dt<=15: # do not bridge sleep, stale telemetry or clock jumps
                watts=(w+power)/2;self.chip_wh+=watts*dt/3600
                self.wall_wh+=(watts*p['wall_multiplier']+p['wall_overhead_w'])*dt/3600;self.coverage_s+=dt
        self.previous=(stamp,power)

class Sampler:
    def __init__(self,deployment):
        self.deployment=deployment;self.binary=None;self.stop_event=threading.Event();self.proc=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.energy=Energy();self.latch=ThermalLatch()
    def start(self):self.thread.start()
    def close(self):self.stop_event.set();self.thread.join(timeout=6)
    def run(self):
        if platform.system()=='Linux':
            from .linux_telemetry import run_sampler
            return run_sampler(self)
        last_write=0;last_level=None;alert_seq=0
        try:
            while not self.stop_event.is_set():
                try:
                    with db() as c:
                        previous=get(c,'telemetry_totals')
                        self.energy.chip_wh=previous.get('chip_wh',0);self.energy.wall_wh=previous.get('wall_wh',0);self.energy.coverage_s=previous.get('coverage_s',0)
                        alert_seq=get(c,'thermal_alert').get('sequence',0)
                    break
                except sqlite3.Error:self.stop_event.wait(2)
            while not self.stop_event.is_set():
                selector=None
                try:
                    self.binary=find_tool('macmon',self.deployment)
                    if not self.binary:raise FileNotFoundError('macmon is unavailable')
                    self.proc=subprocess.Popen([str(self.binary),'pipe','-i','3000'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,bufsize=0)
                    selector=selectors.DefaultSelector();selector.register(self.proc.stdout,selectors.EVENT_READ);pending=b''
                    while not self.stop_event.is_set() and self.proc.poll() is None:
                        if not selector.select(1):continue
                        chunk=os.read(self.proc.stdout.fileno(),65536)
                        if not chunk:break
                        pending+=chunk
                        if len(pending)>1024*1024:raise ValueError('oversized sensor output')
                        while b'\n' in pending:
                            line,pending=pending.split(b'\n',1)
                            try:d=json.loads(line)
                            except ValueError:continue
                            if not isinstance(d,dict):continue
                            now=time.time();temp=d.get('temp',{})
                            sample={'time':now,'cpu_c':temp.get('cpu_temp_avg'),'gpu_c':temp.get('gpu_temp_avg'),
                                    'chip_w':d.get('all_power'),'ram_used_gib':d.get('memory',{}).get('ram_usage',0)/1024**3,
                                    'ram_total_gib':d.get('memory',{}).get('ram_total',0)/1024**3,'gpu_percent':d.get('gpu_active_ratio',0)*100}
                            for key in ('cpu_c','gpu_c','chip_w','ram_used_gib','ram_total_gib','gpu_percent'):sample[key]=finite(sample[key])
                            atomic_json(home()/'telemetry.json',sample);valid=sample_from(home()/'telemetry.json')
                            with db() as c:
                                policy=get(c,'safety');self.energy.add(time.monotonic(),sample['chip_w'],policy)
                                sample.update(chip_wh=self.energy.chip_wh,wall_wh=self.energy.wall_wh,coverage_s=self.energy.coverage_s)
                                sample['wall_w_estimate']=(sample['chip_w']*policy['wall_multiplier']+policy['wall_overhead_w']) if isinstance(sample['chip_w'],(float,int)) and math.isfinite(sample['chip_w']) else None
                                level=self.latch.update(valid,policy,time.monotonic());sample['level']=level
                                if level!=last_level:
                                    alert_seq+=1;alert={'sequence':alert_seq,'level':level,'time':now,'cpu_c':sample['cpu_c'],'gpu_c':sample['gpu_c']}
                                    setv(c,'thermal_alert',alert);event(c,'thermal_'+level,**alert);last_level=level
                                if now-last_write>=30:
                                    totals={'chip_wh':self.energy.chip_wh,'wall_wh':self.energy.wall_wh,'coverage_s':self.energy.coverage_s}
                                    setv(c,'telemetry_totals',totals)
                                    c.execute('INSERT INTO telemetry(time,data) VALUES(?,?)',(now,json.dumps(sample)))
                                    prune(c,now)
                                    last_write=now
                            atomic_json(home()/'telemetry.json',sample)
                except (OSError,ValueError,TypeError,KeyError,AttributeError,sqlite3.Error):pass
                finally:
                    if selector:selector.close()
                    if self.proc:
                        try:self.proc.terminate()
                        except ProcessLookupError:pass
                        try:self.proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
                        if self.proc.stdout:self.proc.stdout.close()
                if not self.stop_event.is_set():self.stop_event.wait(10)
        finally:
            try:
                with db() as c:setv(c,'telemetry_totals',{'chip_wh':self.energy.chip_wh,'wall_wh':self.energy.wall_wh,'coverage_s':self.energy.coverage_s})
            except Exception:pass
