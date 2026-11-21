"""SH DATA LINE connector (SH's own data service).

Turned on by Render environment variables: SH_DATA_API_URL and SH_DATA_API_KEY (SH_DATA_PROVIDER=off turns it off).
Use an SH Data Line score_read consumer key for this legacy mode. Contract (sh_data_api.py): GET /v1/matches and
/v1/matches/<id>/balls with header X-API-Key, answers {"items": [...]}. The older /api/v1 + Bearer form is also accepted.
Reads SH Data Line's matches and balls, links each match to the SH PREDICTION match with the same two teams
(live or within a day), and hands the balls to the ball merge agent together with CricketData's balls.
The key is only read on the server and never sent to the browser.
SH_DATA_PROVIDER_MODE=events selects the separate durable provider-event consumer instead.
"""
import datetime
import json
import os
import re
import urllib.request

STATE = {"last_ok": None, "last_error": None, "matches_seen": 0, "linked": 0, "unlinked": [], "last_stats": None}


def configured():
    return bool(os.environ.get("SH_DATA_API_URL", "").startswith("https://") and os.environ.get("SH_DATA_API_KEY")) \
        and os.environ.get("SH_DATA_PROVIDER", "SH_DATA_LINE").lower() not in ("off", "0", "none", "false")


def _get(path, opener):
    k = os.environ["SH_DATA_API_KEY"]
    req = urllib.request.Request(os.environ["SH_DATA_API_URL"].rstrip("/") + path,
                                 headers={"X-API-Key": k, "Authorization": "Bearer " + k, "Accept": "application/json", "User-Agent": "SH-PREDICTION/1.0"})
    return json.loads(opener(req, timeout=15).read())


def _list(j, *names):
    for n in ("items",) + names:
        if isinstance((j or {}).get(n), list):
            return j[n]
    return []


def _matches(opener):
    import urllib.error
    try:
        return _list(_get("/v1/matches", opener), "matches")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return _list(_get("/api/v1/matches", opener), "matches")


def _balls(mid, opener):
    import urllib.error
    q = urllib.request.quote(str(mid), safe=":")      # ids like "cd:abc" stay readable for servers that do not decode the path
    try:
        return _list(_get("/v1/matches/%s/balls" % q, opener), "balls")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return _list(_get("/api/v1/matches/%s/balls" % q, opener), "balls")


_PING = {}


def ping(opener=urllib.request.urlopen):
    """Authenticated check used by the status page: reachable + key accepted (no data shown). Cached 60 s."""
    import time
    if _PING.get("at", 0) > time.time() - 60:
        return _PING["v"]
    _PING.update(at=time.time(), v=_ping(opener))
    return _PING["v"]


def _ping(opener):
    try:
        j = _get("/v1/coverage", opener)
        return {"ok": True, "matches": j.get("matches"), "live_matches": j.get("live_matches")}
    except Exception as e:
        return {"ok": False, "error": re.sub(r"(Bearer|X-API-Key:?) \S+", r"\1 ***", str(e))[:160]}


