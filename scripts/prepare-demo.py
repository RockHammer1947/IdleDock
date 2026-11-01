"""Write an isolated example configuration; never enqueue or start a worker."""
import argparse
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='New directory; must not already exist')
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    deployment = destination/'deployment'
    deployment.mkdir()
    shutil.copyfile(root/'examples/standalone-deployment/agent_session.py', deployment/'agent_session.py')
    runner = root/'examples/echo-provider/runner.py'
    manifest = {'protocol': 1, 'id': 'example-echo', 'label': 'Example echo', 'revision': '1',
                'argv': [sys.executable, str(runner), '--request', '{request}', '--output', '{output}'],
                'dependencies': [str(runner)], 'resources': {'device': 'cpu', 'min_available_gib': 0},
                'output': 'echo.json', 'output_kind': 'json'}
    (destination/'provider.json').write_text(json.dumps(manifest, indent=2))
    shutil.copyfile(root/'examples/echo-provider/request.json', destination/'request.json')
    print(json.dumps({'destination': str(destination), 'deployment': str(deployment), 'started': False}))


if __name__ == '__main__':
    main()
