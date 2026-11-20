"""Provider-neutral SH live bridge: consume authorized structured events only.

The provider adapter is responsible for fetching new events and respecting its rate limits.
This module never scrapes or copies third-party commentary.
"""
import hashlib
import json
import threading
import time


def event_key(event):
    """Stable identity across repeated provider polls and reconnects."""
    fields = [event.get(k) for k in ('provider', 'match_id', 'innings', 'event_id', 'over', 'ball')]
    if not fields[1] or (fields[3] is None and (fields[4] is None or fields[5] is None)):
        raise ValueError('match_id and event_id or over/ball are required')
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class MemorySeen:
    """Seen-key store for tests and short runs (lost on restart)."""
    def __init__(self, max_seen=50000):
        self._seen, self._order, self.max_seen = set(), [], max_seen

    def has(self, key):
        return key in self._seen

    def add(self, key):
        if key in self._seen:
            return False
        self._seen.add(key); self._order.append(key)
        if len(self._order) > self.max_seen:
            self._seen.discard(self._order.pop(0))
        return True


class SqliteSeen:
    """Persistent seen-key store: a restart never republishes an event (UNIQUE key in the database)."""
    def __init__(self, db_fn):
        self.db_fn = db_fn
        c = db_fn()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS live_event_keys(event_key TEXT PRIMARY KEY, match_id TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
            c.commit()
        finally:
            c.close()

    def has(self, key):
        c = self.db_fn()
        try:
            return c.execute("SELECT 1 FROM live_event_keys WHERE event_key=?", (key,)).fetchone() is not None
        finally:
            c.close()

    def add(self, key, match_id=None):
        c = self.db_fn()
        try:
            cur = c.execute("INSERT OR IGNORE INTO live_event_keys(event_key, match_id) VALUES(?,?)", (key, match_id))
            c.commit()
            return cur.rowcount == 1
        finally:
            c.close()


class LiveBridge:
    """One-second-capable poller with deduplication and no fabricated events.

    fetch_events returns structured provider events. publish is called only for new
    events. For production durability publish must store the event transactionally
    with its unique event key before notifying SSE clients.
    """
    def __init__(self, fetch_events, publish, interval_seconds=1.0, max_seen=50000, seen=None):
        if interval_seconds <= 0 or max_seen < 1:
            raise ValueError('invalid polling configuration')
        self.fetch_events, self.publish = fetch_events, publish
        self.interval_seconds, self.max_seen = interval_seconds, max_seen
        self.seen = seen or MemorySeen(max_seen)
        self._stop = threading.Event()

    def poll_once(self):
        count = 0
        for event in self.fetch_events():
            if not isinstance(event, dict):
                raise ValueError('structured event dictionary required')
            key = event_key(event)
            if self.seen.has(key):
                continue
            self.publish(key, event)          # mark seen only after the event was stored/published
            self.seen.add(key)
            count += 1
        return count

    def run(self):
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.poll_once()
            except Exception:
                pass
            self._stop.wait(max(0, self.interval_seconds - (time.monotonic() - started)))

    def stop(self):
        self._stop.set()
