"""Session hooks for a host WITHOUT a resident model service to stop/restore.

Copy this into your own deployment directory and review it before configuring
the queue. The queue owns .codex-inference.lock for command and TTS providers.
This template does NOT detect other GPU workloads and is NOT the legacy H3
CLI wrapper. Never replace an existing managed deployment's session with it.
"""


def service(action, profile=None, prefix_cache=False):
    if action == 'status':
        return {'running': False, 'state': None}
    raise RuntimeError('No resident service is configured in this template')


def ready(profile):
    raise RuntimeError('No resident service is configured in this template')


if __name__ == '__main__':
    raise SystemExit('This is a command/TTS session template, not an H3 wrapper. See docs/DEPLOYMENT.md.')
