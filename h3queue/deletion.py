"""Explicit terminal-job deletion; media and recovery records go to Trash."""
import json
import re
import time
import uuid
from pathlib import Path
from .store import db, home, event, atomic_json


def references_directory(value, directory):
    if isinstance(value, dict):
        return any(references_directory(v, directory) for v in value.values())
    if isinstance(value, list):
        return any(references_directory(v, directory) for v in value)
    return isinstance(value, str) and Path(value).is_absolute() and Path(value).resolve().is_relative_to(directory)


def delete_job(job_id, trash_root=None):
    if not re.fullmatch(r'[0-9a-f]{12}', job_id):
        raise ValueError('Invalid job ID')
    source = home().resolve() / 'runs' / job_id
    moved = False
    destination = None
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ValueError('Job not found')
            if row['status'] not in ('completed', 'failed', 'cancelled'):
                raise ValueError('Only finished jobs may be deleted; cancel active/queued work first')
            attempts = [dict(r) for r in c.execute('SELECT * FROM attempts WHERE job_id=?', (job_id,))]
            if any(a['status'] not in ('completed', 'failed', 'cancelled') for a in attempts):
                raise ValueError('Job still has an active attempt')
            if source.is_symlink():
                raise ValueError('Refusing symlinked job directory')
            paths = [a['directory'] for a in attempts] + ([row['output']] if row['output'] else [])
            if any(not Path(p).resolve().is_relative_to(source) for p in paths):
                raise ValueError('Job has external media; refusing to remove shared inputs')
            # A retry/recovery job may still refer to this attempt's files.
            for other in c.execute('SELECT id,spec,output FROM jobs WHERE id<>?', (job_id,)):
                if references_directory(json.loads(other['spec']), source) or references_directory(other['output'], source):
                    raise ValueError('Media is referenced by another job: ' + other['id'])
            trash = Path(trash_root) if trash_root is not None else Path.home() / '.Trash'
            destination = trash / ('H3Queue-' + job_id + '-' + uuid.uuid4().hex[:8])
            destination.mkdir(parents=True, exist_ok=False)
            cache = [dict(r) for r in c.execute('SELECT * FROM cache WHERE fingerprint=?', (row['fingerprint'],))]
            atomic_json(destination / 'record.json', {'deleted_at': time.time(), 'job': dict(row),
                'attempts': attempts, 'cache': cache, 'original_directory': str(source)})
            if source.exists():
                source.rename(destination / 'runs')
                moved = True
            c.execute('DELETE FROM cache WHERE fingerprint=?', (row['fingerprint'],))
            c.execute('DELETE FROM attempts WHERE job_id=?', (job_id,))
            c.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            event(c, 'deleted_to_trash', job_id, trash=str(destination), title=row['title'])
    except BaseException:
        if moved:
            (destination / 'runs').rename(source)
        raise
    return {'id': job_id, 'deleted': True, 'trash': str(destination)}
