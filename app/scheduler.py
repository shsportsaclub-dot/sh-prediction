"""Server-side collectors: run 24/7 on the backend, no app or APK needs to be open.

Jobs live in the collector_jobs table (interval, enabled, config). A failing job retries with backoff
(5, 10, 20... minutes, never longer than its normal interval) and every run is written to collector_log.
"""
import datetime
import json
import os
import threading
import time
import traceback

import cricketdata
import cricsheet
import gsheets
from schema import now

WHO = {"actor": "data-bridge", "role": "admin", "user_id": None}
_lock = threading.Lock()
_started = False


def _ts(dt):
    return dt.isoformat()


def _now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def _helpers(conn):
    import api_v1

    def create_match(row):
        return api_v1.admin_match(conn, WHO, row)

    def record_result(d):
        try:
            return api_v1.admin_result(conn, WHO, d)
        except api_v1.ApiError as e:
            return {"status": "rejected", "error": e.message if hasattr(e, "message") else str(e)}
    return create_match, record_result


# ------------------------------------------------------------------ jobs
def job_owner_sheets_sync(conn, cfg, opener):
    leagues = json.loads((conn.execute("SELECT value FROM system_settings WHERE key='owner_sheets'").fetchone() or ["[]"])[0])
    create_match, record_result = _helpers(conn)
    out, errors = {}, []
    for lg in leagues:
        try:
            x = gsheets.fetch_xlsx(lg["sheet_id"], opener)
            out[lg["league"]] = gsheets.sync_league(conn, lg, x, create_match, record_result, now)
            conn.commit()
        except Exception as e:
            conn.rollback()
            errors.append("%s: %s" % (lg["league"], e))
    if errors and not out:
        raise RuntimeError("; ".join(errors))
    return {"leagues": out, "errors": errors}


def job_registry_index_sync(conn, cfg, opener):
    x = gsheets.fetch_xlsx(cfg["sheet_id"], opener)
    k = gsheets.sync_index_registry(conn, x, now)
    conn.commit()
    return k


def job_cricketdata_matches(conn, cfg, opener):
    if not cricketdata.key():
        return {"skipped": "CRICKETDATA_API_KEY is not set on the server"}
    create_match, record_result = _helpers(conn)
    k = cricketdata.sync(conn, "matches", cfg.get("daily_budget", 60), create_match, record_result, now, opener)
    conn.commit()
    return k


def job_cricketdata_live(conn, cfg, opener):
    if not cricketdata.key():
        return {"skipped": "CRICKETDATA_API_KEY is not set on the server"}
    soon = _ts(_now_dt() + datetime.timedelta(hours=1))
    recent = _ts(_now_dt() - datetime.timedelta(hours=10))
    n = conn.execute("""SELECT COUNT(*) FROM matches m JOIN data_provider_syncs s ON s.local_id=m.id AND s.provider='cricketdata' AND s.provider_entity='match'
                        WHERE m.status='live' OR (m.status='scheduled' AND m.start_utc BETWEEN ? AND ?)""", (recent, soon)).fetchone()[0]
    if not n:
        return {"skipped": "no CricketData match is live or starting within the hour; no hit spent"}
    create_match, record_result = _helpers(conn)
    k = cricketdata.sync(conn, "currentMatches", cfg.get("daily_budget", 60), create_match, record_result, now, opener)
    conn.commit()
    return k


def _cricsheet_file(db_fn, fname, opener):
    import api_v1
    factory = lambda c: (lambda row: api_v1.admin_match(c, {"actor": "cricsheet-import", "role": "admin", "user_id": None}, row))
    for _ in range(600):   # wait if an admin-started import is still running
        try:
            info, t = cricsheet.start_job(db_fn, fname, factory, opener=opener)
            break
        except RuntimeError:
            time.sleep(1)
    else:
        raise RuntimeError("another Cricsheet import kept running")
    t.join()
    c = db_fn()
    try:
        r = c.execute("SELECT status, created, duplicates, rejected, error FROM data_sync_runs WHERE id=?", (info["run_id"],)).fetchone()
    finally:
        c.close()
    if r[0] != "ok":
        raise RuntimeError("%s: %s" % (fname, r[4]))
    return {"file": fname, "created": r[1], "duplicates": r[2], "rejected": r[3], "note": r[4]}


def job_cricsheet_recent(conn, cfg, opener, db_fn):
    return {"files": [_cricsheet_file(db_fn, f, opener) for f in cfg.get("files", [])]}


