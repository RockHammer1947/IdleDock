"""Provider selection is configuration, never executable code supplied by a job.

Built-ins implement normalize/resources/describe/run. Additional local adapters
use the versioned command manifest protocol without modifying the scheduler.
"""
import re
from pathlib import Path
from ..store import home


def provider_id(spec):
    value = spec.get('provider', 'h3')
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value):
        raise ValueError('Invalid provider ID')
    return value


def resolve(spec):
    name = provider_id(spec)
    if name == 'h3':
        from .h3 import H3Provider
        return H3Provider()
    if name == 'tts':
        from .tts import TTSProvider
        return TTSProvider()
    from .command import CommandProvider
    return CommandProvider(name)


def catalog(deployment):
    from .tts import profiles
    result = [{'id': 'h3', 'label': 'H3 视频', 'kind': 'video', 'device': 'gpu',
               'profiles': ['native20', 'lightx3']},
              {'id': 'tts', 'label': '本地配音', 'kind': 'audio', 'device': 'gpu',
               'profiles': profiles(deployment)}]
    for path in sorted((home()/'providers').glob('*.json')):
        try:
            provider = resolve({'provider': path.stem})
            manifest = provider.manifest()
            result.append({'id': path.stem, 'label': manifest['label'], 'kind': manifest['output_kind'],
                           'device': manifest['resources']['device'], 'revision': manifest['revision']})
        except (ValueError, OSError) as exc:
            result.append({'id': path.stem, 'error': str(exc)})
    return result
