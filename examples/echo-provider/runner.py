"""Tiny CPU-only protocol example. No models, downloads, or subprocesses."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.request.read_text())['spec']
    args.output.write_text(json.dumps({'received': spec['payload']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