def job_cricsheet_backfill(conn, cfg, opener, db_fn):
    """One Cricsheet file per run: priority leagues first, then every other file on the official downloads page."""
    if not cfg.get("catalogue") or cfg.get("catalogue_at", "") < _ts(_now_dt() - datetime.timedelta(days=7)):
        cfg["catalogue"] = cricsheet.discover(opener) if opener else cricsheet.discover()
        cfg["catalogue_at"] = now()
    order = [f for f in cfg.get("priority", []) if f in cfg["catalogue"]] + [f for f in cfg["catalogue"] if f not in cfg.get("priority", [])]
    todo = [f for f in order if f not in cfg.get("done", []) and f not in cfg.get("skip", []) and not f.startswith("recently_added")]
    if not todo:
        return {"status": "all %d catalogue files imported; recent files keep them current" % len(cfg.get("done", [])), "_cfg": cfg}
    r = _cricsheet_file(db_fn, todo[0], opener)
    cfg.setdefault("done", []).append(todo[0])
    r["remaining_files"] = len(todo) - 1
    r["_cfg"] = cfg
    return r


JOBS = {"owner_sheets_sync": job_owner_sheets_sync, "registry_index_sync": job_registry_index_sync,
        "cricketdata_matches": job_cricketdata_matches, "cricketdata_live": job_cricketdata_live,
        "cricsheet_recent": job_cricsheet_recent, "cricsheet_backfill": job_cricsheet_backfill}
NEEDS_DB_FN = {"cricsheet_recent", "cricsheet_backfill"}


def run_job(db_fn, name, opener=None, force=False):
    """Run one job now (used by the loop and by the admin 'Run now' button). Returns the log row."""
    conn = db_fn()
    try:
        j = conn.execute("SELECT * FROM collector_jobs WHERE name=?", (name,)).fetchone()
        if not j:
            raise KeyError(name)
        if j["running"] and not force:
            return {"status": "already running"}
        conn.execute("UPDATE collector_jobs SET running=1 WHERE name=?", (name,))
        conn.execute("INSERT INTO collector_log(job,started_at,status) VALUES(?,?,'running')", (name, now()))
        log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        cfg = json.loads(j["config_json"] or "{}")
        try:
            fn = JOBS[name]
            res = fn(conn, cfg, opener, db_fn) if name in NEEDS_DB_FN else fn(conn, cfg, opener)
            status, err = ("skipped" if isinstance(res, dict) and "skipped" in res else "ok"), None
        except Exception as e:
            conn.rollback()
            res, status, err = None, "failed", "%s" % e
            if os.getenv("SH_DEBUG"):
                traceback.print_exc()
        newcfg = res.pop("_cfg", None) if isinstance(res, dict) else None
        fails = 0 if status != "failed" else j["consecutive_failures"] + 1
        delay = j["interval_minutes"] if status != "failed" else min(j["interval_minutes"], 5 * 2 ** (fails - 1))
        conn.execute("""UPDATE collector_jobs SET running=0, last_run_at=?, next_run_at=?, last_status=?, last_error=?, runs=runs+1,
                        failures=failures+?, consecutive_failures=?, config_json=COALESCE(?,config_json) WHERE name=?""",
                     (now(), _ts(_now_dt() + datetime.timedelta(minutes=delay)), status, err, 1 if status == "failed" else 0, fails,
                      json.dumps(newcfg) if newcfg is not None else None, name))
        conn.execute("UPDATE collector_log SET finished_at=?, status=?, summary=?, error=? WHERE id=?",
                     (now(), status, json.dumps(res, default=str)[:4000] if res is not None else None, err, log_id))
        conn.execute("DELETE FROM collector_log WHERE job=? AND id < (SELECT MAX(id) - 200 FROM collector_log WHERE job=?)", (name, name))
        conn.commit()
        return {"job": name, "status": status, "summary": res, "error": err}
    finally:
        conn.close()


def due(db_fn):
    c = db_fn()
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='collector_jobs'").fetchone():
            return []
        # a job marked running for more than 3 hours was interrupted by a restart
        c.execute("UPDATE collector_jobs SET running=0 WHERE running=1 AND last_run_at < ?", (_ts(_now_dt() - datetime.timedelta(hours=3)),))
        c.commit()
        return [r[0] for r in c.execute("SELECT name FROM collector_jobs WHERE enabled=1 AND running=0 AND (next_run_at IS NULL OR next_run_at<=?) ORDER BY next_run_at",
                                         (now(),))]
    finally:
        c.close()


def loop(db_fn, tick=60):
    while True:
        try:
            for name in due(db_fn):
                run_job(db_fn, name)
        except Exception:
            traceback.print_exc()
        time.sleep(tick)


def start(db_fn):
    """Start the collector loop once per process (disabled with SH_COLLECTORS=0, e.g. in tests)."""
    global _started
    with _lock:
        if _started or os.getenv("SH_COLLECTORS", "1") == "0":
            return False
        _started = True
    threading.Thread(target=loop, args=(db_fn,), daemon=True, name="sh-collectors").start()
    return True
