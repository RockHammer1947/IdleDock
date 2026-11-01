import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from h3queue.store import db
from h3queue.deletion import delete_job


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'H3_QUEUE_HOME': str(self.root / 'state')})
        self.env.start()
        self.jid = '0123456789ab'
        self.source = self.root / 'state/runs' / self.jid
        self.attempt = self.source / 'attempt'
        self.attempt.mkdir(parents=True)
        (self.attempt / 'video.mp4').write_bytes(b'old-video')
        with db() as c:
            c.execute("INSERT INTO jobs(id,fingerprint,title,spec,status,created,updated,output) VALUES(?,?,?,?,?,?,?,?)",
                (self.jid, 'fingerprint', 'old', '{}', 'completed', 1, 1, str(self.attempt / 'video.mp4')))
            c.execute('INSERT INTO attempts(id,job_id,started,finished,status,directory) VALUES(?,?,?,?,?,?)',
                ('attempt', self.jid, 1, 2, 'completed', str(self.attempt)))
            c.execute('INSERT INTO cache VALUES(?,?,?,?)', ('fingerprint', str(self.attempt / 'video.mp4'), 'sha', 1))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_delete_moves_media_invalidates_cache_and_preserves_audit(self):
        result = delete_job(self.jid, self.root / 'Trash')
        self.assertFalse(self.source.exists())
        self.assertEqual((Path(result['trash']) / 'runs/attempt/video.mp4').read_bytes(), b'old-video')
        self.assertEqual(json.loads((Path(result['trash']) / 'record.json').read_text())['job']['id'], self.jid)
        with db() as c:
            for table in ('jobs', 'attempts', 'cache'):
                self.assertEqual(c.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT kind FROM events').fetchone()[0], 'deleted_to_trash')

    def test_active_job_is_untouched(self):
        with db() as c:
            c.execute("UPDATE jobs SET status='running'")
        with self.assertRaises(ValueError):
            delete_job(self.jid, self.root / 'Trash')
        self.assertTrue((self.attempt / 'video.mp4').exists())

    def test_shared_media_is_untouched(self):
        with db() as c:
            c.execute('INSERT INTO jobs(id,fingerprint,title,spec,created,updated) VALUES(?,?,?,?,?,?)',
                ('aaaaaaaaaaaa', 'new-key', 'new', json.dumps({'audio': str(self.attempt / 'video.mp4')}), 1, 1))
        with self.assertRaises(ValueError):
            delete_job(self.jid, self.root / 'Trash')
        self.assertTrue(self.source.exists())

    def test_database_error_restores_media_and_rows(self):
        with patch('h3queue.deletion.event', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):
                delete_job(self.jid, self.root / 'Trash')
        self.assertTrue((self.attempt / 'video.mp4').exists())
        with db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM cache').fetchone()[0], 1)