def _n(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\b(womens|women|w)\b", " women ", s)          # keep men's and women's sides apart (double-headers)
    s = re.sub(r"\b(mens|men|cricket|club|cc|team)\b", " ", s)
    return " ".join(s.split())


def _find_local(c, teams):
    if len(teams) < 2:
        return None
    want = {_n(teams[0]), _n(teams[1])}
    now = datetime.datetime.now(datetime.timezone.utc)
    lo, hi = (now - datetime.timedelta(hours=30)).isoformat(), (now + datetime.timedelta(hours=12)).isoformat()
    for r in c.execute("""SELECT m.id, th.name AS h, ta.name AS a, th.short_code AS hs, ta.short_code AS as_ FROM matches m
                          JOIN teams th ON th.id=m.home_team_id JOIN teams ta ON ta.id=m.away_team_id
                          WHERE m.data_origin<>'demo' AND (m.status='live' OR m.start_utc BETWEEN ? AND ?)
                          ORDER BY (m.status='live') DESC, m.start_utc DESC""", (lo, hi)).fetchall():
        names = [{_n(r["h"]), _n(r["hs"])}, {_n(r["a"]), _n(r["as_"])}]
        t = list(want)
        if (t[0] in names[0] and t[1] in names[1]) or (t[0] in names[1] and t[1] in names[0]):
            return r["id"]
    return None


def to_balls(rows):
    """Data Line ball rows -> SH ball rows. 'runs' there is the batter's runs (older form: runs_bat), 'extras' the extra runs."""
    out = []
    for b in rows or []:
        d = b.get("data") if isinstance(b.get("data"), dict) else {}
        if b.get("over_number") is None or b.get("ball_number") is None:
            continue                                   # a ball without over/ball cannot be placed: skipped, never guessed
        ext = b.get("extra_type") or d.get("extra_type") or b.get("extra") or d.get("extra") or None
        bat = b.get("runs_bat", b.get("runs", 0))
        out.append({"n": None, "inning": int(b.get("innings") or 1), "over": int(b.get("over_number")), "ball": int(b.get("ball_number")),
                    "runs": int(bat or 0) + int(b.get("extras") or 0), "batter": b.get("batter"), "bowler": b.get("bowler"),
                    "wicket": bool(b.get("wicket")), "extra": ext, "src": "sh", "observed_at": b.get("observed_at")})
    return out


def sync(c, now_fn, opener=urllib.request.urlopen):
    """One pass: link matches, merge balls, publish new deliveries once. Never raises (state shows the error)."""
    import ball_merge
    import cricketdata
    if not configured():
        return {"skipped": "SH Data Line not configured"}
    try:
        ms = _matches(opener)
        STATE.update(matches_seen=len(ms), unlinked=[])
        linked, totals = 0, {"duplicates": 0, "conflicts": 0, "new_sh_balls": 0}
        for m in ms:
            if str(m.get("status", "")).lower() in ("finished", "completed", "result", "abandoned", "cancelled", "postponed", "scheduled"):
                continue                                   # balls only for matches in play
            teams = m.get("teams") or [t for t in (m.get("home_team"), m.get("away_team")) if t]
            dl_id = m.get("id") or m.get("match_id")
            mid = _find_local(c, teams)
            if not mid:
                STATE["unlinked"].append(" v ".join(teams)[:80]); continue
            linked += 1
            c.execute("INSERT OR IGNORE INTO data_provider_syncs(provider,provider_entity,provider_id,local_table,local_id,synced_at) VALUES('shdataline','match',?,'matches',?,?)",
                      (str(dl_id), mid, now_fn()))
            c.commit()                                     # no open write transaction while waiting on the network
            sh = to_balls(_balls(dl_id, opener))
            row = c.execute("SELECT balls_json FROM ext_match_detail WHERE match_id=?", (mid,)).fetchone()
            if not row:
                c.execute("INSERT INTO ext_match_detail(match_id,source) VALUES(?,'shdataline')", (mid,)); row = {"balls_json": None}
            old = json.loads(row["balls_json"] or "[]")
            primary = [b for b in old if b.get("src") != "sh"]
            merged, st = ball_merge.merge(primary, sh)
            totals["duplicates"] += st["duplicates"]; totals["conflicts"] += st["conflicts"]
            if len(merged) != len(old):
                totals["new_sh_balls"] += max(0, len(merged) - len(old))
                c.execute("UPDATE ext_match_detail SET balls_json=?, balls_at=? WHERE match_id=?", (json.dumps(merged), now_fn(), mid))
                cricketdata.publish_new_balls(c, mid, merged, now_fn)
            c.commit()
        STATE.update(last_ok=now_fn(), linked=linked, last_stats=totals, last_error=None)
        return dict(totals, linked=linked, seen=len(ms))
    except Exception as e:
        c.rollback()
        STATE.update(last_error=re.sub(r"Bearer \S+", "Bearer ***", str(e))[:200])
        return {"error": STATE["last_error"]}

