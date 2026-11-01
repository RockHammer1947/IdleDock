"""One TTS task per isolated process, using its profile's existing Python environment.

No inference-library imports at module scope. The queue owns locks/monitoring.
Model-specific adapters can be extended independently of the scheduler.
"""
import argparse
import json
import os
from pathlib import Path
import random
import sys


def mlx_audio(spec, output):
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    from mlx_audio.tts.utils import load_model
    model = load_model(spec['model_path'])
    profile, lang = spec['profile'], spec['language']
    options = dict(spec['profile_config'].get('generation', {}))
    if profile in ('qwen-base', 'qwen-custom'):
        options['lang_code'] = {'zh':'Chinese','en':'English'}[lang]
        if profile=='qwen-custom':options['voice']='Vivian'
    elif profile=='kokoro':
        options.update(voice='zf_xiaobei' if lang=='zh' else 'af_heart', lang_code='z' if lang=='zh' else 'a')
        if lang=='zh' and len(spec['text'])>80:options['split_pattern']=r'(?<=[。！？])\s*'
    else:options['lang_code']=lang
    options.update(spec['options'])
    if spec.get('reference_audio'):
        options['ref_audio']=spec['reference_audio']
        if spec.get('reference_text'):options['ref_text']=spec['reference_text']
        if spec['profile_config']['runtime']=='mlx-audio-plus':
            import soxr
            audio, rate=sf.read(spec['reference_audio'], dtype='float32')
            if audio.ndim==2:audio=audio.mean(axis=1)
            if rate!=24000:audio=soxr.resample(audio,rate,24000)
            options['ref_audio']=mx.array(audio)
    options['stream']=False
    chunks=[];rate=None
    for result in model.generate(text=spec['text'], **options):
        mx.eval(result.audio)
        audio=np.asarray(result.audio,dtype=np.float32)
        if audio.ndim==2 and audio.shape[0]<=2 and audio.shape[1]>audio.shape[0]:audio=audio.T
        if audio.ndim==2 and audio.shape[1]==1:audio=audio[:,0]
        if rate is not None and rate!=int(result.sample_rate):raise ValueError('Changing sample rate within one task')
        rate=int(result.sample_rate)
        if audio.size:chunks.append(audio.copy())
    if not chunks:raise ValueError('Model returned no audio')
    write_audio(output,np.concatenate(chunks,axis=0),rate)


def indextts(spec, output):
    import soundfile as sf
    os.environ['INDEXTTS_W2V_BERT_DIR']=str(Path(spec['deployment'])/'TTS/runtimes/models/w2v-bert-2.0')
    from mlx_indextts.runtime import TTSRuntime, GenerateOptions
    model=TTSRuntime(quantize='fp32',memory_limit_gb=64)
    model.load(spec['model_path'])
    options={**spec['profile_config'].get('generation',{}), **spec['options']}
    allowed={'diffusion_steps','use_gpt_latent','temperature','emotion'}
    if set(options)-allowed:raise ValueError('Unsupported IndexTTS options: '+str(sorted(set(options)-allowed)))
    opts=GenerateOptions(language=spec['language'],seed=spec['seed'],verbose=False,
                         denoise_ref_audio=False,denoise_emotion_ref_audio=False)
    for key,value in options.items():setattr(opts,key,value)
    model.generate(spec['text'],spec['reference_audio'],str(output),profile='v25',model=spec['model_path'],options=opts)
    audio,rate=sf.read(output,dtype='float32')
    write_audio(output,audio,rate)


def auk(spec, output):
    from auk_mlx.infer import AukMLX, GenerateOptions
    path=Path(spec['model_path']);flash=spec['profile'].endswith('flash')
    model=AukMLX(str(path),str(path/('config_flash.yaml' if flash else 'config_base.yaml')),str(path/'qwen'),bits=8)
    options={**spec['profile_config'].get('generation',{}), **spec['options']}
    if set(options)-{'gen_seconds','nfe'}:raise ValueError('AuK options support gen_seconds/nfe')
    duration=options.get('gen_seconds',max(5.0,min(45.0,len(spec['text'])/(4.2 if spec['language']=='zh' else 13)+1.5)))
    opts=GenerateOptions(gen_seconds=duration,nfe=options.get('nfe',4 if flash else 32),seed=spec['seed'])
    audio,rate=model.generate('Say the following with the same voice: '+json.dumps(spec['text'],ensure_ascii=False),
                              audio_path=spec['reference_audio'],opts=opts)
    write_audio(output,audio,rate)


def write_audio(output,audio,rate):
    import numpy as np
    import soundfile as sf
    audio=np.asarray(audio,dtype=np.float32)
    if not audio.size or not np.isfinite(audio).all():raise ValueError('Empty/nonfinite audio')
    if float(np.max(np.abs(audio)))<1e-5:raise ValueError('Silent audio')
    sf.write(output,audio,int(rate),subtype='PCM_16')


ADAPTERS={'mlx-audio':mlx_audio,'mlx-audio-plus':mlx_audio,'indextts':indextts,'auk':auk}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();spec=json.loads(args.request.read_text())['spec']
    if os.environ.get('LOCAL_MODEL_SESSION_TARGET')!='h3':raise RuntimeError('Use the queue; a GPU resource session is required')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',VIRTUAL_ENV=sys.prefix)
    cache=Path(spec['deployment'])/'TTS/hf-cache'
    os.environ.setdefault('HF_HOME',str(cache))
    os.environ.setdefault('HF_HUB_CACHE',str(cache/'hub'))
    os.environ['PATH']=str(Path(sys.prefix)/'bin')+os.pathsep+os.environ.get('PATH','')
    import mlx.core as mx
    import numpy as np
    random.seed(spec['seed']);np.random.seed(spec['seed']);mx.random.seed(spec['seed'])
    mx.set_cache_limit(8*1024**3)
    ADAPTERS[spec['profile_config']['runtime']](spec,args.output)


if __name__=='__main__':main()
