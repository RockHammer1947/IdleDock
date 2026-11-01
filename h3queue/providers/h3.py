"""Legacy H3 adapter. Keep its normalized spec byte-compatible with existing jobs."""
import math, wave
from pathlib import Path
from ..store import digest

PROFILES={'native20':20,'lightx3':3,'tf3':3}

def normalize(raw,deployment):
    s=dict(raw);profile=s.get('profile','native20')
    if profile not in PROFILES:raise ValueError('Unknown H3 profile')
    adapter=s.get('adapter','profile')
    if adapter not in ('profile','native-audio'):raise ValueError('Unknown adapter')
    width=int(s.get('width',1280));height=int(s.get('height',736))
    frames=int(s.get('frames',124));seed=int(s.get('seed',42))
    if width<=0 or height<=0 or width%32 or height%32 or width*height>1920*1088:raise ValueError('尺寸必须是32的倍数，当前上限1920×1088像素')
    if not 4<=frames<=362:raise ValueError('帧数须为4–362')
    prompt=str(s.get('prompt','')).strip()
    if not prompt or len(prompt)>20000:raise ValueError('Prompt is empty or too long')
    result=dict(profile=profile,adapter=adapter,width=width,height=height,frames=frames,seed=seed,prompt=prompt,deployment=str(Path(deployment).resolve()))
    if adapter=='native-audio':
        if profile!='native20':raise ValueError('已验证的音频驱动适配器只支持 native20')
        if frames<5 or (frames-5)%17:raise ValueError('原生音频驱动帧数需为 17n+5')
        for key in ('engine','portrait','audio'):
            path=Path(s[key]).expanduser().resolve()
            if not path.is_file():raise ValueError(f'Missing {key}: {path}')
            result[key]=str(path);result[key+'_sha256']=digest(path)
        with wave.open(result['audio']) as w:duration=w.getnframes()/w.getframerate()
        if not 2<=duration<=15 or duration>frames/24+.005:raise ValueError('驱动WAV须为2–15秒且不超过生成时长')
        result['audio_seconds']=duration
        trim=float(s.get('trim_s',0));delivery=int(s.get('delivery_frames',int(duration*30+.001)))
        if not math.isfinite(trim) or trim<0 or delivery<=0 or trim+delivery/30>min(frames/24,duration)+.001:raise ValueError('交付裁切超出生成时长')
        result.update(trim_s=trim,delivery_frames=delivery,delivery_height=int(s.get('delivery_height',height)))
        if result['delivery_height']>height or result['delivery_height']<2 or result['delivery_height']%2:raise ValueError('Invalid delivery height')
    else:
        if (frames-1)%3:raise ValueError('generate_fast 输入帧数须为 3n+1')
        if s.get('audio') or s.get('portrait'):raise ValueError('profile适配器只接收文生视频；音频驱动请用native-audio')
    # Only pin entrypoints actually used by this adapter. Native audio runs its
    # separately pinned engine and our guarded_run, not generate_fast/resource_monitor.
    base=Path(result['deployment']);pins=[]
    paths=[base/'agent_session.py']
    if adapter=='profile':paths += [base/'H3/generate_fast.py',base/'H3/resource_monitor.py']
    for path in paths:
        if path.exists():pins.append([str(path),digest(path)])
    result['deployment_pins']=pins
    return result


class H3Provider:
    id = 'h3'
    label = 'H3 视频'
    output_kind = 'video'
    normalize = staticmethod(normalize)

    def resources(self, spec):
        return {'device': 'gpu', 'min_available_gib': 0}

    def describe(self, spec):
        return {'provider': self.id, 'provider_label': self.label, 'output_kind': self.output_kind,
                'profile': spec['profile'], 'width': spec['width'], 'height': spec['height'],
                'seconds': spec['frames']/24, 'summary': f"{spec['frames']/24:.1f} 秒视频"}

    def run(self, context):
        from ..h3_executor import execute
        code = execute(context.path)
        if code:
            raise InterruptedError('H3 execution stopped')
        import json
        return json.loads((context.out/'verified.json').read_text())
