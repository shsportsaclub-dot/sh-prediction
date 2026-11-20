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


KEY_NAMES = ("CRICKETDATA_API_KEY", "CRIC_API_KEY", "CRICAPI_KEY", "CRICKET_API_KEY", "CRICKETDATA_KEY")


def key_name():
    """Name of the environment variable holding the CricketData key: a known name first, otherwise any
    variable named CRIC...KEY (the owner may have copied the name from another service)."""
    for n in KEY_NAMES:
        if os.getenv(n, "").strip():
            return n
    for n in sorted(os.environ):
        if re.fullmatch(r"CRIC[A-Z0-9_]*(KEY|TOKEN)", n) and os.environ[n].strip():
            return n
    return None


def key():
    n = key_name()
    return os.environ[n].strip() if n else ""


def today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def plan_limit(c):
    """Daily hit limit the provider last reported for this key (100 = Lifetime Free). Unknown until the first call."""
    r = c.execute("SELECT value FROM system_settings WHERE key='cricketdata_plan'").fetchone()
    try:
        return int(json.loads(r[0])["hitsLimit"]) if r else None
    except (ValueError, KeyError, TypeError):
        return None


def plan_override(c):
    """Owner-declared plan, e.g. {"mode": "unlimited", "until": "2026-11-29"}; ignored after its end date."""
    r = c.execute("SELECT value FROM system_settings WHERE key='cricketdata_plan_override'").fetchone()
    if not r:
        return None
    try:
        o = json.loads(r[0])
    except ValueError:
        return None
    if o.get("until") and today() > o["until"]:
        return None
    return o


def unlimited(c):
    o = plan_override(c)
    L = plan_limit(c)
    return bool(o and o.get("mode") == "unlimited") or (L is not None and L >= 100000)


