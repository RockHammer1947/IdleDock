"""Check the public source candidate set, not ignored local runtime data.

This is a focused hygiene/link check, not a complete secret scanner. Tracked
ignored files remain candidates, so accidentally committed state is detected.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.state', '.build', '.local', '.venv', '.codebase-memory', '__pycache__', 'dist'}
PRIVATE_FILES = {'AGENTS.local.md', 'AGENTS.override.md', 'CLAUDE.local.md', '.env'}
BINARY_SUFFIXES = {'.sqlite3', '.db', '.pyc', '.wav', '.mp3', '.mp4', '.safetensors', '.gguf', '.dmg', '.zip', '.gz'}


def candidates():
    data = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    return sorted({Path(p.decode()) for p in data.split(b'\0') if p})


def check():
    paths = candidates()
    public = set(paths)
    errors = []
    for relative in paths:
        path = ROOT/relative
        if (set(relative.parts) & PRIVATE_PARTS or relative.name in PRIVATE_FILES
                or (relative.name.startswith('.env.') and relative.name != '.env.example')
                or relative.suffix in BINARY_SUFFIXES):
            errors.append(f'{relative}: runtime/private/binary file in public candidate set')
            continue
        if not path.exists():
            errors.append(f'{relative}: missing tracked file; stage its deletion')
            continue
        if path.is_symlink():
            errors.append(f'{relative}: symlinks require manual release review')
            continue
        if path.stat().st_size > 1024*1024:
            errors.append(f'{relative}: unexpectedly large source file')
            continue
        # Reviewed UI screenshots are the only binary documentation assets.
        # Keep this exception scoped; model/media/runtime files still fail above.
        if relative.parent == Path('docs/images') and relative.suffix in ('.png', '.jpg'):
            data = path.read_bytes()
            valid = (data.startswith(b'\x89PNG\r\n\x1a\n') if relative.suffix == '.png'
                     else data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'))
            if not valid:
                errors.append(f'{relative}: invalid screenshot format')
            continue
        try:
            content = path.read_text()
        except UnicodeError:
            errors.append(f'{relative}: non-text source candidate')
            continue
        for label, pattern in (
            ('personal absolute path', r'/(?:Users|home)/[A-Za-z0-9._-]+/'),
            ('private key', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
            ('token-like value', r'\b(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_\-]{20,}'),
        ):
            if re.search(pattern, content):
                errors.append(f'{relative}: {label}; review without printing the value')
        if path.suffix == '.json':
            try:
                json.loads(content)
            except ValueError:
                errors.append(f'{relative}: invalid example JSON')
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]\n]+\]\(([^)\s]+)\)', content):
                link = urlsplit(target.strip('<>'))
                if link.scheme or link.netloc or not link.path:
                    continue
                resolved = (path.parent/unquote(link.path)).resolve()
                if not resolved.is_relative_to(ROOT) or resolved.relative_to(ROOT) not in public:
                    errors.append(f'{relative}: link is not in public source: {target}')
    return paths, errors


if __name__ == '__main__':
    files, failures = check()
    print(json.dumps({'checked_files': len(files), 'errors': failures}, ensure_ascii=False, indent=2))
    sys.exit(bool(failures))
