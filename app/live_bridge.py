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


class LiveBridge:
    """One-second-capable poller with deduplication and no fabricated events.

    fetch_events returns structured provider events. publish is called only for new
    events. For production durability publish must store the event transactionally
    with its unique event key before notifying SSE clients.
    """
    def __init__(self, fetch_events, publish, interval_seconds=1.0, max_seen=50000):
        if interval_seconds <= 0 or max_seen < 1:
            raise ValueError('invalid polling configuration')
        self.fetch_events, self.publish = fetch_events, publish
        self.interval_seconds, self.max_seen = interval_seconds, max_seen
        self._seen = set()
        self._order = []
        self._stop = threading.Event()

    def poll_once(self):
        count = 0
        for event in self.fetch_events():
            if not isinstance(event, dict):
                raise ValueError('structured event dictionary required')
            key = event_key(event)
            if key in self._seen:
                continue
            self.publish(key, event)
            self._seen.add(key)
            self._order.append(key)
            if len(self._order) > self.max_seen:
                self._seen.remove(self._order.pop(0))
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
