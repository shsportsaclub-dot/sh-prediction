"""Explicit, verified database migration: backup -> verify backup -> migrate -> verify result.
Used by the admin 'Run migration' action and by tools/migrate.py. Never runs on a page load."""
import datetime
import os
import sqlite3

import schema

def _counts(c):
    names = [r[0] for r in sqlite3.Connection.execute(c, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {n: sqlite3.Connection.execute(c, 'SELECT COUNT(*) FROM "%s"' % n).fetchone()[0] for n in names}

def backup(c, db_path):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backup-%s.sqlite3" % ts)
    dst = sqlite3.connect(path)
    try:
        c.commit()
        c.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        same = _counts(dst) == _counts(c)
    finally:
        dst.close()
    if not (ok and same):
        os.remove(path)
        raise RuntimeError("backup verification failed; migration not started")
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
