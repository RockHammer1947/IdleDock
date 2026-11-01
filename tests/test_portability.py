"""First-install checks do not read or alter the user's queue/deployment."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from h3queue.system_tools import find_tool, require_tool
from h3queue.store import ROOT, db, get, setv
from h3queue.cli import main


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='queue portable ')
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def executable(self, name):
        path = self.root/name
        path.write_text('#!/bin/sh\nprintf "chosen:%s\\n" "$1"\n')
        path.chmod(0o755)
        return path

    def test_explicit_tool_path_with_spaces_and_invalid_override(self):
        chosen = self.executable('custom ffmpeg')
        with patch.dict(os.environ, {'H3_QUEUE_FFMPEG': str(chosen)}):
            self.assertEqual(require_tool('ffmpeg'), str(chosen))
        with patch.dict(os.environ, {'H3_QUEUE_FFMPEG': str(self.root/'missing')}):
            self.assertIsNone(find_tool('ffmpeg'))
            with self.assertRaises(FileNotFoundError):require_tool('ffmpeg')

    def test_path_discovery_and_legacy_sensor(self):
        chosen = self.executable('ffprobe')
        base = self.root/'deployment'
        sensor = base/'H3/tools/macmon/macmon'
        sensor.parent.mkdir(parents=True)
        shutil.copyfile(chosen, sensor);sensor.chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(self.root)}, clear=True):
            self.assertEqual(find_tool('ffprobe'), str(chosen))
            self.assertEqual(find_tool('macmon', base), str(sensor))

    def launcher(self):
        root = self.root/'checkout with spaces'
        (root/'scripts').mkdir(parents=True)
        shutil.copyfile(ROOT/'queue', root/'queue')
        shutil.copyfile(ROOT/'scripts/python-path.sh', root/'scripts/python-path.sh')
        return root

    def test_python_override_wins_over_saved_path(self):
        root = self.launcher();(root/'.state').mkdir()
        (root/'.state/python-path').write_text('/missing/old/python')
        python = self.executable('selected python')
        result = subprocess.run(['/bin/zsh', '-f', str(root/'queue'), '--help'],
                                env={**os.environ, 'H3_QUEUE_PYTHON': str(python)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('chosen:-m', result.stdout)

    def test_invalid_saved_python_does_not_fall_back(self):
        root = self.launcher();(root/'.state').mkdir()
        (root/'.state/python-path').write_text('/missing/old/python')
        env = {k:v for k,v in os.environ.items() if k != 'H3_QUEUE_PYTHON'}
        result = subprocess.run(['/bin/zsh', '-f', str(root/'queue'), '--help'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('absolute Python', result.stderr)

    def test_init_reports_and_preserves_existing_mode(self):
        with patch.dict(os.environ, {'H3_QUEUE_HOME': str(self.root/'state')}):
            with db() as c:setv(c, 'mode', 'auto')
            with patch('h3queue.cli.ensure_worker'), contextlib.redirect_stdout(io.StringIO()) as output:
                main(['init'])
            self.assertEqual(json.loads(output.getvalue())['mode'], 'auto')
            with db() as c:self.assertEqual(get(c, 'mode'), 'auto')


if __name__ == '__main__':unittest.main()
