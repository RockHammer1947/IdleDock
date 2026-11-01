"""Discover host tools without assuming one developer's Homebrew installation."""
import os
from pathlib import Path
import shutil


def find_tool(name, deployment=None):
    if name not in ('ffmpeg', 'ffprobe', 'macmon'):
        raise ValueError('Unsupported host tool: '+name)
    override = os.environ.get('H3_QUEUE_'+name.upper())
    if override:
        # An invalid explicit choice must not fall back to another executable.
        path = Path(override).expanduser()
        return str(path) if path.is_absolute() and path.is_file() and os.access(path, os.X_OK) else None
    candidates = []
    if name == 'macmon' and deployment:
        candidates.append(Path(deployment)/'H3/tools/macmon/macmon')
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    candidates.extend(base/name for base in (
        Path('/opt/homebrew/bin'), Path('/usr/local/bin'), Path.home()/'.homebrew/bin'))
    return next((str(p.absolute()) for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


def require_tool(name, deployment=None):
    found = find_tool(name, deployment)
    if not found:
        raise FileNotFoundError(f'{name} is unavailable; install it or set H3_QUEUE_{name.upper()} to its absolute executable path')
    return found
