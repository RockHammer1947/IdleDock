import json
from pathlib import Path
from .store import digest


class DeploymentChanged(ValueError):
    pass


def validate_inputs(spec):
    for key in ('engine', 'portrait', 'audio', 'reference_audio'):
        if key in spec and digest(spec[key]) != spec[key + '_sha256']:
            raise DeploymentChanged(f'{key} changed since enqueue: {spec[key]}')
    for asset in spec.get('input_assets',{}).values():
        if digest(asset['path'])!=asset['sha256']:raise DeploymentChanged('Input asset changed: '+asset['path'])
    if spec.get('provider')=='tts':
        from .providers.tts import model_inventory
        if model_inventory(spec['model_path'])!=spec['model_inventory']:
            raise DeploymentChanged('TTS model files changed; enqueue a new request')


def validate_spec(spec):
    validate_inputs(spec)
    for path, sha in spec['deployment_pins']:
        if digest(path) != sha:
            raise DeploymentChanged(f'Deployment changed: {path}; review then retry --refresh-deployment')
    if spec.get('provider')=='tts':
        profiles=json.loads((Path(spec['deployment'])/'TTS/profiles.json').read_text())
        if profiles.get(spec['profile'])!=spec['profile_config']:
            raise DeploymentChanged('Selected TTS profile changed; enqueue a new request')
