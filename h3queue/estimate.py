import hashlib, json, math, statistics, subprocess
from functools import lru_cache

@lru_cache(maxsize=1)
def machine():
    try:
        return subprocess.check_output(['/usr/sbin/sysctl','-n','machdep.cpu.brand_string'],text=True).strip()
    except (OSError,subprocess.SubprocessError):
        return 'unknown'

def metric_identity(spec):
    provider=spec.get('provider','h3')
    if provider=='h3':return spec['profile'],spec['width']*spec['height']*spec['frames']
    identity={k:v for k,v in spec.items() if k not in ('text','seed','reuse_render')}
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),len(spec['text']) if provider=='tts' else 1


def estimate(c,spec,rows=None):
    if spec.get('provider','h3')!='h3':
        key,units=metric_identity(spec)
        if rows is None:rows=list(c.execute('SELECT * FROM provider_metrics WHERE provider=? AND metric_key=? AND machine=?',
                                            (spec['provider'],key,machine())))
        # Only nearby text sizes: loading overhead makes broad linear scaling misleading.
        near=sorted((r for r in rows if .5<=units/r['units']<=2),key=lambda r:abs(math.log(units/r['units'])))[:6]
        if not near:return {'seconds':None,'low':None,'high':None,'samples':0,'basis':'本机该 provider/配置尚无相近成功记录'}
        values=[r['elapsed']*units/r['units'] for r in near]
        return {'seconds':round(statistics.median(values)),'low':round(min(values)/1.8),'high':round(max(values)*1.8),
                'samples':len(near),'basis':'同 provider/配置相近任务粗估（含加载）'}
    return h3_estimate(c,spec,rows)


def h3_estimate(c,spec,rows=None):
    if rows is None:rows=list(c.execute('SELECT * FROM benchmarks WHERE profile=? AND machine=?',(spec['profile'],machine())))
    pixels=spec['width']*spec['height'];frames=spec['frames'];target=pixels*frames
    if not rows:
        return {'seconds':None,'low':None,'high':None,'samples':0,'basis':'本机该档位尚无成功记录'}
    near=sorted(rows,key=lambda r:abs(math.log((r['width']*r['height']*r['frames'])/target)))[:6]
    # Attention grows faster than linearly. Bound sparse-data extrapolation generously.
    estimates=[r['elapsed']*(target/(r['width']*r['height']*r['frames']))**1.25 for r in near]
    exact_res=all(r['width']==spec['width'] and r['height']==spec['height'] for r in near)
    median=statistics.median(estimates);spread=1.35 if len(near)>=3 and exact_res else 1.8
    return {'seconds':round(median),'low':round(min(estimates)/spread),
            'high':round(max(estimates)*spread),'samples':len(near),
            'basis':'本机实测插值' if exact_res else '跨分辨率粗估；显存压力可能放大误差'}
