"""SH live event stream (Server-Sent Events) for matches scored in SH PREDICTION.

Every scored delivery is written to live_events (persistent, so a reconnecting client resumes with Last-Event-ID) and
wakes waiting SSE connections. Only data that was actually scored or received is sent; when nothing is live the
stream says so in a status event.
"""
import json
import threading
import time

from schema import now

_cond = threading.Condition()
_version = {"n": 0}

def publish(c, match_id, kind, payload):
    c.execute("INSERT INTO live_events(match_id,kind,payload,created_at) VALUES(?,?,?,?)", (match_id, kind, json.dumps(payload), now()))
    eid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    return eid

def wake():
    with _cond:
        _version["n"] += 1
        _cond.notify_all()

def stream(handler, db_fn, match_id, last_id=0, max_seconds=300, heartbeat=15):
    """Writes an SSE response. Ends after max_seconds (clients reconnect automatically with Last-Event-ID)."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    w = handler.wfile
    start = time.time()
    c = db_fn()
    try:
        m = c.execute("SELECT status, data_origin FROM matches WHERE id=?", (match_id,)).fetchone()
        status = {"match_id": match_id, "status": m["status"] if m else "unknown", "data_origin": m["data_origin"] if m else None,
                  "live_source": "SH scorer" if m and m["status"] == "live" else None,
                  "message": None if m and m["status"] == "live" else "No live data for this match right now."}
        w.write(("event: status\ndata: %s\nretry: 3000\n\n" % json.dumps(status)).encode()); w.flush()
        last_beat = time.time()
        while time.time() - start < max_seconds:
            rows = c.execute("SELECT * FROM live_events WHERE match_id=? AND id>? ORDER BY id LIMIT 200", (match_id, last_id)).fetchall()
            for r in rows:
                w.write(("id: %d\nevent: %s\ndata: %s\n\n" % (r["id"], r["kind"], r["payload"])).encode())
                last_id = r["id"]
            if rows:
                w.flush()
                continue
            if time.time() - last_beat >= heartbeat:
                w.write(b": heartbeat\n\n"); w.flush()
                last_beat = time.time()
            with _cond:
                v = _version["n"]
                _cond.wait_for(lambda: _version["n"] != v, timeout=min(heartbeat, max(0.1, max_seconds - (time.time() - start))))
            c.commit()  # end the read snapshot so new rows become visible
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        c.close()
