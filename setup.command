#!/bin/zsh
set -eu
TASK_ROOT="${0:A:h}"
cd "$TASK_ROOT"
source "$TASK_ROOT/scripts/python-path.sh"
"$QUEUE_PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"; import psutil'
mkdir -p .state
print -r -- "$QUEUE_PYTHON" > .state/python-path
./scripts/build-app.sh
./queue init
open "$TASK_ROOT/dist/H3 Queue.app"
