"""SH DATA LINE connector (SH's own data service).

Turned on by Render environment variables: SH_DATA_API_URL and SH_DATA_API_KEY (SH_DATA_PROVIDER=off turns it off).
Reads SH Data Line's matches and balls, links each match to the SH PREDICTION match with the same two teams
(live or within a day), and hands the balls to the ball merge agent together with CricketData's balls.
The key is only read on the server and never sent to the browser.
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
    req = urllib.request.Request(os.environ["SH_DATA_API_URL"].rstrip("/") + path,
                                 headers={"Authorization": "Bearer " + os.environ["SH_DATA_API_KEY"], "Accept": "application/json",
                                          "User-Agent": "SH-PREDICTION/1.0"})
    return json.loads(opener(req, timeout=15).read())


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
    out = []
    for b in rows or []:
        ext = b.get("extra_type") or b.get("extra") or None
        out.append({"n": None, "inning": int(b.get("innings") or 1), "over": int(b.get("over_number") or 0), "ball": int(b.get("ball_number") or 0),
                    "runs": int(b.get("runs_bat") or 0) + int(b.get("extras") or 0), "batter": b.get("batter"), "bowler": b.get("bowler"),
                    "wicket": bool(b.get("wicket")), "extra": ext, "src": "sh"})
    return out


def sync(c, now_fn, opener=urllib.request.urlopen):
    """One pass: link matches, merge balls, publish new deliveries once. Never raises (state shows the error)."""
    import ball_merge
    import cricketdata
    if not configured():
        return {"skipped": "SH Data Line not configured"}
    try:
        ms = (_get("/api/v1/matches", opener) or {}).get("matches") or []
        STATE.update(matches_seen=len(ms), unlinked=[])
        linked, totals = 0, {"duplicates": 0, "conflicts": 0, "new_sh_balls": 0}
        for m in ms:
            if str(m.get("status", "")).lower() in ("finished", "completed", "result", "abandoned"):
                continue
            mid = _find_local(c, m.get("teams") or [])
            if not mid:
                STATE["unlinked"].append(" v ".join(m.get("teams") or [])[:80]); continue
            linked += 1
            c.execute("INSERT OR IGNORE INTO data_provider_syncs(provider,provider_entity,provider_id,local_table,local_id,synced_at) VALUES('shdataline','match',?,'matches',?,?)",
                      (str(m["match_id"]), mid, now_fn()))
            sh = to_balls((_get("/api/v1/matches/%s/balls" % urllib.request.quote(str(m["match_id"]), safe=""), opener) or {}).get("balls"))
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

