"""Exercise the source/privacy boundary in a temporary, independent Git repo."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_export', ROOT/'scripts/export-source.py')
source_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_export)


class SourceExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'source'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root/'.gitignore').write_text('.state/\n.build/\n')
        (self.root/'README.md').write_text('# Example\n')
        (self.root/'queue').write_text('#!/bin/sh\nexit 0\n')
        (self.root/'queue').chmod(0o755)
        (self.root/'.state').mkdir()
        (self.root/'.state/private.txt').write_text('private test record')
        self.output = Path(self.temp.name)/'export.zip'
        self.first = patch.object(source_export, 'ROOT', self.root)
        self.second = patch.object(source_export.public_source_check, 'ROOT', self.root)
        self.first.start(); self.second.start()
        self.addCleanup(self.first.stop); self.addCleanup(self.second.stop)

    def test_only_reviewed_sources_export_with_executable_modes_and_checksums(self):
        result = source_export.export_source(self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {'idledock/.gitignore', 'idledock/README.md', 'idledock/queue'})
            self.assertEqual(archive.getinfo('idledock/queue').external_attr >> 16 & 0o777, 0o755)
            self.assertEqual(archive.read('idledock/README.md'), b'# Example\n')
        manifest = json.loads(Path(result['manifest']).read_text())
        self.assertEqual(manifest['file_count'], 3)
        self.assertEqual(manifest['archive_sha256'], result['sha256'])
        self.assertEqual(Path(result['checksum']).read_text().split()[0], result['sha256'])
        self.assertNotIn(str(self.root), Path(result['manifest']).read_text())
        with self.assertRaises(FileExistsError):
            source_export.export_source(self.output)

    def test_forced_tracked_runtime_data_blocks_the_export(self):
        subprocess.run(['git', 'add', '-f', '.state/private.txt'], cwd=self.root, check=True)
        with self.assertRaisesRegex(ValueError, 'Public-source checks failed'):
            source_export.export_source(self.output)
        self.assertFalse(self.output.exists())

    def test_symlinks_are_not_followed_or_packaged(self):
        (self.root/'outside-link').symlink_to(self.root/'.state/private.txt')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            source_export.export_source(self.output)
        self.assertFalse(self.output.exists())
