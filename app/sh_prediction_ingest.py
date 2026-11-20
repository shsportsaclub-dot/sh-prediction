"""SH Prediction verified ball-event ingestion; provider-neutral, no scraping."""
import hashlib
import json

FIELDS = ("provider", "match_id", "innings", "event_id", "over", "ball")

def normalize(event):
    if not isinstance(event, dict):
        raise ValueError("structured event required")
    if any(event.get(k) is None or event.get(k) == "" for k in FIELDS):
        raise ValueError("provider, match, innings, event, over and ball required")
    if event.get("verified") is not True:
        raise ValueError("unverified event rejected")
    runs = event.get("runs_bat", 0)
    if type(runs) is not int or not 0 <= runs <= 6:
        raise ValueError("invalid runs")
    extras = event.get("extras", {})
    if not isinstance(extras, dict) or any(type(v) is not int or v < 0 for v in extras.values()):
        raise ValueError("invalid extras")
    allowed = FIELDS + ("runs_bat", "extras", "wicket", "wicket_kind", "batter", "bowler", "verified", "source_timestamp")
    return {k: event[k] for k in allowed if k in event}

def event_key(event):
    return hashlib.sha256(json.dumps([event[k] for k in FIELDS[:4]], ensure_ascii=False).encode()).hexdigest()

def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS sh_prediction_ball_events (
        event_key TEXT PRIMARY KEY, provider TEXT NOT NULL, match_id TEXT NOT NULL,
        innings TEXT NOT NULL, event_id TEXT NOT NULL, payload TEXT NOT NULL,
        received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("CREATE INDEX IF NOT EXISTS sh_prediction_ball_match ON sh_prediction_ball_events(match_id, received_at)")
    conn.commit()

def ingest(conn, event):
    """Atomically save one verified event. Caller may notify SSE only after commit."""
    clean = normalize(event)
    key = event_key(clean)
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute("""INSERT OR IGNORE INTO sh_prediction_ball_events
            (event_key, provider, match_id, innings, event_id, payload)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (key, str(clean["provider"]), str(clean["match_id"]), str(clean["innings"]),
             str(clean["event_id"]), json.dumps(clean, ensure_ascii=False)))
        conn.commit()
        return cur.rowcount == 1, key
    except BaseException:
        conn.rollback()
        raise

def history(conn, match_id, limit=200):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid limit")
    rows = conn.execute("""SELECT payload, received_at FROM sh_prediction_ball_events
        WHERE match_id=? ORDER BY received_at, rowid LIMIT ?""", (str(match_id), limit)).fetchall()
    return [{**json.loads(payload), "received_at": received_at} for payload, received_at in rows]
