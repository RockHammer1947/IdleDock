# Sourced by POSIX shell and zsh launchers. TASK_ROOT must be the checkout's absolute path.
# Keep an explicitly selected interpreter; never silently switch after setup.
if [ -n "${H3_QUEUE_PYTHON:-}" ]; then
  QUEUE_PYTHON="$H3_QUEUE_PYTHON"
elif [ -f "$TASK_ROOT/.state/python-path" ]; then
  QUEUE_PYTHON="$(cat "$TASK_ROOT/.state/python-path")"
elif [ -x "$TASK_ROOT/.venv/bin/python" ]; then
  QUEUE_PYTHON="$TASK_ROOT/.venv/bin/python"
elif [ -x "$HOME/coding/base-local-modal/Qwen3.8/.venv/bin/python" ]; then
  # Compatibility for installations created before the standalone environment.
  QUEUE_PYTHON="$HOME/coding/base-local-modal/Qwen3.8/.venv/bin/python"
else
  QUEUE_PYTHON="$(command -v python3)"
fi
case "$QUEUE_PYTHON" in /*) ;; *) QUEUE_PYTHON="" ;; esac
if [ ! -x "$QUEUE_PYTHON" ]; then
  printf '%s\n' >&2 'Set H3_QUEUE_PYTHON to an absolute Python 3.10+ executable path.'
  exit 1
fi
