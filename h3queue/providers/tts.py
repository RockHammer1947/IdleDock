"""Batch TTS over existing local deployments; model imports happen only in the runner."""
import json
import math
from pathlib import Path
from ..store import digest, atomic_json
from ..artifacts import audio_metadata, verify

RUNTIMES = {'mlx-audio', 'mlx-audio-plus', 'indextts', 'auk'}
RUNNER = Path(__file__).resolve().parents[1]/'tts_runner.py'


def profiles(deployment):
    path = Path(deployment)/'TTS/profiles.json'
    if not path.is_file():return []
    data = json.loads(path.read_text())
    return [{'id': key, 'family': value.get('family'), 'runtime': value.get('runtime'),
             'configured': value.get('runtime') in RUNTIMES,
             'files_present': (path.parent/value.get('model_path', '')).is_dir() and Path(value.get('python', '')).is_file(),
             'reference_required': bool(value.get('reference')), 'languages': value.get('languages', [])}
            for key, value in sorted(data.items())]


def model_inventory(path):
    """Metadata identity, not a claim to hash all multi-GB model weights."""
    root = Path(path)
    rows = []
    for item in sorted(root.rglob('*')):
        relative = item.relative_to(root)
        if any(part.startswith('.') for part in relative.parts) or not item.is_file():continue
        stat = item.stat()
        rows.append([str(relative), str(item.resolve()), stat.st_size, stat.st_mtime_ns])
    if not rows:raise ValueError('Local model directory is empty: '+str(root))
    return rows


class TTSProvider:
    id = 'tts'
    label = '本地配音'
    output_kind = 'audio'

    def normalize(self, raw, deployment):
        base = Path(deployment).resolve()
        profile_id = raw.get('profile')
        configs = json.loads((base/'TTS/profiles.json').read_text())
        if profile_id not in configs:raise ValueError('Unknown TTS profile; run queue providers')
        config = configs[profile_id]
        if config.get('runtime') not in RUNTIMES:raise ValueError('Unsupported TTS runtime')
        text = raw.get('text', '')
        if not isinstance(text, str) or not text.strip() or len(text)>20000:
            raise ValueError('TTS text must contain 1–20000 characters; split long scripts into jobs')
        language = raw.get('language', 'zh')
        if language not in config.get('languages', []):raise ValueError('Unsupported TTS language')
        python = Path(config['python']).expanduser().absolute()
        model = (base/'TTS'/config['model_path']).resolve()
        if not python.is_file() or not model.is_dir():raise ValueError('TTS runtime/model is not installed locally')
        options = raw.get('options', {})
        if not isinstance(options, dict):raise ValueError('options must be a JSON object')
        if set(options) & {'text','ref_audio','ref_text','stream','model','model_path','output','output_path','audio_path'}:
            raise ValueError('Use the dedicated input fields; options cannot override inputs/output/model')
        json.dumps(options, allow_nan=False)
        runtime=config['runtime']
        if runtime=='indextts' and set(options)-{'diffusion_steps','use_gpt_latent','temperature','emotion'}:
            raise ValueError('IndexTTS options support diffusion_steps/use_gpt_latent/temperature/emotion')
        if runtime=='auk':
            if set(options)-{'gen_seconds','nfe'}:raise ValueError('AuK options support gen_seconds/nfe')
            if len(text)/(4.2 if language=='zh' else 13)+1.5>45:
                raise ValueError('Split this AuK paragraph: its estimated speech length exceeds 45 seconds')
            seconds=options.get('gen_seconds',5);steps=options.get('nfe',4)
            if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 1<=seconds<=45:
                raise ValueError('AuK gen_seconds must be 1–45')
            if isinstance(steps,bool) or not isinstance(steps,int) or not 1<=steps<=200:
                raise ValueError('AuK nfe must be an integer 1–200')
        seed = int(raw.get('seed', 42))
        if not 0<=seed<2**32:raise ValueError('seed must fit uint32')
        result = {'provider': 'tts', 'schema_version': 1, 'profile': profile_id, 'deployment': str(base),
                  'text': text, 'language': language, 'seed': seed, 'options': options,
                  'profile_config': config, 'python': str(python), 'model_path': str(model),
                  'model_inventory': model_inventory(model)}
        if config.get('reference'):
            if not raw.get('reference_audio'):raise ValueError('This TTS profile requires reference_audio')
            reference = Path(raw['reference_audio']).expanduser().resolve()
            metadata = audio_metadata(reference)
            if metadata['audio_seconds']>60:raise ValueError('Reference audio must be at most 60 seconds')
            transcript = raw.get('reference_text', '')
            if not isinstance(transcript,str) or len(transcript)>20000:raise ValueError('Invalid reference_text')
            if profile_id in ('qwen-base','ming','fish-drama3') and not transcript.strip():
                raise ValueError('This profile requires an exact reference_text transcript')
            result.update(reference_audio=str(reference), reference_audio_sha256=digest(reference), reference_text=transcript)
        elif raw.get('reference_audio') or raw.get('reference_text'):
            raise ValueError('Selected profile does not support reference audio')
        # Pin only the selected config (not unrelated profiles) plus runner/session.
        pins=[RUNNER,base/'agent_session.py']
        venv=python.parent.parent
        if (venv/'pyvenv.cfg').exists():pins.append(venv/'pyvenv.cfg')
        for pattern in ('mlx*','auk*','torch*','soundfile*'):
            pins.extend(venv.glob('lib/python*/site-packages/'+pattern+'.dist-info/METADATA'))
            pins.extend(venv.glob('lib/python*/site-packages/'+pattern+'.dist-info/direct_url.json'))
        result['deployment_pins'] = [[str(p), digest(p)] for p in sorted(set(pins))]
        return result

    def resources(self, spec):return {'device': 'gpu', 'min_available_gib': 0}

    def describe(self, spec):
        return {'provider': self.id, 'provider_label': self.label, 'output_kind': 'audio',
                'profile': spec['profile'], 'width': None, 'height': None, 'seconds': None,
                'summary': f"{len(spec['text'])} 字符 · {spec['language']} · {spec['profile']}"}

    def run(self, context):
        output = context.out/'audio.wav'
        result = context.run([context.spec['python'], str(RUNNER), '--request', str(context.path), '--output', str(output)],
                             cwd=Path(context.spec['deployment'])/'TTS')
        artifact = verify(context, output, 'audio')
        artifact.update(elapsed=result['elapsed_s'], chip_power_mean_w=result.get('chip_power_mean_w'))
        return artifact