def auto(c, cfg):
    """Effective settings: explicit numbers in the job config win; 'auto' (default) follows the plan limit."""
    if unlimited(c):
        return {"limit": None, "paid": True, "unlimited": True, "budget": 10 ** 9,
                "max_featured": cfg.get("max_featured") if isinstance(cfg.get("max_featured"), int) else 20,
                "scorecard_every_min": 0, "balls_every_min": 0}
    L = plan_limit(c) or 100
    paid = L > 100
    b = cfg.get("daily_budget", "auto")
    return {"limit": L, "paid": paid, "unlimited": False,
            "budget": (L - RESERVE if paid else 60) if b in (None, "auto") else int(b),
            "max_featured": cfg.get("max_featured") if isinstance(cfg.get("max_featured"), int) else (min(8, max(1, L // 500)) if paid else 1),
            "scorecard_every_min": cfg.get("scorecard_every_min") if isinstance(cfg.get("scorecard_every_min"), (int, float)) else (2 if paid else 6),
            "balls_every_min": cfg.get("balls_every_min") if isinstance(cfg.get("balls_every_min"), (int, float)) else (2 if paid else 12)}


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
    if info.get("hitsLimit"):
        c.execute("INSERT INTO system_settings(key,value,updated_at,updated_by) VALUES('cricketdata_plan',?,?,'cricketdata') "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                  (json.dumps({"hitsLimit": info["hitsLimit"], "hitsToday": info.get("hitsToday")}), datetime.datetime.now(datetime.timezone.utc).isoformat()))
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
    if budget in (None, "auto"):
        budget = auto(c, {})["budget"]
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


# ------------------------------------------------------------------ featured match detail (scorecard, squad, info, balls)
# Field names follow CricketData's live replies as used by the SH live-line server:
# scorecard[] {inning, batting[{batsman{id,name}, r, b, 4s, 6s, sr, dismissal-text}], bowling[{bowler{id,name}, o, m, r, w, nb, wd, eco}],
#              extras, totals{R, W, O}}; match_squad -> [{teamName, players[{id,name,role,...}]}]; match_bbb -> {bbb[...]}.
# Anything else in a reply is kept raw and ignored by the screens.

def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def norm_scorecard(data):
    out = []
    for inn in (data or {}).get("scorecard") or []:
        bat = []
        for b in inn.get("batting") or []:
            p = b.get("batsman") or {}
            bat.append({"name": p.get("name") if isinstance(p, dict) else str(p), "id": p.get("id") if isinstance(p, dict) else None,
                        "r": _num(b.get("r")), "b": _num(b.get("b")), "fours": _num(b.get("4s")), "sixes": _num(b.get("6s")),
                        "sr": _num(b.get("sr")), "dismissal": b.get("dismissal-text") or b.get("dismissal") or None})
        bowl = []
        for w in inn.get("bowling") or []:
            p = w.get("bowler") or {}
            bowl.append({"name": p.get("name") if isinstance(p, dict) else str(p), "id": p.get("id") if isinstance(p, dict) else None,
                         "o": w.get("o"), "m": _num(w.get("m")), "r": _num(w.get("r")), "w": _num(w.get("w")),
                         "nb": _num(w.get("nb")), "wd": _num(w.get("wd")), "eco": _num(w.get("eco"))})
        t = inn.get("totals") or {}
        ex = inn.get("extras") or {}
        out.append({"inning": inn.get("inning"), "batting": bat, "bowling": bowl,
                    "total": {"r": _num(t.get("R")), "w": _num(t.get("W")), "o": t.get("O"), "rr": _num(t.get("Rr"))} if t else None,
                    "extras": ex if isinstance(ex, dict) else {"total": _num(ex)}})
    return out


def norm_squad(data):
    teams = data if isinstance(data, list) else (data or {}).get("squads") or (data or {}).get("teams") or []
    out = []
    for t in teams if isinstance(teams, list) else []:
        out.append({"team": t.get("teamName") or t.get("name"), "players": [{"name": p.get("name"), "id": p.get("id"), "role": p.get("role")}
                                                                          for p in t.get("players") or [] if isinstance(p, dict)]})
    if not out and isinstance(data, dict) and isinstance(data.get("players"), list):   # flat list with a team field
        byt = {}
        for p in data["players"]:
            byt.setdefault(p.get("team") or "Squad", []).append({"name": p.get("name"), "id": p.get("id"), "role": p.get("role")})
        out = [{"team": k, "players": v} for k, v in byt.items()]
    return out


def norm_balls(data):
    rows = (data or {}).get("bbb") if isinstance(data, dict) else data
    out = []
    for x in rows or []:
        if not isinstance(x, dict):
            continue
        name = lambda v: (v.get("name") if isinstance(v, dict) else v) or None
        out.append({"n": x.get("n"), "inning": x.get("inning"), "over": _num(x.get("over")), "ball": _num(x.get("ball")), "runs": _num(x.get("runs")) or 0,
                    "batter": name(x.get("batsman")), "bowler": name(x.get("bowler")),
                    "wicket": bool(x.get("wicket") or x.get("dismissal") or x.get("out")),
                    "extra": x.get("extras") or x.get("extra") or (("wd" if x.get("wide") else "nb" if x.get("noball") else None))})
    return out


def _detail_targets(c, cfg):
    """Live CricketData matches, best first: owner/priority competitions, then most recently started."""
    rows = c.execute("""SELECT m.id, s.provider_id, cp.name AS comp, m.start_utc FROM matches m
                        JOIN data_provider_syncs s ON s.local_id=m.id AND s.provider='cricketdata' AND s.provider_entity='match'
                        JOIN competitions cp ON cp.id=m.competition_id WHERE m.status='live' ORDER BY m.start_utc DESC""").fetchall()
    pri = [p.lower() for p in cfg.get("priority", [])]
    rank = lambda r: next((i for i, p in enumerate(pri) if p in (r["comp"] or "").lower()), len(pri))
    return sorted(rows, key=rank)[: max(0, int(cfg.get("max_featured", 1)))]


def _detail_call(c, endpoint, pid, budget, opener):
    try:
        j, _ = call(c, endpoint, {"id": pid}, budget, opener)
        return j.get("data"), None
    except CDError as e:
        return None, "%s: %s" % (endpoint, e)


def sync_detail(c, cfg, now_fn, opener=urllib.request.urlopen):
    A = auto(c, cfg)
    budget = A["budget"]
    done, notes = [], []
    targets = _detail_targets(c, dict(cfg, max_featured=A["max_featured"]))
    c.execute("UPDATE ext_match_detail SET featured=0")
    for t in targets:
        mid, pid = t["id"], t["provider_id"]
        row = c.execute("SELECT * FROM ext_match_detail WHERE match_id=?", (mid,)).fetchone()
        if not row:
            c.execute("INSERT INTO ext_match_detail(match_id,source) VALUES(?,'cricketdata')", (mid,))
            row = c.execute("SELECT * FROM ext_match_detail WHERE match_id=?", (mid,)).fetchone()
        c.execute("UPDATE ext_match_detail SET featured=1 WHERE match_id=?", (mid,))
        age = lambda at: 10 ** 9 if not at else (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(at)).total_seconds() / 60
        mnotes = []
        data, err = (None, None) if age(row["scorecard_at"]) < A["scorecard_every_min"] - 0.2 else _detail_call(c, "match_scorecard", pid, budget, opener)
        if data is None and err is None:
            pass
        elif data is not None:
            new_sc = norm_scorecard(data)
            old_sc = json.loads(row["scorecard_json"]) if row["scorecard_json"] else None
            if old_sc is not None and new_sc != old_sc:
                backfill_updates(c, mid)        # before this snapshot is kept, so it is not counted twice
            _store_raw(c, pid, "scorecard", data, now_fn)
            c.execute("UPDATE ext_match_detail SET scorecard_json=?, scorecard_at=? WHERE match_id=?", (json.dumps(new_sc), now_fn(), mid))
            last = new_sc[-1]["total"] if new_sc and new_sc[-1].get("total") else None
            prev = old_sc[-1]["total"] if old_sc and old_sc[-1].get("total") else None
            # SH commentary from scorecard changes (works even when the source sends no ball-by-ball rows)
            if old_sc is not None and new_sc != old_sc:
                store_updates(c, mid, derive_updates(old_sc, new_sc), now_fn)
            if last and last != prev:
                import live
                live.publish(c, mid, "ball", {"score": "%s-%s" % (last["r"], last["w"]), "overs": last["o"], "source": "scorecard"})
        else:
            mnotes.append(err)
        if age(row["squad_at"]) >= cfg.get("squad_every_min", 120):
            data, err = _detail_call(c, "match_squad", pid, budget, opener)
            if data is not None:
                c.execute("UPDATE ext_match_detail SET squad_json=?, squad_at=? WHERE match_id=?", (json.dumps(norm_squad(data)), now_fn(), mid))
            else:
                mnotes.append(err)
        if age(row["info_at"]) >= cfg.get("info_every_min", 120):
            data, err = _detail_call(c, "match_info", pid, budget, opener)
            if data is not None:
                keep = {k: data.get(k) for k in ("name", "matchType", "status", "venue", "date", "dateTimeGMT", "teams", "tossWinner", "tossChoice",
                                                 "matchWinner", "series_id", "fantasyEnabled", "bbbEnabled") if k in data}
                c.execute("UPDATE ext_match_detail SET info_json=?, info_at=? WHERE match_id=?", (json.dumps(keep), now_fn(), mid))
            else:
                mnotes.append(err)
        info = json.loads(c.execute("SELECT info_json FROM ext_match_detail WHERE match_id=?", (mid,)).fetchone()[0] or "{}")
        if cfg.get("balls", True) and info.get("bbbEnabled") is not False and age(row["balls_at"]) >= A["balls_every_min"] - 0.2:
            data, err = _detail_call(c, "match_bbb", pid, budget, opener)
            if data is not None:
                nb = norm_balls(data)
                c.execute("UPDATE ext_match_detail SET balls_json=?, balls_at=? WHERE match_id=?", (json.dumps(nb), now_fn(), mid))
                publish_new_balls(c, mid, nb, now_fn)
            else:
                mnotes.append(err)
        elif info.get("bbbEnabled") is False:
            mnotes.append("match_bbb: provider lists this match with ball-by-ball switched off")
        c.execute("UPDATE ext_match_detail SET notes_json=? WHERE match_id=?", (json.dumps([n for n in mnotes if n]), mid))
        c.commit()
        done.append({"match_id": mid, "provider_id": pid, "notes": mnotes})
        notes += mnotes
    return {"featured": done, "hits_used_today": hits_used(c), "plan_limit": A["limit"], "budget": budget, "max_featured": A["max_featured"],
            "note": None if targets else "no live CricketData match right now; no hit spent"}


_EXT = {"wd": "wide", "wides": "wide", "wide": "wide", "nb": "no_ball", "noballs": "no_ball", "noball": "no_ball",
        "b": "bye", "byes": "bye", "lb": "leg_bye", "legbyes": "leg_bye"}

def publish_new_balls(c, mid, balls, now_fn):
    """One live 'delivery' event per new provider ball, with SH's own commentary. The event key is stored in the same
    transaction (UNIQUE), so a restart or a repeated poll never sends a ball twice."""
    import commentary as commentary_engine
    import live, live_bridge
    c.execute("CREATE TABLE IF NOT EXISTS live_event_keys(event_key TEXT PRIMARY KEY, match_id TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    first = not c.execute("SELECT 1 FROM live_event_keys WHERE match_id=?", (str(mid),)).fetchone()
    inn_ids, sent = {}, 0
    for i, b in enumerate(balls or []):
        if b.get("over") is None or b.get("ball") is None:
            continue
        ino = inn_ids.setdefault(str(b.get("inning")), len(inn_ids) + 1)
        key = live_bridge.event_key({"provider": "cricketdata", "match_id": str(mid), "innings": ino, "event_id": b.get("n"),
                                     "over": b.get("over"), "ball": b.get("ball")})
        if c.execute("INSERT OR IGNORE INTO live_event_keys(event_key, match_id) VALUES(?,?)", (key, str(mid))).rowcount != 1:
            continue
        if first:
            continue          # first sight of a match already in progress: record the backlog without flooding clients
        et = _EXT.get(str(b.get("extra") or "").lower())
        runs = b.get("runs") or 0
        ev = {"innings_no": ino, "seq": b.get("n") or i + 1, "over_no": b.get("over") or 0, "ball_in_over": b.get("ball") or 0,
              "runs_bat": 0 if et in ("wide", "bye", "leg_bye") else runs, "extras": runs if et in ("wide", "bye", "leg_bye") else 0,
              "extra_type": et, "is_wicket": 1 if b.get("wicket") else 0, "wicket_kind": None,
              "batter": b.get("batter"), "bowler": b.get("bowler"), "batting_team_id": None}
        text = (commentary_engine.generate([ev], "en", {}) or [{}])[0].get("text")
        live.publish(c, mid, "delivery", {"innings": ino, "over": "%s.%s" % (b.get("over"), b.get("ball")), "runs": runs, "extra": et,
                                          "wicket": bool(b.get("wicket")), "batter": b.get("batter"), "bowler": b.get("bowler"),
                                          "commentary": text, "source": "CricketData", "status": "PROVIDER_REPORTED", "event_key": key})
        sent += 1
    if sent:
        live.wake()
    return sent


def _ob(o):
    s = str(o if o is not None else "0").split(".")
    try:
        return int(float(s[0] or 0)) * 6 + (int(s[1]) if len(s) > 1 and s[1] else 0)
    except ValueError:
        return 0


def derive_updates(old_sc, new_sc):
    """SH's own commentary lines from two scorecard snapshots (used when the source sends no ball-by-ball rows).
    Only facts in the two cards are used: runs, balls, 4s, 6s, dismissals, bowler figures. Nothing is invented."""
    out = []
    if not new_sc:
        return out
    olds = {i.get("inning"): i for i in (old_sc or [])}
    for inn in new_sc:
        o = olds.get(inn.get("inning"))
        if o is None:
            if old_sc is not None:
                out.append({"kind": "innings", "text": "%s begin their innings." % re.sub(r"\s*inning\s*\d+$", "", str(inn.get("inning") or ""), flags=re.I),
                            "flash": None})
            continue
        nt, ot = inn.get("total") or {}, o.get("total") or {}
        nb_bat = {b.get("name"): b for b in inn.get("batting") or [] if b.get("name")}
        ob_bat = {b.get("name"): b for b in o.get("batting") or [] if b.get("name")}
        dballs = sum((b.get("b") or 0) for b in nb_bat.values()) - sum((b.get("b") or 0) for b in ob_bat.values())
        lines, flash = [], None
        wickets = []
        for name, b in nb_bat.items():
            p = ob_bat.get(name)
            out_now = bool(b.get("dismissal")) and not re.search(r"not out|batting", b.get("dismissal") or "", re.I)
            out_before = p and p.get("dismissal") and not re.search(r"not out|batting", p.get("dismissal") or "", re.I)
            if out_now and not out_before:
                wickets.append("WICKET! %s %s, %d (%d)." % (name, b.get("dismissal"), b.get("r") or 0, b.get("b") or 0))
                continue
            if not p:
                if not out_now:
                    lines.append("%s comes in to bat." % name)
                continue
            d4 = (b.get("fours") or 0) - (p.get("fours") or 0)
            d6 = (b.get("sixes") or 0) - (p.get("sixes") or 0)
            dr = (b.get("r") or 0) - (p.get("r") or 0)
            if d6 > 0:
                lines.append("SIX! %s%s, now %d (%d)." % (name, " (%d sixes)" % d6 if d6 > 1 else "", b.get("r") or 0, b.get("b") or 0))
            if d4 > 0:
                lines.append("FOUR! %s%s, now %d (%d)." % (name, " (%d fours)" % d4 if d4 > 1 else "", b.get("r") or 0, b.get("b") or 0))
            if dr > 0 and not d4 and not d6:
                lines.append("%s adds %d, now %d (%d)." % (name, dr, b.get("r") or 0, b.get("b") or 0))
        score = "%s-%s (%s)" % (nt.get("r"), nt.get("w"), nt.get("o")) if nt.get("r") is not None else ""
        dr_tot = (nt.get("r") or 0) - (ot.get("r") or 0) if nt.get("r") is not None and ot.get("r") is not None else None
        dball_tot = _ob(nt.get("o")) - _ob(ot.get("o")) if nt.get("o") is not None and ot.get("o") is not None else dballs
        if wickets:
            flash = {"wicket": True, "batter": wickets[0].split("WICKET! ")[1].split(" ")[0]}
        elif dball_tot == 1 and dr_tot is not None:
            sixes = any(l.startswith("SIX") for l in lines); fours = any(l.startswith("FOUR") for l in lines)
            flash = {"runs": 6} if sixes and dr_tot >= 6 else {"runs": 4} if fours and dr_tot >= 4 else {"runs": dr_tot}
        if not lines and not wickets and dball_tot == 1 and dr_tot == 0:
            lines.append("No run.")
        elif not lines and not wickets and dr_tot:
            lines.append("%d run%s from the last %s." % (dr_tot, "" if dr_tot == 1 else "s", "ball" if dball_tot == 1 else "%d balls" % dball_tot if dball_tot > 1 else "update"))
        if wickets or lines:
            out.append({"kind": "wicket" if wickets else "score", "overs": nt.get("o"), "score": score,
                        "text": " ".join(wickets + lines), "flash": flash})
    return out


def _updates_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS score_updates(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id), overs TEXT, score TEXT,
                 kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)""")


def store_updates(c, mid, ups, now_fn, publish=True):
    import live
    _updates_table(c)
    for u in ups:
        c.execute("INSERT INTO score_updates(match_id,overs,score,kind,text,created_at) VALUES(?,?,?,?,?,?)",
                  (mid, str(u.get("overs") or ""), u.get("score"), u["kind"], u["text"], now_fn()))
        if publish and u.get("flash"):
            f = dict(u["flash"], commentary=u["text"], over=str(u.get("overs") or ""), source="scorecard", status="PROVIDER_REPORTED")
            live.publish(c, mid, "delivery", f)


def backfill_updates(c, mid):
    """First look at a match with no SH lines yet: replay every scorecard snapshot already kept in source_records
    (oldest first) so the commentary starts from the first snapshot we fetched, not from the next change. Runs once."""
    _updates_table(c)
    if c.execute("SELECT 1 FROM score_updates WHERE match_id=? LIMIT 1", (mid,)).fetchone():
        return 0
    r = c.execute("SELECT provider_id FROM data_provider_syncs WHERE provider='cricketdata' AND provider_entity='match' AND local_id=?", (mid,)).fetchone()
    if not r:
        return 0
    prev, n = None, 0
    for payload, at in c.execute("SELECT payload, fetched_at FROM source_records WHERE provider='cricketdata' AND provider_id=? AND kind='scorecard' ORDER BY id",
                                 (str(r[0]),)).fetchall():
        try:
            sc = norm_scorecard(json.loads(payload))
        except Exception:
            continue
        if prev is not None and sc != prev:
            ups = derive_updates(prev, sc)
            store_updates(c, mid, ups, lambda: at, publish=False)
            n += len(ups)
        prev = sc
    return n