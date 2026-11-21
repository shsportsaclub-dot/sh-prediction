import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'storage_copy.py'


class StorageCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.sqlite3'
        self.target = self.root / 'target.sqlite3'
        self.writer = sqlite3.connect(self.source)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('PRAGMA wal_autocheckpoint=0')
        self.writer.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, payload TEXT)')
        self.writer.execute("INSERT INTO events VALUES(1,'verified event')")
        self.writer.commit()

    def module(self):
        spec = importlib.util.spec_from_file_location('storage_copy', TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_copies_wal_and_reopens_independently(self):
        result = self.module().copy_database(self.source, self.target)
        self.assertEqual(result['row_counts'], {'events': 1})
        self.assertEqual(result['integrity'], 'ok')
        self.assertFalse(result['production_cutover_verified'])
        self.assertEqual(os.stat(self.target).st_mode & 0o777, 0o600)
        output = subprocess.check_output([sys.executable, '-c',
            'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("SELECT payload FROM events").fetchone()[0])', str(self.target)], text=True)
        self.assertEqual(output.strip(), 'verified event')
        self.assertEqual(len(result['sha256']), 64)
        self.assertEqual(list(self.root.glob('.sh-storage-*')), [])

    def test_never_overwrites_destination(self):
        self.target.write_bytes(b'keep existing database')
        with self.assertRaises(FileExistsError):
            self.module().copy_database(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'keep existing database')

    def test_refuses_source_or_destination_sidecars(self):
        mod = self.module()
        with self.assertRaises(FileExistsError): mod.copy_database(self.source, self.source)
        Path(str(self.target) + '-wal').write_bytes(b'active')
        with self.assertRaises(FileExistsError): mod.copy_database(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_missing_source_is_not_created(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(FileNotFoundError): self.module().copy_database(missing, self.target)
        self.assertFalse(missing.exists())
        self.assertFalse(self.target.exists())

    def test_rejects_unmounted_or_outside_destination(self):
        mod = self.module()
        with self.assertRaises(ValueError): mod.copy_database(self.source, self.target, mount_root=self.root)
        (self.root / 'disk').mkdir()
        with patch.object(mod.os.path, 'ismount', return_value=True):
            with self.assertRaises(ValueError): mod.copy_database(self.source, self.target, mount_root=self.root / 'disk')
        self.assertFalse(self.target.exists())

    def test_counts_and_backup_use_same_snapshot_during_writes(self):
        mod = self.module()
        original = mod._counts
        wrote = False

        def counts(c):
            nonlocal wrote
            result = original(c)
            if not wrote:
                wrote = True
                self.writer.execute("INSERT INTO events VALUES(2,'later event')")
                self.writer.commit()
            return result

        with patch.object(mod, '_counts', side_effect=counts):
            result = mod.copy_database(self.source, self.target)
        self.assertEqual(result['row_counts'], {'events': 1})
        self.assertEqual(self.writer.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2)

    def test_corrupt_source_leaves_no_destination_or_staging_file(self):
        bad = self.root / 'bad.sqlite3'; bad.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError): self.module().copy_database(bad, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.sh-storage-*')), [])
