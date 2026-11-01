"""Runs inside the existing deployment wrapper. No shell and no provider downloads."""
import json,os,signal,subprocess,sys,threading,time,wave
from pathlib import Path
from .store import digest,atomic_json
from .integrity import validate_spec,DeploymentChanged
from .system_tools import require_tool

def normalization_command(ff,s,source,output):
    height=s['delivery_height'];y=(s['height']-height)//2
    # Accurate seek can leave the first 24fps frame after t=0. Start the 30fps
    # grid at zero so fractional trims do not silently lose one delivery frame.
    return [ff,'-v','error','-threads','2','-ss',str(s['trim_s']),'-i',str(source),'-ss',str(s['trim_s']),'-i',s['audio'],
        '-map','0:v:0','-map','1:a:0','-vf',f'crop={s["width"]}:{height}:0:{y},fps=30:start_time=0',
        '-t',str(s['delivery_frames']/30),'-c:v','libx264','-threads','2','-crf','16','-pix_fmt','yuv420p',
        '-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]

def execute(path):
    path=Path(path);request=json.loads(path.read_text());s=request['spec'];out=path.parent
    if os.environ.get('LOCAL_MODEL_SESSION_TARGET')!='h3':raise RuntimeError('Must run through agent_session.py h3')
    import psutil
    atomic_json(out/'inner.json',{'pid':os.getpid(),'born':psutil.Process().create_time(),'time':time.time()})
    if (out/'STOP').exists():return 130
    validate_spec(s)
    base=Path(s['deployment'])/'H3';sys.path.insert(0,str(base))
    from .guarded_run import run as guarded
    from .safety import DEFAULTS
    policy={**DEFAULTS,**request.get('safety',{})}
    def media(command,name):
        result=guarded(command,out,out,name,policy,env=env,max_seconds=600,smart_idle_minutes=request.get('smart_idle_minutes'))
        if result['exit_code']!=0 or result['aborted']:raise RuntimeError(name+': '+str(result))
    ff=require_tool('ffmpeg');fp=require_tool('ffprobe')
    env=dict(os.environ)
    # Finder-launched workers may not inherit the user's Homebrew PATH.
    env['PATH']=os.pathsep.join(dict.fromkeys([str(Path(ff).parent),str(Path(fp).parent),env.get('PATH','')]))
    if s['adapter']=='native-audio':
        command=[s['engine'],'-d',str(base/'models/MiniMax-H3'),'-p',s['prompt'],
                 '--width',str(s['width']),'--height',str(s['height']),'--frames',str(s['frames']),
                 '--steps','20','--layers','50','--reuse','1','--seed',str(s['seed']),'--profile',
                 '--first-frame',s['portrait'],'--audio-drive',s['audio'],'-o',str(out/'video.mp4')]
        cwd=Path(s['engine']).parent
    else:
        (out/'prompt.txt').write_text(s['prompt'])
        command=[sys.executable,str(base/'generate_fast.py'),'--profile',s['profile'],'--prompt-file',str(out/'prompt.txt'),
                 '--width',str(s['width']),'--height',str(s['height']),'--frames',str(s['frames']),'--seed',str(s['seed']),
                 '--out',str(out/'video.mp4')]
        cwd=base
    atomic_json(out/'command.json',command)
    # One outer monitor also covers the profile entrypoint; never nest --monitor locks.
    if s.get('reuse_render'):
        from .recovery import reuse_raw
        result=reuse_raw(s,out)
    else:
        result=guarded(command,cwd,out,'render',policy,env=env,smart_idle_minutes=request.get('smart_idle_minutes'))
    if (out/'STOP').exists():return 130
    if result['exit_code']!=0:raise RuntimeError(f'Engine failed: {result["exit_code"]}; see render.log')
    if s['adapter']=='native-audio' and 'audio-drive invariant PASS' not in (out/'render.log').read_text():raise RuntimeError('Audio-drive invariant missing')
    media([ff,'-v','error','-threads','2','-i',str(out/'video.mp4'),'-f','null','-'],'decode-raw')
    output=out/'video.mp4'
    if s['adapter']=='native-audio':
        output=out/'preview-720p.mp4'
        media(normalization_command(ff,s,out/'video.mp4',output),'normalize')
    media([fp,'-v','error','-count_frames','-show_streams','-of','json',str(output)],'probe')
    probe=json.loads((out/'probe.log').read_text())
    video=next(x for x in probe['streams'] if x['codec_type']=='video')
    if not any(x['codec_type']=='audio' for x in probe['streams']):raise RuntimeError('Missing audio stream')
    if video['width']!=s['width']:raise RuntimeError('Width mismatch')
    if s['adapter']=='native-audio' and (int(video['nb_read_frames'])!=s['delivery_frames'] or video['height']!=s['delivery_height']):
        raise RuntimeError(f'Delivery mismatch: expected {s["delivery_frames"]} frames / {s["delivery_height"]}p, got {video["nb_read_frames"]} frames / {video["height"]}p')
    media([ff,'-v','error','-threads','2','-i',str(output),'-f','null','-'],'decode-output')
    if (out/'STOP').exists():return 130
    atomic_json(out/'verified.json',{'output':str(output),'sha':digest(output),'elapsed':result['elapsed_s'],
        'chip_power_mean_w':result.get('chip_power_mean_w'),'review':'technical_pass_visual_sync_review_pending','probe':probe})
    return 0


if __name__=='__main__':
    try:sys.exit(execute(sys.argv[1]))
    except Exception as e:
        atomic_json(Path(sys.argv[1]).parent/'error.json',{'error':str(e),'error_kind':'deployment_changed' if isinstance(e,DeploymentChanged) else 'execution'});raise
