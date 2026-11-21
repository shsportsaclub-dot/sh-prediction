"""Explicit, verified database migration: backup -> verify backup -> migrate -> verify result.
Used by the admin 'Run migration' action and by tools/migrate.py. Never runs on a page load."""
import datetime
import os
import sqlite3
import tempfile

import schema

def _counts(c):
    names = [r[0] for r in sqlite3.Connection.execute(c, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {n: sqlite3.Connection.execute(c, 'SELECT COUNT(*) FROM "%s"' % n).fetchone()[0] for n in names}

def backup(c, db_path):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = os.path.dirname(os.path.abspath(db_path))
    fd, staging = tempfile.mkstemp(prefix=".backup-%s-" % ts, suffix=".sqlite3", dir=directory)
    os.close(fd)
    path = os.path.join(directory, os.path.basename(staging)[1:])
    try:
        c.commit()
        c.execute("BEGIN")
        try:
            # Counts and copied bytes must describe the same source read snapshot.
            before = _counts(c)
            dst = sqlite3.connect(staging)
            try:
                c.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                ok = [r[0] for r in dst.execute("PRAGMA integrity_check")] == ["ok"]
                same = _counts(dst) == before
            finally:
                dst.close()
        finally:
            c.rollback()  # End only the read transaction started above.
        if not (ok and same):
            raise RuntimeError("backup verification failed; migration not started")
        with open(staging, "rb") as saved:
            os.fsync(saved.fileno())
        # Publish a verified owner-only file without ever replacing backup history.
        os.link(staging, path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        os.remove(staging)
    return {"path": path, "integrity": "ok", "row_counts_match": True, "bytes": os.path.getsize(path)}

def run(c, db_path):
    todo = schema.pending(c)
    if not todo:
        return {"status": "up_to_date", "applied": []}
    before = _counts(c)
    lp_before = before.get(getattr(c, "lp", "legacy_predictions"), 0)
    b = backup(c, db_path)
    schema.migrate(c)
    after = _counts(c)
    checks = {
        "integrity": sqlite3.Connection.execute(c, "PRAGMA integrity_check").fetchone()[0],
        "foreign_keys": len(sqlite3.Connection.execute(c, "PRAGMA foreign_key_check").fetchall()),
        "legacy_fixtures_kept": after.get("fixtures", 0) == before.get("fixtures", 0),
        "legacy_predictions_kept": after.get("legacy_predictions", 0) == lp_before,
        "legacy_outcomes_kept": after.get("outcomes", 0) == before.get("outcomes", 0),
    }
    ok = checks["integrity"] == "ok" and checks["foreign_keys"] == 0 and all(v for k, v in checks.items() if k.endswith("_kept"))
    return {"status": "migrated" if ok else "migrated_with_warnings", "applied": todo, "backup": b, "checks": checks}

def backups(db_path):
    d = os.path.dirname(os.path.abspath(db_path))
    return sorted((f for f in os.listdir(d) if f.startswith("backup-") and f.endswith(".sqlite3")), reverse=True) if os.path.isdir(d) else []
