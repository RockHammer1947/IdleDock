"""Only this context launches provider commands; all use the same process guard."""
import os
from pathlib import Path
from .store import atomic_json
from .safety import DEFAULTS


class ExecutionContext:
    def __init__(self, path, request, resources):
        self.path = Path(path)
        self.out = self.path.parent
        self.spec = request['spec']
        self.request = request
        self.policy = {**DEFAULTS, **request.get('safety', {})}
        self.minimum = resources.get('min_available_gib', 0)
        self.policy['min_available_gib'] = max(self.policy['min_available_gib'], self.minimum)
        self.env = dict(os.environ)
        self.env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1')
        self.env['PATH'] = str(Path.home()/'.homebrew/bin')+':'+self.env.get('PATH', '')

    def run(self, command, name='render', cwd=None, max_seconds=None):
        from .guarded_run import run
        if (self.out/'STOP').exists():raise InterruptedError('Task stopped')
        atomic_json(self.out/(name+'.command.json'), command)
        result = run(command, cwd or self.out, self.out, name, self.policy, env=self.env,
                     max_seconds=max_seconds, smart_idle_minutes=self.request.get('smart_idle_minutes'),
                     min_available_gib=self.minimum)
        if (self.out/'STOP').exists():raise InterruptedError('Task stopped')
        if result['exit_code'] != 0 or result.get('aborted'):
            raise RuntimeError(f'{name} failed: {result}; see {name}.log')
        return result
