"""Concurrent requests must safely initialize an existing legacy database."""
import concurrent.futures
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
import main


class LegacyInitialization(unittest.TestCase):
    def test_simultaneous_first_requests_add_columns_once(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'legacy.sqlite3')
            with sqlite3.connect(path) as c:
                c.execute('CREATE TABLE outcomes(fixture_id INTEGER PRIMARY KEY, toss_winner TEXT, match_winner TEXT, source TEXT NOT NULL, verified_at TEXT NOT NULL)')
            barrier = threading.Barrier(2)
            original = main.LegacyConn.execute
            local = threading.local()

            def execute(c, sql, *args):
                result = original(c, sql, *args)
                if sql == 'PRAGMA table_info(outcomes)' and not getattr(local, 'observed', False):
                    # Both connections see the same pre-upgrade schema before either ALTER.
                    rows = list(result)
                    local.observed = True
                    barrier.wait(timeout=10)
                    return rows
                return result

            def connect():
                c = main.db()
                try:
                    return {r[1] for r in c.execute('PRAGMA table_info(outcomes)')}
                finally:
                    c.close()

            with patch.object(main, 'DB', path), patch.object(main.LegacyConn, 'execute', execute):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    columns = list(pool.map(lambda _: connect(), range(2)))
            for cols in columns:
                self.assertTrue({'status', 'toss_decision', 'remarks'} <= cols)
