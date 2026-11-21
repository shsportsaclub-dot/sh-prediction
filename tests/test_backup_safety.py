import datetime
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import system


class BackupSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'production.sqlite3')
        self.c = sqlite3.connect(self.path)
        self.addCleanup(self.c.close)
        self.c.execute('PRAGMA journal_mode=WAL')
        self.c.execute('CREATE TABLE events(value TEXT)')
        self.c.execute("INSERT INTO events VALUES('first')")
        self.c.commit()

    def test_same_second_backups_never_replace_history(self):
        fixed = datetime.datetime(2026, 11, 21, tzinfo=datetime.timezone.utc)
        with patch.object(system.datetime, 'datetime') as clock:
            clock.now.return_value = fixed
            first = system.backup(self.c, self.path)
            self.c.execute("INSERT INTO events VALUES('second')")
            self.c.commit()
            second = system.backup(self.c, self.path)
        self.assertNotEqual(first['path'], second['path'])
        with sqlite3.connect(first['path']) as restored:
            self.assertEqual(restored.execute('SELECT value FROM events').fetchall(), [('first',)])
        self.assertEqual(len(system.backups(self.path)), 2)

    def test_backup_is_owner_only(self):
        result = system.backup(self.c, self.path)
        self.assertEqual(os.stat(result['path']).st_mode & 0o777, 0o600)

    def test_counts_are_pinned_to_backup_snapshot(self):
        original = system._counts
        wrote = False
        def counts(c):
            nonlocal wrote
            result = original(c)
            if not wrote:
                wrote = True
                with sqlite3.connect(self.path) as other:
                    other.execute("INSERT INTO events VALUES('later')")
            return result
        with patch.object(system, '_counts', side_effect=counts):
            result = system.backup(self.c, self.path)
        self.assertTrue(result['row_counts_match'])
        with sqlite3.connect(result['path']) as restored:
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2)

    def test_failed_backup_leaves_no_partial_recovery_file(self):
        class BrokenBackup(sqlite3.Connection):
            def backup(self, *args, **kwargs):
                raise sqlite3.OperationalError('simulated backup failure')
        broken = sqlite3.connect(self.path, factory=BrokenBackup)
        try:
            with self.assertRaises(sqlite3.OperationalError): system.backup(broken, self.path)
        finally:
            broken.close()
        self.assertEqual(system.backups(self.path), [])
