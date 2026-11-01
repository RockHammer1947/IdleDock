"""Registered command protocol v1 for additional local compute providers.

Registration is a trusted code-install operation. Jobs supply JSON payload and
hashed assets, never an executable, shell fragment, or output path.
"""
import json
import math
from pathlib import Path
from ..store import home, digest, atomic_json
from ..artifacts import verify

TOKENS={'{request}','{output}','{workdir}'}


def validate_manifest(raw):
    from . import provider_id
    name=provider_id({'provider':raw.get('id')})
    if name in ('h3','tts'):raise ValueError('Built-in provider IDs are reserved')
    if raw.get('protocol')!=1:raise ValueError('Unsupported command protocol version')
    if not isinstance(raw.get('revision'),str) or not raw['revision'].strip():raise ValueError('revision is required')
    if not isinstance(raw.get('label'),str) or not raw['label'].strip():raise ValueError('label is required')
    argv=raw.get('argv')
    if not isinstance(argv,list) or not argv or not all(isinstance(v,str) and v and '\x00' not in v for v in argv):
        raise ValueError('argv must be a nonempty string array')
    if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():raise ValueError('argv[0] must be an installed absolute executable')
    if '{request}' not in argv or '{output}' not in argv:raise ValueError('argv must include separate {request} and {output} arguments')
    for value in argv:
        if ('{' in value or '}' in value) and value not in TOKENS:raise ValueError('Only whole-argument protocol tokens are supported')
    filename=raw.get('output','')
    if not filename or Path(filename).name!=filename or filename in ('.','..','request.json','verified.json','receipt.json','STOP'):
        raise ValueError('output must be a dedicated filename')
    if raw.get('output_kind') not in ('audio','video','json','file'):raise ValueError('output_kind must be audio/video/json/file')
    resources=raw.get('resources',{})
    if resources.get('device') not in ('gpu','cpu'):raise ValueError('resources.device must be gpu or cpu')
    minimum=resources.get('min_available_gib',0)
    if isinstance(minimum,bool) or not isinstance(minimum,(int,float)) or not math.isfinite(minimum) or not 0<=minimum<=64:
        raise ValueError('Invalid min_available_gib')
    dependencies=raw.get('dependencies',[])
    if not isinstance(dependencies,list) or not all(isinstance(v,str) and Path(v).is_absolute() and Path(v).is_file() for v in dependencies):
        raise ValueError('dependencies must list existing absolute files')
    json.dumps(raw,allow_nan=False)
    return {**raw,'resources':{'device':resources['device'],'min_available_gib':minimum},'dependencies':dependencies}


def register(path, replace=False):
    manifest=validate_manifest(json.loads(Path(path).read_text()))
    target=home()/'providers'/(manifest['id']+'.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and not replace:raise ValueError('Provider exists; use --replace after reviewing changes')
    atomic_json(target,manifest)
    return {'registered':manifest['id'],'path':str(target),'note':'Registration does not start computation'}


class CommandProvider:
    def __init__(self,name):self.id=name

    def manifest(self):
        path=home()/'providers'/(self.id+'.json')
        if not path.is_file():raise ValueError('Unknown provider: '+self.id)
        manifest=validate_manifest(json.loads(path.read_text()))
        if manifest['id']!=self.id:raise ValueError('Provider manifest ID mismatch')
        return manifest

    def normalize(self,raw,deployment):
        manifest=self.manifest()
        payload=raw.get('payload',{})
        if not isinstance(payload,dict):raise ValueError('payload must be an object')
        json.dumps(payload,allow_nan=False)
        assets=raw.get('assets',{})
        if not isinstance(assets,dict):raise ValueError('assets must be an object of absolute file paths')
        inputs={}
        for key,value in assets.items():
            if not isinstance(value,str) or not Path(value).is_absolute():raise ValueError('assets require absolute file paths')
            path=Path(value).resolve();inputs[key]={'path':str(path),'sha256':digest(path)}
        target=home()/'providers'/(self.id+'.json')
        dependencies={str(target),*manifest['dependencies']}
        dependencies.update(arg for arg in manifest['argv'] if Path(arg).is_absolute() and Path(arg).is_file())
        dependencies.add(str(Path(deployment)/'agent_session.py'))
        return {'provider':self.id,'schema_version':1,'profile':str(raw.get('profile','default')),
                'deployment':str(Path(deployment).resolve()),'payload':payload,'assets':{k:v['path'] for k,v in inputs.items()},
                'input_assets':inputs,'manifest':manifest,
                'deployment_pins':[[p,digest(p)] for p in sorted(dependencies)]}

    def resources(self,spec):return spec['manifest']['resources']

    def describe(self,spec):
        return {'provider':self.id,'provider_label':spec['manifest']['label'],'output_kind':spec['manifest']['output_kind'],
                'profile':spec['profile'],'width':None,'height':None,'seconds':None,
                'summary':spec['manifest']['label']+' · '+spec['profile']}

    def run(self,context):
        manifest=context.spec['manifest'];output=context.out/'artifacts'/manifest['output']
        output.parent.mkdir(exist_ok=True)
        tokens={'{request}':str(context.path),'{output}':str(output),'{workdir}':str(context.out)}
        command=[tokens.get(arg,arg) for arg in manifest['argv']]
        result=context.run(command)
        artifact=verify(context,output,manifest['output_kind'])
        artifact.update(elapsed=result['elapsed_s'],chip_power_mean_w=result.get('chip_power_mean_w'))
        return artifact
