"""CricketData.org (formerly CricAPI) adapter: authorized API with the owner's key (env CRICKETDATA_API_KEY).

Free plan: 100 hits/day, shared with the Telegram bot when the same key is used. SH PREDICTION spends at most
`daily_budget` hits per UTC day (default 60) and also stops when the provider reports fewer than RESERVE hits left.
What it gives us: match list (upcoming/live/finished), live score lines, toss and result. It does NOT give
ball-by-ball on the free plan, so matches from this source are marked "score only".
"""
import datetime
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request

BASE = "https://api.cricapi.com/v1/"
RESERVE = 15          # hits always left for other apps sharing the key
FMT = {"t20": "T20", "t20i": "T20", "odi": "ODI", "test": "Test", "t10": "T10"}


class CDError(Exception):
    pass


def key():
    return os.getenv("CRICKETDATA_API_KEY", "").strip()


def today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def hits_used(c):
    r = c.execute("SELECT hits FROM api_budget WHERE provider='cricketdata' AND day=?", (today(),)).fetchone()
    return r[0] if r else 0


def call(c, endpoint, params, budget, opener=urllib.request.urlopen):
    if not key():
        raise CDError("CRICKETDATA_API_KEY is not set on the server")
    if hits_used(c) >= budget:
        raise CDError("daily limit reached (%d of %d hits used by SH PREDICTION today)" % (hits_used(c), budget))
    q = dict(params, apikey=key())
    url = BASE + endpoint + "?" + urllib.parse.urlencode(q)
    c.execute("INSERT INTO api_budget(provider,day,hits) VALUES('cricketdata',?,1) ON CONFLICT(provider,day) DO UPDATE SET hits=hits+1", (today(),))
    c.commit()
    try:
        raw = opener(urllib.request.Request(url, headers={"User-Agent": "SH-PREDICTION/1.0"}), timeout=30).read()
    except Exception as e:
        raise CDError("request failed: %s" % re.sub(r"apikey=[^&\s]+", "apikey=***", str(e)))
    j = json.loads(raw)
    if j.get("status") != "success":
        raise CDError("provider error: %s" % (j.get("reason") or j.get("status")))
    info = j.get("info") or {}
    if info.get("hitsLimit") and info.get("hitsToday") is not None and info["hitsLimit"] - info["hitsToday"] < RESERVE:
        c.execute("UPDATE api_budget SET hits=? WHERE provider='cricketdata' AND day=?", (budget, today()))   # stop for today: key shared
    return j, info


def _store_raw(c, pid, kind, payload, now_fn):
    s = json.dumps(payload, sort_keys=True)
    c.execute("INSERT OR IGNORE INTO source_records(provider,provider_id,kind,payload,payload_hash,fetched_at) VALUES('cricketdata',?,?,?,?,?)",
              (str(pid), kind, s, hashlib.sha256(s.encode()).hexdigest(), now_fn()))


def series_name(m):
    """'India vs Australia, 2nd T20I, Australia tour of India, 2026' -> 'Australia tour of India, 2026'."""
    parts = [p.strip() for p in (m.get("name") or "").split(",")]
    return ", ".join(parts[2:]) if len(parts) >= 3 else (m.get("series") or m.get("name") or "CricketData match")


def margin_from(status):
    m = re.search(r"won by (.+)$", status or "", re.I)
    return m.group(1).strip() if m else None


def upsert(c, m, create_match, record_result, now_fn):
    """Store one CricketData match; returns (match_id, created?)."""
    teams = [t.get("name") for t in (m.get("teamInfo") or [])] or (m.get("teams") or [])
    if len(teams) != 2 or not (m.get("dateTimeGMT") or m.get("date")):
        return None, False
    start = (m.get("dateTimeGMT") or m["date"] + "T00:00:00")
    start = start if "+" in start or start.endswith("Z") else start + "+00:00"
    fmt = FMT.get(str(m.get("matchType") or "").lower(), "Other")
    src = "CricketData.org API (match %s). Team order as listed by the provider." % m["id"]
    r = create_match({"competition": series_name(m), "home": teams[0], "away": teams[1], "start_utc": start.replace("Z", "+00:00"),
                      "venue": m.get("venue"), "format": fmt, "source": src, "data_origin": "imported",
                      "provider": "cricketdata", "provider_id": m["id"]})
    mid = r["match_id"]
    c.execute("UPDATE matches SET listed_order=?, home_away_verified=0 WHERE id=?", (json.dumps(teams), mid))
    _store_raw(c, m["id"], "match", m, now_fn)
    started, ended = bool(m.get("matchStarted")), bool(m.get("matchEnded"))
    if started and not ended:
        c.execute("UPDATE matches SET status='live', updated_at=? WHERE id=? AND status='scheduled'", (now_fn(), mid))
    if m.get("score") is not None or started:
        c.execute("""INSERT INTO live_scores(match_id,source,status_text,innings_json,fetched_at,ball_by_ball) VALUES(?,?,?,?,?,0)
                     ON CONFLICT(match_id) DO UPDATE SET source=excluded.source,status_text=excluded.status_text,
                     innings_json=excluded.innings_json,fetched_at=excluded.fetched_at""",
                  (mid, "cricketdata", m.get("status"), json.dumps(m.get("score") or []), now_fn()))
    row = c.execute("SELECT home_team_id, away_team_id FROM matches WHERE id=?", (mid,)).fetchone()
    ids = {teams[0]: row[0], teams[1]: row[1]}
    if m.get("tossWinner") in ids and not c.execute("SELECT 1 FROM toss_results WHERE match_id=?", (mid,)).fetchone():
        ch = str(m.get("tossChoice") or "").lower()
        c.execute("INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)",
                  (mid, ids[m["tossWinner"]], "bat" if ch.startswith("bat") else "bowl" if ch.startswith(("bowl", "field")) else None, src, now_fn()))
    if ended and not c.execute("SELECT 1 FROM match_results WHERE match_id=?", (mid,)).fetchone():
        st = (m.get("status") or "").lower()
        if m.get("matchWinner") in ids:
            record_result({"match_id": mid, "result_type": "win", "winner_team_id": ids[m["matchWinner"]], "margin": margin_from(m.get("status")), "source": src})
        elif "no result" in st:
            record_result({"match_id": mid, "result_type": "no_result", "source": src})
        elif "abandon" in st:
            record_result({"match_id": mid, "result_type": "abandoned", "source": src})
        elif "drawn" in st or "draw" == st.strip():
            record_result({"match_id": mid, "result_type": "draw", "source": src})
        else:
            m2 = re.search(r"^(.+?) won by", m.get("status") or "")
            if m2 and m2.group(1).strip() in ids:
                record_result({"match_id": mid, "result_type": "win", "winner_team_id": ids[m2.group(1).strip()], "margin": margin_from(m.get("status")), "source": src})
    return mid, r["status"] == "created"


def sync(c, endpoint, budget, create_match, record_result, now_fn, opener=urllib.request.urlopen, pages=1):
    k = {"fetched": 0, "created": 0, "updated": 0, "hits_used_today": None, "provider_hits_today": None}
    for page in range(pages):
        j, info = call(c, endpoint, {"offset": page * 25}, budget, opener)
        k["provider_hits_today"] = "%s/%s" % (info.get("hitsToday"), info.get("hitsLimit"))
        for m in j.get("data") or []:
            if not m.get("id"):
                continue
            k["fetched"] += 1
            mid, created = upsert(c, m, create_match, record_result, now_fn)
            if mid:
                k["created" if created else "updated"] += 1
        if len(j.get("data") or []) < 25:
            break
    k["hits_used_today"] = hits_used(c)
    return k
