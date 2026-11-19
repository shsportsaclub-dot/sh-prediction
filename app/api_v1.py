"""/api/v1 — versioned SH PREDICTION API.

Viewer endpoints are public and return only published predictions and public explanations.
/api/v1/admin/* needs the admin token (checked here, in the backend, for every call).
Logged-in users (Bearer session) manage their preferences and follows; verified experts may submit
predictions, which stay private until an admin publishes them. Every write is audited.
Errors: {"error": {"code", "message"}} with HTTP 400/401/403/404/409/429.
"""
import datetime
import hashlib
import json
import re
import threading
import time
import uuid
import sqlite3

import api_social
import assistant
import auth
import commentary as commentary_engine
import game
import live
import media
import os
import social
import cricsheet
import engine
import fantasy
import gateway
import i18n
import system
from datetime import timedelta
from pathlib import Path
from schema import now, pending, bridge_legacy

class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

def bad(msg):
    return ApiError(400, "VALIDATION_ERROR", msg)

# ------------------------------------------------------------------ rate limiting
RATE = {"capacity": 300, "per_seconds": 60}
_buckets, _lock = {}, threading.Lock()

def rate_ok(key):
    with _lock:
        t = time.time()
        tokens, last = _buckets.get(key, (RATE["capacity"], t))
        tokens = min(RATE["capacity"], tokens + (t - last) * RATE["capacity"] / RATE["per_seconds"])
        if tokens < 1:
            _buckets[key] = (tokens, t)
            return False
        _buckets[key] = (tokens - 1, t)
        return True

# ------------------------------------------------------------------ helpers
def rows(cur):
    return [dict(r) for r in cur]

def page(q):
    try:
        limit = int(q.get("limit", ["50"])[0])
        offset = int(q.get("offset", ["0"])[0])
    except ValueError:
        raise bad("limit and offset must be integers")
    if not 1 <= limit <= 100 or offset < 0:
        raise bad("limit must be 1..100 and offset >= 0")
    return limit, offset

def qv(q, k):
    v = q.get(k, [None])[0]
    return v.strip() if isinstance(v, str) and v.strip() else None

def dataset(q):
    """'verified' (default) or 'demo'. The two are never mixed in one response."""
    d = qv(q, "dataset") or ("demo" if qv(q, "include_demo") == "1" else "verified")
    if d not in ("verified", "demo"):
        raise bad("dataset must be verified or demo")
    return d

def origin_sql(d, alias="m"):
    return "%s.data_origin='demo'" % alias if d == "demo" else "%s.data_origin<>'demo'" % alias

def int_id(v, name="id"):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise bad(name + " must be an integer")

def audit(c, actor, action, entity, entity_id, payload, old=None):
    c.execute("INSERT INTO audit_logs(action,payload,old_value,created_at,actor,entity,entity_id) VALUES(?,?,?,?,?,?,?)",
              (action, json.dumps(payload, ensure_ascii=False, default=str)[:4000],
               json.dumps(old, ensure_ascii=False, default=str) if old else None, now(), actor, entity, str(entity_id)))

def team_code(t):
    return t["short_code"] if t and t["short_code"] and t["short_code_approved"] else None

MATCH_SQL = """SELECT m.*, c.name AS competition, s.name AS season, v.name AS venue,
 h.name AS home_name, h.short_code AS home_code, h.short_code_approved AS home_code_ok,
 a.name AS away_name, a.short_code AS away_code, a.short_code_approved AS away_code_ok,
 t.winner_team_id AS toss_winner_id, t.decision AS toss_decision, r.result_type, r.winner_team_id, r.margin, r.method
 FROM matches m JOIN competitions c ON c.id=m.competition_id LEFT JOIN seasons s ON s.id=m.season_id
 LEFT JOIN venues v ON v.id=m.venue_id JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
 LEFT JOIN toss_results t ON t.match_id=m.id LEFT JOIN match_results r ON r.match_id=m.id"""

def match_out(r):
    d = dict(r)
    d["home"] = {"id": r["home_team_id"], "name": r["home_name"], "short_code": r["home_code"] if r["home_code_ok"] else None}
    d["away"] = {"id": r["away_team_id"], "name": r["away_name"], "short_code": r["away_code"] if r["away_code_ok"] else None}
    for k in ("home_name", "home_code", "home_code_ok", "away_name", "away_code", "away_code_ok"):
        d.pop(k)
    return d

STALE_MIN = 30

def annotate(c, items):
    """Add an honest data_status to each match: what we actually have for it, and from where."""
    if not items:
        return items
    ids = [d["id"] for d in items]
    qm = ",".join("?" * len(ids))
    balls = {r[0]: (r[1], r[2]) for r in c.execute("SELECT match_id, COUNT(*), MAX(source) FROM ball_events WHERE match_id IN (%s) GROUP BY match_id" % qm, ids)}
    live = {r["match_id"]: r for r in c.execute("SELECT * FROM live_scores WHERE match_id IN (%s)" % qm, ids)}
    prov = {}
    for r in c.execute("SELECT local_id, provider FROM data_provider_syncs WHERE provider_entity='match' AND local_id IN (%s)" % qm, ids):
        prov.setdefault(r[0], []).append(r[1])
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=STALE_MIN)).isoformat()
    ext_fresh = {r[0] for r in c.execute("SELECT match_id FROM ext_match_detail WHERE match_id IN (%s) AND scorecard_json IS NOT NULL AND scorecard_at>=?" % qm,
                                         ids + [cutoff])} if c.execute("SELECT 1 FROM sqlite_master WHERE name='ext_match_detail'").fetchone() else set()
    for d in items:
        n, bsrc = balls.get(d["id"], (0, None))
        ls = live.get(d["id"])
        if d.get("data_origin") == "demo":
            st = ("demo", "Demo data")
        elif d["status"] == "scheduled":
            st = ("upcoming", "Upcoming")
        elif d["status"] == "live":
            if n and bsrc not in ("cricsheet",):
                st = ("live_ball_by_ball", "Live · ball-by-ball (SH scoring)")
            elif d["id"] in ext_fresh:
                st = ("live_scorecard", "Live · scorecard (%s)" % ls["source"] if ls else "Live · scorecard")
            elif ls and ls["fetched_at"] >= cutoff:
                st = ("live_score_only", "Live · score only (%s)" % ls["source"])
            elif ls:
                st = ("delayed", "Delayed · last update %s UTC" % ls["fetched_at"][11:16])
            else:
                st = ("unavailable", "Live data unavailable")
        elif n:
            st = ("historical_ball_by_ball", "Historical · ball-by-ball")
        elif d.get("result_type"):
            st = ("result_only", "Result only · no ball-by-ball")
        else:
            st = ("unavailable", "Data unavailable")
        d["data_status"], d["data_status_label"] = st
        d["sources"] = prov.get(d["id"], ["sh_entry"])
        if ls:
            d["live_score"] = {"source": ls["source"], "status_text": ls["status_text"], "innings": json.loads(ls["innings_json"]),
                               "fetched_at": ls["fetched_at"], "ball_by_ball": bool(ls["ball_by_ball"])}
        d["home_away_note"] = None if d.get("home_away_verified", 1) else "Team order as listed by the source; home/away not verified"
    return items

def get_match(c, mid):
    r = c.execute(MATCH_SQL + " WHERE m.id=?", (mid,)).fetchone()
    if not r:
        raise ApiError(404, "NOT_FOUND", "match not found")
    return r

# ------------------------------------------------------------------ privacy of SH logic
# Model internals (factor weights, factor breakdown, model name/version, training sample) are visible
# to admins only. Users see outcomes: probabilities, picks, confidence and the public settlement rule.
PUBLIC_MODEL_NAME = "SH AI"

def is_admin(who):
    return bool(who) and who["role"] == "admin"

def redact_prediction(d):
    d.pop("factors", None)
    d.pop("model_version_id", None)
    if d.get("source_type") == "model":
        d["model"] = PUBLIC_MODEL_NAME
        d["explanation"] = "SH AI prediction"
    for v in d.get("versions", []):
        v.pop("factors_json", None)
    return d

def redact_signals(s):
    pm = s["pre_match"]
    s["pre_match"] = {k: pm[k] for k in ("match_id", "home_win_probability", "away_win_probability", "toss_probability",
                                         "confidence_level", "predicted_team_id", "confidence", "public_factors")}
    s["pre_match"]["model"] = PUBLIC_MODEL_NAME
    return s

# ------------------------------------------------------------------ identity
def identity(h, c):
    """Return dict(user_id, role, actor) or None. A valid admin token gives the admin role (and keeps the user's own id)."""
    adm = h.admin_ok()
    tok = h.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not tok:
        return {"user_id": None, "role": "admin", "actor": "admin-token"} if adm else None
    acct = auth.session_user(c, tok)
    if acct:
        u = c.execute("SELECT * FROM users WHERE id=?", (acct["user_id"],)).fetchone()
        role = "admin" if adm else u["role"]
        return {"user_id": u["id"], "role": role, "actor": ("admin-token:" if adm else "") + "user:%d" % u["id"], "account": acct}
    s = None
    if os.getenv("SH_DEV_PHONE_LOGIN") == "1":  # legacy on-screen phone code sessions: local development only
        s = c.execute("SELECT phone FROM login_sessions WHERE token_hash=? AND created_at>=?",
                      (hashlib.sha256(tok.encode()).hexdigest(), time.time() - 30 * 86400)).fetchone()
    if not s:
        return {"user_id": None, "role": "admin", "actor": "admin-token"} if adm else None
    c.execute("INSERT OR IGNORE INTO users(phone,created_at) VALUES(?,?)", (s[0], now()))
    u = c.execute("SELECT * FROM users WHERE phone=?", (s[0],)).fetchone()
    if adm:
        return {"user_id": u["id"], "role": "admin", "actor": "admin-token:user:%d" % u["id"]}
    return {"user_id": u["id"], "role": u["role"], "actor": "user:%d" % u["id"]}

# ------------------------------------------------------------------ reads
def list_matches(c, q):
    limit, offset = page(q)
    where, args = [], []
    st = qv(q, "status")
    if st:
        groups = {"live": ("live",), "upcoming": ("scheduled",), "completed": ("completed", "abandoned", "no_result", "canceled")}
        if st not in groups:
            raise bad("status must be live, upcoming or completed")
        where.append("m.status IN (%s)" % ",".join("?" * len(groups[st])))
        args += groups[st]
    if qv(q, "competition_id"):
        where.append("m.competition_id=?"); args.append(int_id(qv(q, "competition_id"), "competition_id"))
    if qv(q, "team_id"):
        t = int_id(qv(q, "team_id"), "team_id"); where.append("(m.home_team_id=? OR m.away_team_id=?)"); args += [t, t]
    if qv(q, "date"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", qv(q, "date")):
            raise bad("date must be YYYY-MM-DD")
        where.append("substr(m.start_utc,1,10)=?"); args.append(qv(q, "date"))
    if qv(q, "q"):
        like = "%" + qv(q, "q")[:60] + "%"
        where.append("(h.name LIKE ? OR a.name LIKE ? OR c.name LIKE ? OR h.short_code LIKE ? OR a.short_code LIKE ?)"); args += [like] * 5
    where.append(origin_sql(dataset(q)))
    sql = MATCH_SQL + (" WHERE " + " AND ".join(where) if where else "")
    total = c.execute("SELECT COUNT(*) FROM (" + sql + ")", args).fetchone()[0]
    order = " ORDER BY m.start_utc DESC" if st == "completed" else " ORDER BY m.start_utc ASC"
    items = annotate(c, [match_out(r) for r in c.execute(sql + order + " LIMIT ? OFFSET ?", args + [limit, offset])])
    return {"items": items, "total": total, "limit": limit, "offset": offset}

def form_of(c, team_id, before, n=5):
    rs = c.execute("""SELECT r.winner_team_id, r.result_type FROM matches m JOIN match_results r ON r.match_id=m.id
                      WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.start_utc<? AND m.data_origin<>'demo'
                      ORDER BY m.start_utc DESC LIMIT ?""", (team_id, team_id, before, n)).fetchall()
    return "".join("W" if r[0] == team_id else ("L" if r[0] else "N") for r in rs)

def attribution_for(source):
    return {"text": "Data: " + cricsheet.ATTRIBUTION, "url": cricsheet.LICENSE_URL} if (source or "").startswith("Cricsheet") else None

def match_detail(c, mid):
    r = get_match(c, mid)
    d = annotate(c, [match_out(r)])[0]
    d["attribution"] = attribution_for(r["source"])
    h, a = r["home_team_id"], r["away_team_id"]
    h2h = c.execute("""SELECT r.winner_team_id FROM matches m JOIN match_results r ON r.match_id=m.id
                       WHERE ((m.home_team_id=? AND m.away_team_id=?) OR (m.home_team_id=? AND m.away_team_id=?)) AND m.id<>?
                       AND m.data_origin<>'demo'""", (h, a, a, h, mid)).fetchall()
    d["head_to_head"] = {"matches": len(h2h), "home_won": sum(1 for x in h2h if x[0] == h), "away_won": sum(1 for x in h2h if x[0] == a)}
    d["form"] = {"home_last5": form_of(c, h, r["start_utc"]), "away_last5": form_of(c, a, r["start_utc"])}
    d["playing_xi"] = rows(c.execute("""SELECT x.team_id,x.player_id,p.name,p.role,x.batting_order,x.is_captain,x.is_keeper,x.is_impact_sub
                                         FROM playing_xi x JOIN players p ON p.id=x.player_id WHERE x.match_id=? ORDER BY x.team_id,x.batting_order""", (mid,)))
    d["squads"] = rows(c.execute("SELECT s.team_id,p.id AS player_id,p.name,p.role FROM match_squads s JOIN players p ON p.id=s.player_id WHERE s.match_id=?", (mid,)))
    d["provider_detail"] = provider_detail(c, mid)
    d["history"] = match_history(c, r)
    return d

def provider_detail(c, mid):
    """Scorecard / squads / balls from an outside provider (CricketData), shown as such and never mixed into our own ball_events."""
    r = c.execute("SELECT * FROM ext_match_detail WHERE match_id=?", (mid,)).fetchone() if \
        c.execute("SELECT 1 FROM sqlite_master WHERE name='ext_match_detail'").fetchone() else None
    if not r:
        return None
    load = lambda k: json.loads(r[k]) if r[k] else None
    balls = load("balls_json") or []
    overs = {}
    for b in balls:
        if b.get("over") is not None:
            key = (str(b.get("inning")), int(b["over"]))
            overs[key] = overs.get(key, 0) + (b.get("runs") or 0)
    return {"source": "CricketData.org", "featured": bool(r["featured"]), "scorecard": load("scorecard_json"), "scorecard_at": r["scorecard_at"],
            "squads": load("squad_json"), "squads_at": r["squad_at"], "info": load("info_json"), "balls": balls[-36:], "balls_at": r["balls_at"],
            "runs_per_over": [{"inning": k[0], "over": k[1] + 1, "runs": v} for k, v in sorted(overs.items(), key=lambda kv: (kv[0][0], kv[0][1]))],
            "notes": json.loads(r["notes_json"] or "[]"),
            "rule": "Provider figures shown as received. Ball rows show only runs, over and wicket marks the provider sends."}

def _norm_team(n):
    n = re.sub(r"\s*\((women|men)\)\s*$", "", (n or "").strip(), flags=re.I)
    women = bool(re.search(r"\bwomen\b", n, re.I))
    return re.sub(r"\s+", " ", re.sub(r"\bwomen\b|\bmen\b", "", n, flags=re.I)).strip().lower(), women

def _team_family(c, tid):
    """Same club under its exact name in other sources (e.g. 'Brisbane Heat Women' and 'Brisbane Heat' in a women's competition)."""
    row = c.execute("SELECT name, gender FROM teams WHERE id=?", (tid,)).fetchone()
    base, women = _norm_team(row["name"])
    women = women or row["gender"] == "women"
    ids = []
    for t in c.execute("SELECT id, name, gender FROM teams"):
        b, w = _norm_team(t["name"])
        if b == base and (w or t["gender"] == "women") == women:
            ids.append(t["id"])
    return ids or [tid]

def match_history(c, r):
    """Head-to-head list, last-5 form and venue figures from completed, non-demo matches in our database (no outside data)."""
    H, A = _team_family(c, r["home_team_id"]), _team_family(c, r["away_team_id"])
    qh, qa = ",".join("?" * len(H)), ",".join("?" * len(A))
    fmt = r["format"]
    h2h = []
    for m in c.execute("""SELECT m.id, substr(m.start_utc,1,10) AS day, m.home_team_id, m.away_team_id, th.name AS home, ta.name AS away,
            mr.result_type, mr.winner_team_id, mr.margin, tw.name AS winner FROM matches m JOIN match_results mr ON mr.match_id=m.id
            JOIN teams th ON th.id=m.home_team_id JOIN teams ta ON ta.id=m.away_team_id LEFT JOIN teams tw ON tw.id=mr.winner_team_id
            WHERE m.id<>? AND m.data_origin<>'demo' AND m.format=? AND ((m.home_team_id IN (%s) AND m.away_team_id IN (%s)) OR (m.home_team_id IN (%s) AND m.away_team_id IN (%s)))
            ORDER BY m.start_utc DESC LIMIT 10""" % (qh, qa, qa, qh), [r["id"], fmt] + H + A + A + H):
        d = dict(m)
        d["innings"] = rows(c.execute("SELECT i.innings_no, t.name AS team, i.runs, i.wickets, i.legal_balls FROM innings i JOIN teams t ON t.id=i.batting_team_id WHERE i.match_id=? AND i.is_super_over=0 ORDER BY i.innings_no", (m["id"],)))
        d["side_won"] = "home" if m["winner_team_id"] in H else "away" if m["winner_team_id"] in A else None
        h2h.append(d)
    def form(ids):
        q = ",".join("?" * len(ids))
        out = []
        for m in c.execute("""SELECT mr.result_type, mr.winner_team_id FROM matches m JOIN match_results mr ON mr.match_id=m.id
                WHERE m.start_utc < ? AND m.data_origin<>'demo' AND m.format=? AND (m.home_team_id IN (%s) OR m.away_team_id IN (%s))
                ORDER BY m.start_utc DESC LIMIT 5""" % (q, q), [r["start_utc"], fmt] + ids + ids):
            out.append("W" if m["winner_team_id"] in ids else "L" if m["winner_team_id"] else "-")
        return out
    venue = None
    if r["venue_id"]:
        vname = c.execute("SELECT name FROM venues WHERE id=?", (r["venue_id"],)).fetchone()[0]
        key = vname.split(",")[0].strip()
        vids = [x[0] for x in c.execute("SELECT id FROM venues WHERE name=? OR name LIKE ?", (vname, key + ",%"))] or [r["venue_id"]]
        qv_ = ",".join("?" * len(vids))
        ms = c.execute("""SELECT m.id, mr.winner_team_id FROM matches m JOIN match_results mr ON mr.match_id=m.id
                          WHERE m.venue_id IN (%s) AND m.format=? AND m.data_origin<>'demo' AND m.id<>? AND mr.result_type IN ('win','awarded')""" % qv_,
                       vids + [fmt, r["id"]]).fetchall()
        first, second, bat_first_won, tot = [], [], 0, []
        for m in ms:
            inn = c.execute("""SELECT i.innings_no, i.runs, i.wickets, i.legal_balls, i.batting_team_id, t.name FROM innings i JOIN teams t ON t.id=i.batting_team_id
                               WHERE i.match_id=? AND i.is_super_over=0 ORDER BY i.innings_no""", (m["id"],)).fetchall()
            if len(inn) >= 2:
                first.append(inn[0]["runs"]); second.append(inn[1]["runs"])
                bat_first_won += m["winner_team_id"] == inn[0]["batting_team_id"]
            tot += [(x["runs"], x["wickets"], x["legal_balls"], x["name"]) for x in inn]
        n = len(first)
        fmt_t = lambda x: {"runs": x[0], "wickets": x[1], "overs": "%d.%d" % divmod(x[2], 6), "team": x[3]} if x else None
        venue = {"name": vname, "matches": n, "avg_first_innings": round(sum(first) / n) if n else None,
                 "avg_second_innings": round(sum(second) / n) if n else None,
                 "bat_first_win_pct": round(100 * bat_first_won / n) if n else None,
                 "chase_win_pct": round(100 * (n - bat_first_won) / n) if n else None,
                 "highest": fmt_t(max(tot) if tot else None), "lowest_all_out": fmt_t(min([x for x in tot if x[1] == 10], default=None))}
    return {"head_to_head": h2h, "home_form": form(H), "away_form": form(A), "venue": venue,
            "note": "From completed %s matches in the SH database (Cricsheet, owner sheets, SH scoring, provider results). Demo data excluded." % fmt}

def match_predictions(c, mid, who=None):
    get_match(c, mid)
    out = []
    for p in c.execute("""SELECT p.*, e.result AS evaluation, e.actual_team_id, e.actual_value, e.rule, e.evaluated_at,
                          x.display_name AS expert_name, x.verified AS expert_verified, mv.name||' '||mv.version AS model
                          FROM predictions p LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                          LEFT JOIN expert_profiles x ON x.id=p.expert_id LEFT JOIN model_versions mv ON mv.id=p.model_version_id
                          WHERE p.match_id=? AND p.status<>'draft' %s ORDER BY p.created_at""" % (
                              "" if is_admin(who) else "AND p.id IN (SELECT prediction_id FROM prediction_publications)"), (mid,)):
        d = dict(p)
        d["factors"] = json.loads(d.pop("factors_json") or "null")
        pub = c.execute("SELECT published_at, public_note FROM prediction_publications WHERE prediction_id=?", (p["id"],)).fetchone()
        d["published_at"] = pub[0] if pub else None
        d["public_note"] = pub[1] if pub else None
        d["versions"] = rows(c.execute("SELECT * FROM prediction_versions WHERE prediction_id=? ORDER BY version_no", (p["id"],)))
        out.append(d if is_admin(who) else redact_prediction(d))
    return {"items": out, "published_only": not is_admin(who)}

def scorecard(c, mid):
    get_match(c, mid)
    inns = rows(c.execute("SELECT * FROM innings WHERE match_id=? ORDER BY innings_no", (mid,)))
    for i in inns:
        i["overs"] = "%d.%d" % divmod(i["legal_balls"], 6)
        i["players"] = rows(c.execute("""SELECT s.*,p.name FROM scorecards s JOIN players p ON p.id=s.player_id
                                          WHERE s.match_id=? AND s.innings_no=? ORDER BY s.id""", (mid, i["innings_no"])))
        i["fall_of_wickets"] = rows(c.execute("""SELECT seq,over_no,ball_in_over,wicket_kind,batter_id FROM ball_events
                                                  WHERE match_id=? AND innings_no=? AND is_wicket=1 ORDER BY seq""", (mid, i["innings_no"])))
    return {"match_id": mid, "innings": inns}

def commentary(c, mid, q):
    get_match(c, mid)
    limit, offset = page(q)
    items = rows(c.execute("""SELECT b.*, bt.name AS batter, bw.name AS bowler FROM ball_events b LEFT JOIN players bt ON bt.id=b.batter_id
                              LEFT JOIN players bw ON bw.id=b.bowler_id WHERE b.match_id=? ORDER BY b.innings_no DESC,b.seq DESC LIMIT ? OFFSET ?""",
                           (mid, limit, offset)))
    lang = qv(q, "lang") or "en"
    r = get_match(c, mid)
    allb = rows(c.execute("""SELECT b.*, bt.name AS batter, bw.name AS bowler, i.batting_team_id FROM ball_events b LEFT JOIN players bt ON bt.id=b.batter_id
                             LEFT JOIN players bw ON bw.id=b.bowler_id JOIN innings i ON i.match_id=b.match_id AND i.innings_no=b.innings_no
                             WHERE b.match_id=? ORDER BY b.innings_no, b.seq""", (mid,)))
    tg = {x["innings_no"]: x["target"] for x in c.execute("SELECT innings_no, target FROM innings WHERE match_id=?", (mid,))}
    mb = c.execute("SELECT max_balls FROM innings WHERE match_id=? ORDER BY innings_no LIMIT 1", (mid,)).fetchone()
    gen = {(g["innings_no"], g["seq"]): g["text"] for g in commentary_engine.generate(allb, lang, {r["home_team_id"]: r["home_name"], r["away_team_id"]: r["away_name"]},
                                                                                         mb[0] if mb else None, tg)}
    for it in items:
        it["generated_commentary"] = gen.get((it["innings_no"], it["seq"]))
        it["scorer_note"] = it.pop("commentary", None) if it.get("source") != "cricsheet" else None
    return {"items": items, "total": c.execute("SELECT COUNT(*) FROM ball_events WHERE match_id=?", (mid,)).fetchone()[0], "limit": limit, "offset": offset,
            "language": lang if lang in commentary_engine.languages() else "en",
            "language_note": None if lang in commentary_engine.languages() else "Commentary is generated in English for this language for now.",
            "note": "Commentary is generated by SH from recorded deliveries only."}

def current_live(c, r):
    inn = c.execute("SELECT * FROM innings WHERE match_id=? AND is_super_over=0 ORDER BY innings_no DESC LIMIT 1", (r["id"],)).fetchone()
    if not inn:
        return None
    pre = None
    try:
        pre = engine.predict_match(c, r["id"])["home_win_probability"]
    except LookupError:
        pass
    lp = engine.live_probability(r["format"], inn["innings_no"], inn["runs"], inn["wickets"], inn["legal_balls"],
                                 inn["target"], inn["max_balls"], pre, inn["batting_team_id"] == r["home_team_id"])
    home_bat = inn["batting_team_id"] == r["home_team_id"]
    lp["home_win_probability"] = lp["batting_team_win_probability"] if home_bat else lp["bowling_team_win_probability"]
    lp["away_win_probability"] = round(100 - lp["home_win_probability"], 1)
    lp.update(innings_no=inn["innings_no"], score="%d/%d" % (inn["runs"], inn["wickets"]), overs="%d.%d" % divmod(inn["legal_balls"], 6))
    # partnership & recent momentum from ball events
    balls = c.execute("SELECT * FROM ball_events WHERE match_id=? AND innings_no=? ORDER BY seq", (r["id"], inn["innings_no"])).fetchall()
    part_runs = part_balls = 0
    for b in balls:
        if b["is_wicket"]:
            part_runs = part_balls = 0
            continue
        part_runs += b["runs_bat"] + b["extras"]
        part_balls += b["extra_type"] not in ("wide", "no_ball")
    last = balls[-12:]
    lp["partnership"] = {"runs": part_runs, "balls": part_balls}
    lp["momentum_last_12_balls"] = {"runs": sum(b["runs_bat"] + b["extras"] for b in last), "wickets": sum(b["is_wicket"] for b in last)}
    return lp

def signals(c, mid):
    r = get_match(c, mid)
    pm = engine.predict_match(c, mid)
    pm["public_factors"] = engine.public_factors(pm, r["home_name"], r["away_name"])
    out = {"match_id": mid, "data_origin": r["data_origin"], "pre_match": pm,
           "projected_first_innings": engine.projected_first_innings(c, mid),
           "projected_second_innings": engine.projected_second_innings(c, mid), "live": current_live(c, r)}
    inn = c.execute("SELECT * FROM innings WHERE match_id=? AND is_super_over=0 ORDER BY innings_no DESC LIMIT 1", (mid,)).fetchone()
    if inn:
        per_over = {o + 1: runs for o, runs in c.execute("""SELECT over_no, SUM(runs_bat+extras) FROM ball_events WHERE match_id=? AND innings_no=?
                                                             GROUP BY over_no""", (mid, inn["innings_no"]))}
        out["over_by_over"] = engine.over_projection(r["format"], inn["runs"], inn["wickets"], inn["legal_balls"], inn["max_balls"], per_over)
        out["wicket_impact"] = engine.wicket_impact(r["format"], inn["innings_no"], inn["runs"], inn["wickets"], inn["legal_balls"], inn["target"], inn["max_balls"])
    lw = c.execute("SELECT id FROM predictions WHERE match_id=? AND prediction_type='live_winner' ORDER BY id LIMIT 1", (mid,)).fetchone()
    out["live_history"] = rows(c.execute("SELECT version_no,predicted_team_id,confidence,score_snapshot,created_at FROM prediction_versions WHERE prediction_id=? ORDER BY version_no", (lw[0],))) if lw else []
    # turning points: biggest swings between consecutive live versions
    hist = out["live_history"]
    swings = []
    for a, b in zip(hist, hist[1:]):
        pa = (a["confidence"] if a["predicted_team_id"] == r["home_team_id"] else 100 - a["confidence"])
        pb = (b["confidence"] if b["predicted_team_id"] == r["home_team_id"] else 100 - b["confidence"])
        swings.append({"at": b["score_snapshot"], "home_swing": round(pb - pa, 1), "created_at": b["created_at"]})
    out["turning_points"] = sorted(swings, key=lambda s: -abs(s["home_swing"]))[:5]
    return out

def master_list(c, q):
    """ADMIN ONLY. Actual results master (not predictions): Match | Home | Away | Toss | Winner.
    Toss cell = toss winner; its code is 'won' (green) if that team went on to win the match, 'lost' (red)
    if it lost, 'unknown' (grey) while there is no winner. Winner cell = match winner (green) or None (grey dash)."""
    d = dataset(q)
    where, args = [origin_sql(d)], []
    if qv(q, "competition_id"):
        where.append("m.competition_id=?"); args.append(int_id(qv(q, "competition_id"), "competition_id"))
    out = []
    for serial, r in enumerate(c.execute(MATCH_SQL + " WHERE " + " AND ".join(where) + " ORDER BY m.start_utc, m.id", args).fetchall(), 1):
        teams = {r["home_team_id"]: ("H", r["home_code"] if r["home_code_ok"] else None, r["home_name"]),
                 r["away_team_id"]: ("A", r["away_code"] if r["away_code_ok"] else None, r["away_name"])}

        def cell(team_id, outcome):
            side, code, name = teams[team_id]
            return {"side": side, "code": code, "name": name, "outcome": outcome}
        winner = r["winner_team_id"] if r["result_type"] in ("win", "tie_super_over", "awarded") else None
        toss = None
        if r["toss_winner_id"]:
            toss = cell(r["toss_winner_id"], "unknown" if not winner else ("won" if winner == r["toss_winner_id"] else "lost"))
        num = (r["match_no"] or "").strip()
        out.append({"match_id": r["id"], "match": "%02d" % int(num) if num.isdigit() else (num or "%02d" % serial),
                    "start_utc": r["start_utc"], "competition": r["competition"], "status": r["status"], "result_type": r["result_type"],
                    "home": {"side": "H", "code": r["home_code"] if r["home_code_ok"] else None, "name": r["home_name"]},
                    "away": {"side": "A", "code": r["away_code"] if r["away_code_ok"] else None, "name": r["away_name"]},
                    "toss": toss, "winner": cell(winner, "won") if winner else None})
    return {"columns": ["Match", "Home", "Away", "Toss", "Winner"], "dataset": d, "items": out,
            "meaning": "actual results; predictions are kept in separate immutable records"}

def prediction_register(c, q):
    """ADMIN ONLY. Every non-draft and draft prediction with its evaluation and publication state."""
    limit, offset = page(q)
    where, args = [origin_sql(dataset(q))], []
    for k, col in (("match_id", "p.match_id"), ("status", "p.status"), ("source_type", "p.source_type")):
        if qv(q, k):
            where.append(col + "=?"); args.append(qv(q, k))
    if qv(q, "published") in ("0", "1"):
        where.append(("" if qv(q, "published") == "1" else "NOT ") + "EXISTS(SELECT 1 FROM prediction_publications pp WHERE pp.prediction_id=p.id)")
    sql = """FROM predictions p JOIN matches m ON m.id=p.match_id JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
             LEFT JOIN teams t ON t.id=p.predicted_team_id LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
             LEFT JOIN prediction_publications pp ON pp.prediction_id=p.id LEFT JOIN expert_profiles x ON x.id=p.expert_id WHERE """ + " AND ".join(where)
    items = rows(c.execute("""SELECT p.id,p.match_id,h.name AS home,a.name AS away,m.start_utc,p.source_type,x.display_name AS expert,p.prediction_type,
                              t.name AS predicted_team,p.predicted_value,p.confidence,p.status,p.created_at,p.locked_at,e.result AS evaluation,
                              pp.published_at """ + sql + " ORDER BY m.start_utc DESC, p.id DESC LIMIT ? OFFSET ?", args + [limit, offset]))
    return {"items": items, "total": c.execute("SELECT COUNT(*) " + sql, args).fetchone()[0], "limit": limit, "offset": offset}

def experts(c, q, who=None):
    limit, offset = page(q)
    acc = engine.accuracy(c, published_only=not is_admin(who))["by_expert"]
    items = rows(c.execute("""SELECT x.id,x.display_name,x.bio,x.contact_url,x.verified,x.verified_at,x.language_code,co.name AS country,
                              (SELECT COUNT(*) FROM expert_follows f WHERE f.expert_id=x.id) AS followers
                              FROM expert_profiles x LEFT JOIN countries co ON co.id=x.country_id ORDER BY x.verified DESC,x.id LIMIT ? OFFSET ?""",
                           (limit, offset)))
    for e in items:
        e["accuracy"] = acc.get(e["display_name"], engine.tally([]))
    items.sort(key=lambda e: (-(e["verified"]), -(e["accuracy"]["accuracy"] or -1), -e["accuracy"]["settled"]))
    for i, e in enumerate(items, 1 + offset):
        e["rank"] = i
    return {"items": items, "total": c.execute("SELECT COUNT(*) FROM expert_profiles").fetchone()[0], "limit": limit, "offset": offset}

def expert_history(c, eid, q, who=None):
    limit, offset = page(q)
    x = c.execute("SELECT * FROM expert_profiles WHERE id=?", (eid,)).fetchone()
    if not x:
        raise ApiError(404, "NOT_FOUND", "expert not found")
    pubf = "" if is_admin(who) else "AND p.id IN (SELECT prediction_id FROM prediction_publications)"
    items = rows(c.execute("""SELECT p.id,p.match_id,p.prediction_type,p.predicted_team_id,t.name AS predicted_team,p.confidence,p.explanation,
                              p.created_at,p.locked_at,e.result AS evaluation,e.rule FROM predictions p LEFT JOIN teams t ON t.id=p.predicted_team_id
                              LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                              WHERE p.expert_id=? AND p.status<>'draft' %s ORDER BY p.created_at DESC LIMIT ? OFFSET ?""" % pubf, (eid, limit, offset)))
    res = [r[0] or "pending" for r in c.execute("""SELECT e.result FROM predictions p LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id
                                                    AND e.superseded_at IS NULL WHERE p.expert_id=? AND p.status<>'draft' %s""" % pubf, (eid,))]
    return {"expert": dict(x), "summary": engine.tally(res), "items": items, "limit": limit, "offset": offset}

# ------------------------------------------------------------------ writes
PRED_TYPES = ("toss", "winner", "first_innings_score", "second_innings_score", "live_winner")

def create_prediction(c, who, d, model=False, allow_unverified_expert=False):
    mid = int_id(d.get("match_id"), "match_id")
    m = get_match(c, mid)
    kind = d.get("prediction_type")
    if kind not in PRED_TYPES:
        raise bad("prediction_type must be one of " + ", ".join(PRED_TYPES))
    expert_id = None
    if who["role"] != "admin":
        x = c.execute("SELECT * FROM expert_profiles WHERE user_id=?", (who["user_id"],)).fetchone()
        if not x or (not x["verified"] and not allow_unverified_expert):
            raise ApiError(403, "FORBIDDEN", "only verified experts or admins can publish predictions")
        expert_id = x["id"]
    elif not model:
        if d.get("expert_id") is None:
            raise bad("expert_id required: admins publish on behalf of an expert profile (model picks use /admin/matches/{id}/model-prediction)")
        expert_id = int_id(d["expert_id"], "expert_id")
        if not c.execute("SELECT 1 FROM expert_profiles WHERE id=?", (expert_id,)).fetchone():
            raise bad("unknown expert_id")
    team = d.get("predicted_team_id")
    value = d.get("predicted_value")
    if kind in ("toss", "winner", "live_winner"):
        team = int_id(team, "predicted_team_id")
        if team not in (m["home_team_id"], m["away_team_id"]):
            raise bad("predicted_team_id must be the home or away team of this match")
        value = None
    else:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise bad("predicted_value (runs) is required for score predictions")
        if not 0 <= value <= 1000:
            raise bad("predicted_value out of range")
        team = None
    conf = d.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            raise bad("confidence must be a number")
        if not 0 <= conf <= 100:
            raise bad("confidence must be between 0 and 100")
    expl = (d.get("explanation") or "").strip()[:2000] or None
    origin = "demo" if m["data_origin"] == "demo" else "verified"
    started = engine.pdt(m["start_utc"]) <= engine.pdt(now())
    if kind != "live_winner" and started:
        raise ApiError(409, "MATCH_STARTED", "pre-match predictions close at the scheduled start time")
    source_type = "expert" if expert_id else "model"
    model_id = None if expert_id else engine.model_params(c)[0]["id"]
    if kind == "live_winner":
        if m["status"] != "live":
            raise ApiError(409, "NOT_LIVE", "live predictions need a live match")
        p = c.execute("SELECT * FROM predictions WHERE match_id=? AND prediction_type='live_winner' AND source_type=? AND expert_id IS ?",
                      (mid, source_type, expert_id)).fetchone()
        if not p:
            c.execute("""INSERT INTO predictions(prediction_uid,match_id,source_type,expert_id,model_version_id,prediction_type,predicted_team_id,
                         confidence,explanation,created_at,locked_at,status,data_origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,'locked',?)""",
                      (str(uuid.uuid4()), mid, source_type, expert_id, model_id, kind, team, conf, expl, now(), now(), origin))
            p = c.execute("SELECT * FROM predictions WHERE id=last_insert_rowid()").fetchone()
        v = add_version(c, p["id"], team, None, conf, d.get("score_snapshot"), None)
        audit(c, who["actor"], "prediction.live_version", "prediction", p["id"], d)
        return {"prediction_id": p["id"], "version_no": v, "status": "locked"}
    lock = bool(d.get("lock", True))
    ts = now()
    c.execute("""INSERT INTO predictions(prediction_uid,match_id,source_type,expert_id,model_version_id,prediction_type,predicted_team_id,predicted_value,
                 confidence,explanation,factors_json,score_snapshot,created_at,locked_at,status,data_origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (str(uuid.uuid4()), mid, source_type, expert_id, model_id, kind, team, value, conf, expl,
               json.dumps(d.get("factors")) if d.get("factors") else None, d.get("score_snapshot"), ts, ts if lock else None,
               "locked" if lock else "draft", origin))
    pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    engine.reevaluate_match(c, mid)
    audit(c, who["actor"], "prediction.create", "prediction", pid, d)
    return {"prediction_id": pid, "status": "locked" if lock else "draft", "locked_at": ts if lock else None}

def add_version(c, pid, team, value, conf, snapshot, factors):
    n = c.execute("SELECT COALESCE(MAX(version_no),0)+1 FROM prediction_versions WHERE prediction_id=?", (pid,)).fetchone()[0]
    c.execute("""INSERT INTO prediction_versions(prediction_id,version_no,predicted_team_id,predicted_value,confidence,factors_json,score_snapshot,created_at)
                 VALUES(?,?,?,?,?,?,?,?)""", (pid, n, team, value, conf, json.dumps(factors) if factors else None, snapshot, now()))
    return n

def lock_prediction(c, who, pid):
    p = c.execute("SELECT p.*,m.start_utc FROM predictions p JOIN matches m ON m.id=p.match_id WHERE p.id=?", (pid,)).fetchone()
    if not p:
        raise ApiError(404, "NOT_FOUND", "prediction not found")
    if who["role"] != "admin":
        x = c.execute("SELECT id FROM expert_profiles WHERE user_id=?", (who["user_id"],)).fetchone()
        if not x or x[0] != p["expert_id"]:
            raise ApiError(403, "FORBIDDEN", "not your prediction")
    if p["status"] != "draft":
        raise ApiError(409, "ALREADY_LOCKED", "prediction already locked")
    if engine.pdt(p["start_utc"]) <= engine.pdt(now()):
        raise ApiError(409, "MATCH_STARTED", "cannot lock after the scheduled start")
    c.execute("UPDATE predictions SET status='locked',locked_at=? WHERE id=?", (now(), pid))
    engine.reevaluate_match(c, p["match_id"])
    audit(c, who["actor"], "prediction.lock", "prediction", pid, {})
    return {"prediction_id": pid, "status": "locked"}

def model_prediction(c, who, mid):
    m = get_match(c, mid)
    if engine.pdt(m["start_utc"]) <= engine.pdt(now()):
        raise ApiError(409, "MATCH_STARTED", "model pre-match predictions close at the scheduled start time")
    res = engine.predict_match(c, mid)
    out = []
    for kind, team, conf in (("winner", res["predicted_team_id"], res["confidence"]),):
        if c.execute("SELECT 1 FROM predictions WHERE match_id=? AND source_type='model' AND prediction_type=? AND model_version_id=?",
                     (mid, kind, res["model_version_id"])).fetchone():
            raise ApiError(409, "DUPLICATE", "this model version already predicted this match")
        expl = "Model %s: home %.1f%% / away %.1f%% from %d verified matches." % (
            res["model"], res["home_win_probability"], res["away_win_probability"], res["history_matches_used"])
        out.append(create_prediction(c, who, {"match_id": mid, "prediction_type": kind, "predicted_team_id": team, "confidence": conf,
                                              "explanation": expl, "factors": res["factors"], "lock": True}, model=True))
    proj = engine.projected_first_innings(c, mid)
    if proj["available"]:
        out.append(create_prediction(c, who, {"match_id": mid, "prediction_type": "first_innings_score", "predicted_value": proj["projected"],
                                              "explanation": "Venue average of %d first innings (IQR %d-%d)" % (proj["samples"], proj["low"], proj["high"]), "lock": True}, model=True))
    return {"model": res, "stored": out}

MODEL_PARAM_KEYS = ("form_window", "form_weight", "h2h_weight", "home_weight", "venue_weight", "laplace")

def admin_model_version(c, who, d):
    ver = str(d.get("version") or "").strip()
    if not re.fullmatch(r"[0-9A-Za-z.\-]{1,20}", ver):
        raise bad("version required (letters, digits, dot, dash)")
    p = d.get("params")
    if not isinstance(p, dict) or set(p) != set(MODEL_PARAM_KEYS):
        raise bad("params must contain exactly: " + ", ".join(MODEL_PARAM_KEYS))
    for k, v in p.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 100:
            raise bad(k + " must be a number between 0 and 100")
    if not 1 <= p["form_window"] <= 50 or p["laplace"] <= 0:
        raise bad("form_window must be 1..50 and laplace > 0")
    try:
        c.execute("INSERT INTO model_versions(name,version,description,params_json,created_at) VALUES('sh-baseline',?,?,?,?)",
                  (ver, (d.get("description") or "admin tuned").strip()[:500], json.dumps(p), now()))
    except sqlite3.IntegrityError:
        raise ApiError(409, "DUPLICATE", "model version already exists")
    mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(c, who["actor"], "model.version", "model_version", mid, {"version": ver})  # weights deliberately not copied to the audit text
    return {"model_version_id": mid, "version": ver, "active": True}

def get_or_create(c, table, key_cols, values, extra=None):
    cols = list(key_cols) + list((extra or {}).keys())
    vals = [values[k] for k in key_cols] + list((extra or {}).values())
    c.execute("INSERT OR IGNORE INTO %s(%s) VALUES(%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), vals)
    return c.execute("SELECT id FROM %s WHERE %s" % (table, " AND ".join(k + " IS ?" for k in key_cols)), [values[k] for k in key_cols]).fetchone()[0]

CODE_RE = re.compile(r"^[A-Z0-9]{2,5}$")

def admin_team(c, who, d):
    name = (d.get("name") or "").strip()
    if not name:
        raise bad("name required")
    code = (d.get("short_code") or "").strip().upper() or None
    if code and not CODE_RE.match(code):
        raise bad("short_code must be 2-5 capital letters/digits")
    old = c.execute("SELECT * FROM teams WHERE name=?", (name,)).fetchone()
    if code:
        clash = c.execute("SELECT name FROM teams WHERE short_code=? AND name<>?", (code, name)).fetchone()
        if clash:
            raise ApiError(409, "DUPLICATE", "short code %s already used by %s" % (code, clash[0]))
    if old:
        c.execute("UPDATE teams SET short_code=COALESCE(?,short_code), short_code_approved=?, gender=COALESCE(?,gender) WHERE id=?",
                  (code, 1 if d.get("approve_code", True) and (code or old["short_code"]) else 0, d.get("gender"), old["id"]))
        tid = old["id"]
    else:
        c.execute("INSERT INTO teams(name,short_code,short_code_approved,gender) VALUES(?,?,?,?)",
                  (name, code, 1 if code and d.get("approve_code", True) else 0, d.get("gender")))
        tid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(c, who["actor"], "team.upsert", "team", tid, d, dict(old) if old else None)
    return {"team_id": tid}

def admin_match(c, who, d):
    for k in ("competition", "home", "away", "start_utc", "source"):
        if not str(d.get(k) or "").strip():
            raise bad("missing " + k)
    if d["home"].strip() == d["away"].strip():
        raise bad("teams must differ")
    try:
        st = engine.pdt(d["start_utc"])
    except ValueError:
        raise bad("start_utc must be ISO-8601")
    if "Z" not in d["start_utc"] and "+" not in d["start_utc"][10:] and "-" not in d["start_utc"][10:]:
        raise bad("start_utc must include a timezone")
    fmt = d.get("format", "T20")
    origin = d.get("data_origin", "verified")
    if origin not in ("verified", "imported", "demo"):
        raise bad("invalid data_origin")
    comp = get_or_create(c, "competitions", ["name"], {"name": d["competition"].strip()}, {"source": d["source"], "data_origin": origin})
    season = get_or_create(c, "seasons", ["competition_id", "name"], {"competition_id": comp, "name": str(d.get("season") or st.year)})
    venue = get_or_create(c, "venues", ["name", "city"], {"name": d["venue"].strip(), "city": (d.get("city") or "").strip()}) if d.get("venue") else None
    h = get_or_create(c, "teams", ["name"], {"name": d["home"].strip()})
    a = get_or_create(c, "teams", ["name"], {"name": d["away"].strip()})
    if d.get("provider") and d.get("provider_id"):
        ex = c.execute("SELECT local_id FROM data_provider_syncs WHERE provider=? AND provider_entity='match' AND provider_id=?",
                       (d["provider"], str(d["provider_id"]))).fetchone()
        if ex:
            return {"match_id": ex[0], "status": "duplicate_provider_id"}
    st_iso = st.isoformat()
    ex = c.execute("SELECT id FROM matches WHERE competition_id=? AND home_team_id=? AND away_team_id=? AND start_utc=?", (comp, h, a, st_iso)).fetchone()
    if ex:
        mid, status = ex[0], "duplicate"
    else:
        try:
            c.execute("""INSERT INTO matches(competition_id,season_id,venue_id,home_team_id,away_team_id,match_no,format,start_utc,source,data_origin,
                         weather,pitch_report,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (comp, season, venue, h, a, d.get("match_no"), fmt, st_iso, d["source"], origin, d.get("weather"), d.get("pitch_report"), now(), now()))
        except sqlite3.IntegrityError as e:
            raise bad(str(e))
        mid, status = c.execute("SELECT last_insert_rowid()").fetchone()[0], "created"
        audit(c, who["actor"], "match.create", "match", mid, d)
    if d.get("provider") and d.get("provider_id"):
        c.execute("INSERT OR IGNORE INTO data_provider_syncs(provider,provider_entity,provider_id,local_table,local_id,synced_at) VALUES(?,?,?,?,?,?)",
                  (d["provider"], "match", str(d["provider_id"]), "matches", mid, now()))
    return {"match_id": mid, "status": status}

# ------------------------------------------------------------------ SH Universal Cricket Data Bridge
def bridge_status(c):
    import cricketdata
    jobs = []
    for j in c.execute("SELECT * FROM collector_jobs ORDER BY name"):
        d = dict(j)
        d["config"] = json.loads(d.pop("config_json") or "{}")
        d["config"].pop("catalogue", None) if len(d["config"].get("catalogue", [])) > 40 else None
        d["recent"] = rows(c.execute("SELECT started_at,finished_at,status,summary,error FROM collector_log WHERE job=? ORDER BY id DESC LIMIT 5", (j["name"],)))
        jobs.append(d)
    counts = {p: c.execute("SELECT COUNT(*) FROM data_provider_syncs WHERE provider=? AND provider_entity='match'", (p,)).fetchone()[0]
              for p in ("cricsheet", "owner_sheets", "cricketdata")}
    suspects = rows(c.execute("""SELECT m1.id AS match_a, m2.id AS match_b, substr(m1.start_utc,1,10) AS day, h.name AS team_1, a.name AS team_2
        FROM matches m1 JOIN matches m2 ON m2.id>m1.id AND substr(m2.start_utc,1,10)=substr(m1.start_utc,1,10)
         AND ((m2.home_team_id=m1.home_team_id AND m2.away_team_id=m1.away_team_id) OR (m2.home_team_id=m1.away_team_id AND m2.away_team_id=m1.home_team_id))
        JOIN teams h ON h.id=m1.home_team_id JOIN teams a ON a.id=m1.away_team_id
        WHERE m1.data_origin<>'demo' AND m2.data_origin<>'demo' LIMIT 50"""))
    return {"jobs": jobs, "matches_by_source": counts,
            "cricketdata": dict(key_configured=bool(cricketdata.key()), hits_used_today=cricketdata.hits_used(c), day_utc=cricketdata.today(),
                                plan_reported_limit=cricketdata.plan_limit(c), plan_override=cricketdata.plan_override(c),
                                effective={k: v for k, v in cricketdata.auto(c, {}).items() if k != "budget"} | {"budget": (lambda b: "unlimited" if b >= 10 ** 9 else b)(cricketdata.auto(c, {})["budget"])},
                                live_refresh_seconds=(10 if cricketdata.unlimited(c) else 60 if cricketdata.auto(c, {})["paid"] else None)),
            "possible_duplicates": suspects,
            "duplicate_rule": "Matches from different sources are never merged automatically; same day and same two teams are listed here for review.",
            "sources": rows(c.execute("SELECT key,name,adapter,permission,last_check,last_ok,last_error FROM source_registry ORDER BY adapter DESC, key"))}

def bridge_public_status(c):
    out = []
    for r in c.execute("SELECT key,name,url,historical,live,ball_by_ball,license,adapter,permission FROM source_registry WHERE adapter='implemented' ORDER BY key"):
        d = dict(r)
        j = c.execute("SELECT last_run_at,last_status FROM collector_jobs WHERE name LIKE ? ORDER BY last_run_at DESC LIMIT 1", (r["key"].split("_")[0] + "%",)).fetchone()
        d["last_run_at"], d["last_status"] = (j[0], j[1]) if j else (None, None)
        d["matches"] = c.execute("SELECT COUNT(*) FROM data_provider_syncs WHERE provider=? AND provider_entity='match'", (r["key"],)).fetchone()[0]
        out.append(d)
    return {"items": out, "coverage_note": "Coverage is limited to the sources listed. Worldwide live coverage is not claimed."}

def cricket_extra(c, mid, what, q):
    if what == "deliveries":
        limit, offset = page(q)
        return {"items": rows(c.execute("""SELECT b.innings_no,b.over_no,b.ball_in_over,b.seq,bt.name AS batter,bw.name AS bowler,b.runs_bat,b.extras,
                  b.extra_type,b.is_wicket,b.wicket_kind,b.source FROM ball_events b LEFT JOIN players bt ON bt.id=b.batter_id
                  LEFT JOIN players bw ON bw.id=b.bowler_id WHERE b.match_id=? ORDER BY b.innings_no,b.seq LIMIT ? OFFSET ?""", (mid, limit, offset))),
                "total": c.execute("SELECT COUNT(*) FROM ball_events WHERE match_id=?", (mid,)).fetchone()[0]}
    if what in ("xi", "squads"):
        return {"items": rows(c.execute("""SELECT x.team_id,t.name AS team,p.id AS player_id,p.name,x.batting_order,p.identity_status FROM playing_xi x
                  JOIN players p ON p.id=x.player_id JOIN teams t ON t.id=x.team_id WHERE x.match_id=? ORDER BY x.team_id,x.batting_order""", (mid,))),
                "note": "Squads are the announced/recorded playing XI where the source provides it."}
    inn = rows(c.execute("SELECT innings_no,batting_team_id,runs,wickets,legal_balls,target,is_super_over FROM innings WHERE match_id=? ORDER BY innings_no", (mid,)))
    for i in inn:
        b = c.execute("""SELECT COALESCE(SUM(runs_bat),0), COALESCE(SUM(extras),0), SUM(extra_type='wide'), SUM(extra_type='no_ball'),
                         SUM(runs_bat=4), SUM(runs_bat=6) FROM ball_events WHERE match_id=? AND innings_no=?""", (mid, i["innings_no"])).fetchone()
        i.update(bat_runs=b[0], extras=b[1], wides=b[2] or 0, no_balls=b[3] or 0, fours=b[4] or 0, sixes=b[5] or 0,
                 run_rate=round(i["runs"] * 6 / i["legal_balls"], 2) if i["legal_balls"] else None,
                 deliveries_match_total=(b[0] + b[1] == i["runs"]) if b[0] + b[1] else None)
    return {"innings": inn}

def registry_list(c, what, q):
    limit, offset = page(q)
    like = "%" + (qv(q, "q") or "")[:60] + "%"
    if what == "sources":
        return {"items": rows(c.execute("SELECT * FROM source_registry ORDER BY adapter DESC, permission, key"))}
    if what == "countries":
        items = rows(c.execute("""SELECT co.*, (SELECT COUNT(*) FROM competitions WHERE country_id=co.id) AS competitions,
                     (SELECT COUNT(*) FROM competitions WHERE country_id=co.id AND verification='verified') AS verified_competitions
                     FROM countries co WHERE co.name LIKE ? ORDER BY (co.icc_status='full') DESC, co.icc_status, co.name LIMIT ? OFFSET ?""", (like, limit, offset)))
        return {"items": items, "total": c.execute("SELECT COUNT(*) FROM countries").fetchone()[0],
                "icc_note": "ICC: 111 members (12 Full, 99 Associate) as of July 2026. Countries not yet researched are marked so."}
    items = rows(c.execute("""SELECT cp.id,cp.name,cp.category,cp.division,cp.format,cp.level,cp.region,co.name AS country,cp.verification,cp.activity,
                 cp.registry_source,cp.source,(SELECT COUNT(*) FROM matches WHERE competition_id=cp.id) AS matches,
                 (SELECT COUNT(*) FROM seasons WHERE competition_id=cp.id) AS seasons FROM competitions cp LEFT JOIN countries co ON co.id=cp.country_id
                 WHERE cp.name LIKE ? ORDER BY matches DESC, cp.name LIMIT ? OFFSET ?""", (like, limit, offset)))
    return {"items": items, "total": c.execute("SELECT COUNT(*) FROM competitions").fetchone()[0]}

def admin_bridge_job(c, who, name, action, d):
    import scheduler
    if not c.execute("SELECT 1 FROM collector_jobs WHERE name=?", (name,)).fetchone():
        raise ApiError(404, "NOT_FOUND", "unknown job")
    if action in ("enable", "disable"):
        c.execute("UPDATE collector_jobs SET enabled=? WHERE name=?", (1 if action == "enable" else 0, name))
    elif action == "config":
        cfg = json.loads(c.execute("SELECT config_json FROM collector_jobs WHERE name=?", (name,)).fetchone()[0])
        if "daily_budget" in d:
            b = d["daily_budget"]
            if not isinstance(b, int) or not 0 <= b <= 100000:
                raise bad("daily_budget must be a whole number")
            cfg["daily_budget"] = b
        if "interval_minutes" in d:
            iv = d["interval_minutes"]
            if not isinstance(iv, int) or not 5 <= iv <= 43200:
                raise bad("interval_minutes must be between 5 and 43200")
            c.execute("UPDATE collector_jobs SET interval_minutes=? WHERE name=?", (iv, name))
        c.execute("UPDATE collector_jobs SET config_json=? WHERE name=?", (json.dumps(cfg), name))
    elif action == "run":
        c.execute("UPDATE collector_jobs SET next_run_at=? WHERE name=?", (now(), name))
        c.commit()
        threading.Thread(target=scheduler.run_job, args=(DB_FN, name), daemon=True).start()
    else:
        raise bad("action must be run, enable, disable or config")
    audit(c, who["actor"], "bridge.job." + action, "collector_job", name, d)
    return {"job": name, "action": action, "status": "started" if action == "run" else "saved"}

OWNER_MASTER = Path(__file__).parent / "data" / "owner_master_abu_dhabi_t10.json"

def admin_owner_master(c, who, d):
    """ADMIN ONLY. Load the owner's Abu Dhabi T10 actual-results master (Match | Home | Away | Toss | Winner).
    Codes like 'H-UB' / 'A-EE'; None = not yet known. Stored as imported, user-supplied, not independently verified.
    The list has no dates, so the admin gives the first start; later matches are spaced by gap_hours only to keep their order."""
    src = json.loads(OWNER_MASTER.read_text())
    rows = d.get("rows") or src["rows"]
    if not str(d.get("start_utc") or "").strip():
        raise bad("start_utc required (first match start, with timezone); the master list has no dates")
    try:
        base = engine.pdt(d["start_utc"])
    except ValueError:
        raise bad("start_utc must be ISO-8601")
    gap = float(d.get("gap_hours", 3))
    comp = (d.get("competition") or src["competition"]).strip()
    source = src["source"] + "; dates are placeholders in match-number order"
    parsed = []
    for n, r in enumerate(rows, 1):
        if not isinstance(r, list) or len(r) != 4:
            raise bad("row %d must be [home, away, toss, winner]" % n)
        home, away, toss, win = r

        def side(v, what):
            if v is None:
                return None
            m = re.fullmatch(r"([HA])-([A-Z0-9]{2,5})", str(v))
            if not m or m.group(2) != (home if m.group(1) == "H" else away):
                raise bad("row %d %s '%s' must be H-<home code> or A-<away code>" % (n, what, v))
            return m.group(1)
        parsed.append((n, home, away, side(toss, "toss"), side(win, "winner")))
    summary = {"matches": len(parsed), "with_result": sum(1 for p in parsed if p[4]), "pending": sum(1 for p in parsed if not p[4])}
    if d.get("dry_run"):
        return dict(summary, dry_run=True)
    for code in sorted({x for p in parsed for x in p[1:3]}):
        clash = c.execute("SELECT name FROM teams WHERE short_code=? AND name<>?", (code, code)).fetchone()
        if clash:
            raise ApiError(409, "DUPLICATE", "short code %s already used by %s" % (code, clash[0]))
        c.execute("INSERT INTO teams(name,short_code,short_code_approved) VALUES(?,?,1) ON CONFLICT(name) DO UPDATE SET short_code=excluded.short_code, short_code_approved=1", (code, code))
    out = {"created": 0, "duplicate": 0, "toss_recorded": 0, "results_recorded": 0}
    for n, home, away, ts, ws in parsed:
        st = (base + timedelta(hours=gap * (n - 1))).isoformat()
        r = admin_match(c, who, {"competition": comp, "home": home, "away": away, "start_utc": st, "source": source, "format": src["format"],
                                 "match_no": "%02d" % n, "data_origin": "imported", "provider": "owner-master", "provider_id": "%s#%02d" % (comp, n)})
        out["created" if r["status"] == "created" else "duplicate"] += 1
        m = get_match(c, r["match_id"])
        ids = {"H": m["home_team_id"], "A": m["away_team_id"]}
        if ts and not c.execute("SELECT 1 FROM toss_results WHERE match_id=?", (m["id"],)).fetchone():
            c.execute("INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,NULL,?,?)", (m["id"], ids[ts], source, now()))
            out["toss_recorded"] += 1
        if ws and not c.execute("SELECT 1 FROM match_results WHERE match_id=?", (m["id"],)).fetchone():
            admin_result(c, who, {"match_id": m["id"], "result_type": "win", "winner_team_id": ids[ws], "source": source})
            out["results_recorded"] += 1
    audit(c, who["actor"], "owner_master.import", "competition", 0, {"competition": comp, "rows": len(parsed)})
    return dict(out, **summary, competition=comp, note=src["note"], verification="user-supplied, not independently verified")

def admin_toss(c, who, d):
    mid = int_id(d.get("match_id"), "match_id")
    m = get_match(c, mid)
    team = int_id(d.get("winner_team_id"), "winner_team_id")
    if team not in (m["home_team_id"], m["away_team_id"]):
        raise bad("toss winner must be a team in this match")
    if d.get("decision") not in ("bat", "bowl"):
        raise bad("decision must be bat or bowl")
    if not (d.get("source") or "").strip():
        raise bad("source required")
    old = c.execute("SELECT * FROM toss_results WHERE match_id=?", (mid,)).fetchone()
    if old and not (d.get("reason") or "").strip():
        raise ApiError(409, "ALREADY_RECORDED", "toss already recorded; send reason to revise")
    c.execute("""INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)
                 ON CONFLICT(match_id) DO UPDATE SET winner_team_id=excluded.winner_team_id,decision=excluded.decision,source=excluded.source,verified_at=excluded.verified_at""",
              (mid, team, d["decision"], d["source"], now()))
    engine.reevaluate_match(c, mid)
    audit(c, who["actor"], "toss.revise" if old else "toss.record", "match", mid, d, dict(old) if old else None)
    return {"status": "revised" if old else "recorded"}

RESULT_TYPES = ("win", "tie_super_over", "tie", "draw", "no_result", "abandoned", "canceled", "awarded")

def admin_result(c, who, d):
    mid = int_id(d.get("match_id"), "match_id")
    m = get_match(c, mid)
    rt = d.get("result_type")
    if rt not in RESULT_TYPES:
        raise bad("result_type must be one of " + ", ".join(RESULT_TYPES))
    winner = d.get("winner_team_id")
    if rt in ("win", "tie_super_over", "awarded"):
        winner = int_id(winner, "winner_team_id")
        if winner not in (m["home_team_id"], m["away_team_id"]):
            raise bad("winner must be a team in this match")
    elif winner is not None:
        raise bad("%s has no winner (ICC clause 16)" % rt)
    if not (d.get("source") or "").strip():
        raise bad("source required")
    old = c.execute("SELECT * FROM match_results WHERE match_id=?", (mid,)).fetchone()
    if old and not (d.get("reason") or "").strip():
        raise ApiError(409, "ALREADY_RECORDED", "result already recorded; send reason to revise")
    c.execute("""INSERT INTO match_results(match_id,result_type,winner_team_id,margin,method,source,verified_at) VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT(match_id) DO UPDATE SET result_type=excluded.result_type,winner_team_id=excluded.winner_team_id,margin=excluded.margin,
                 method=excluded.method,source=excluded.source,verified_at=excluded.verified_at""",
              (mid, rt, winner, d.get("margin"), d.get("method"), d["source"], now()))
    status = {"win": "completed", "tie_super_over": "completed", "tie": "completed", "draw": "completed", "awarded": "completed",
              "no_result": "no_result", "abandoned": "abandoned", "canceled": "canceled"}[rt]
    c.execute("UPDATE matches SET status=?,updated_at=? WHERE id=?", (status, now(), mid))
    n = engine.reevaluate_match(c, mid)
    audit(c, who["actor"], "result.revise" if old else "result.record", "match", mid, d, dict(old) if old else None)
    return {"status": "revised" if old else "recorded", "evaluations_changed": n}

def admin_ball(c, who, d):
    """Append one delivery; innings totals and the model live prediction update from it."""
    mid = int_id(d.get("match_id"), "match_id")
    m = get_match(c, mid)
    ino = int_id(d.get("innings_no"), "innings_no")
    if ino < 1 or ino > 6:
        raise bad("innings_no must be 1..6")
    et = d.get("extra_type")
    if et not in (None, "wide", "no_ball", "bye", "leg_bye", "penalty"):
        raise bad("invalid extra_type")
    rb, ex = int(d.get("runs_bat", 0)), int(d.get("extras", 0))
    if not 0 <= rb <= 7 or not 0 <= ex <= 7:
        raise bad("runs out of range")
    if et in ("wide", "no_ball") and ex < 1:
        raise bad("a wide or no-ball carries at least 1 extra run (Laws 21-22)")
    inn = c.execute("SELECT * FROM innings WHERE match_id=? AND innings_no=?", (mid, ino)).fetchone()
    if not inn:
        bt = int_id(d.get("batting_team_id"), "batting_team_id")
        if bt not in (m["home_team_id"], m["away_team_id"]):
            raise bad("batting_team_id must be a team in this match")
        c.execute("INSERT INTO innings(match_id,innings_no,batting_team_id,target,max_balls,is_super_over) VALUES(?,?,?,?,?,?)",
                  (mid, ino, bt, d.get("target"), d.get("max_balls") or engine.FORMAT_BALLS.get(m["format"]), 1 if ino > 2 and m["format"] != "Test" else 0))
        inn = c.execute("SELECT * FROM innings WHERE match_id=? AND innings_no=?", (mid, ino)).fetchone()
    if inn["completed"]:
        raise ApiError(409, "INNINGS_CLOSED", "innings already completed")
    seq = int_id(d.get("seq"), "seq")
    legal = et not in ("wide", "no_ball")
    over_no, ball = divmod(inn["legal_balls"], 6)
    try:
        c.execute("""INSERT INTO ball_events(match_id,innings_no,over_no,ball_in_over,seq,batter_id,bowler_id,runs_bat,extras,extra_type,is_wicket,
                     wicket_kind,commentary,source,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (mid, ino, over_no, ball + (1 if legal else 0), seq, d.get("batter_id"), d.get("bowler_id"), rb, ex, et,
                   1 if d.get("is_wicket") else 0, d.get("wicket_kind"), (d.get("commentary") or "")[:500] or None, d.get("source") or "admin", now()))
    except sqlite3.IntegrityError:
        raise ApiError(409, "DUPLICATE", "ball seq %d already recorded for innings %d" % (seq, ino))
    runs = inn["runs"] + rb + ex
    wk = inn["wickets"] + (1 if d.get("is_wicket") else 0)
    lb = inn["legal_balls"] + (1 if legal else 0)
    done = wk >= 10 or (inn["max_balls"] and lb >= inn["max_balls"]) or (inn["target"] and runs >= inn["target"])
    c.execute("UPDATE innings SET runs=?,wickets=?,legal_balls=?,completed=? WHERE id=?", (runs, wk, lb, 1 if done else 0, inn["id"]))
    if m["status"] == "scheduled":
        c.execute("UPDATE matches SET status='live',updated_at=? WHERE id=?", (now(), mid))
    m = get_match(c, mid)
    lv = current_live(c, m)
    if lv and m["status"] == "live":
        team = m["home_team_id"] if lv["home_win_probability"] >= 50 else m["away_team_id"]
        conf = max(lv["home_win_probability"], lv["away_win_probability"])
        p = c.execute("SELECT id FROM predictions WHERE match_id=? AND prediction_type='live_winner' AND source_type='model'", (mid,)).fetchone()
        if not p:
            c.execute("""INSERT INTO predictions(prediction_uid,match_id,source_type,model_version_id,prediction_type,predicted_team_id,confidence,
                         explanation,created_at,locked_at,status,data_origin) VALUES(?,?,'model',?,'live_winner',?,?,?,?,?,'locked',?)""",
                      (str(uuid.uuid4()), mid, engine.model_params(c)[0]["id"], team, conf, "Ball-by-ball live model; every update is a new version.",
                       now(), now(), "demo" if m["data_origin"] == "demo" else "verified"))
            p = c.execute("SELECT last_insert_rowid()").fetchone()
        add_version(c, p[0], team, None, conf, "inn%d %d/%d (%s ov)" % (ino, runs, wk, "%d.%d" % divmod(lb, 6)), lv)
    _own_scorecard(c, mid, ino, d, rb, ex, et, legal)
    if done:
        import cricsheet
        cricsheet.rebuild_player_statistics(c)
    # SH own scoring adapter -> event stream (score, commentary, probability) for SSE subscribers
    names = {m["home_team_id"]: m["home_name"], m["away_team_id"]: m["away_name"]}
    ev = c.execute("""SELECT b.*, bt.name AS batter, bw.name AS bowler, ? AS batting_team_id FROM ball_events b LEFT JOIN players bt ON bt.id=b.batter_id
                      LEFT JOIN players bw ON bw.id=b.bowler_id WHERE b.match_id=? AND b.innings_no=? ORDER BY b.seq""", (inn["batting_team_id"], mid, ino)).fetchall()
    lines = commentary_engine.generate([dict(x) for x in ev], "en", names, inn["max_balls"], {ino: inn["target"]} if inn["target"] else None)
    live.publish(c, mid, "ball", {"innings_no": ino, "seq": seq, "over": "%d.%d" % (over_no, ball + (1 if legal else 0)), "score": "%d/%d" % (runs, wk),
                                   "overs": "%d.%d" % divmod(lb, 6), "runs_bat": rb, "extras": ex, "extra_type": et, "is_wicket": bool(d.get("is_wicket")),
                                   "commentary": lines[-1]["text"] if lines else None, "innings_completed": bool(done)})
    if live_state := current_live(c, m):
        live.publish(c, mid, "probability", {"home_win_probability": live_state["home_win_probability"], "away_win_probability": live_state["away_win_probability"],
                                              "crr": live_state["current_run_rate"], "rrr": live_state.get("required_run_rate")})
    return {"innings_no": ino, "score": "%d/%d" % (runs, wk), "overs": "%d.%d" % divmod(lb, 6), "innings_completed": bool(done), "live": live_state}

def _own_scorecard(c, mid, ino, d, rb, ex, et, legal):
    """Per-ball scorecard maintenance for SH-scored matches (batter and bowler rows)."""
    bid, wid = d.get("batter_id"), d.get("bowler_id")
    if bid:
        c.execute("INSERT OR IGNORE INTO scorecards(match_id,innings_no,player_id,runs,balls,fours,sixes) VALUES(?,?,?,0,0,0,0)", (mid, ino, bid))
        c.execute("""UPDATE scorecards SET runs=COALESCE(runs,0)+?, balls=COALESCE(balls,0)+?, fours=COALESCE(fours,0)+?, sixes=COALESCE(sixes,0)+?,
                     dismissal=COALESCE(?, dismissal) WHERE match_id=? AND innings_no=? AND player_id=?""",
                  (rb, 0 if et == "wide" else 1, 1 if rb == 4 else 0, 1 if rb == 6 else 0,
                   (d.get("wicket_kind") or "out") if d.get("is_wicket") else None, mid, ino, bid))
    if wid:
        c.execute("INSERT OR IGNORE INTO scorecards(match_id,innings_no,player_id,overs_bowled,runs_conceded,wickets) VALUES(?,?,?,'0.0',0,0)", (mid, ino, wid))
        row = c.execute("SELECT overs_bowled FROM scorecards WHERE match_id=? AND innings_no=? AND player_id=?", (mid, ino, wid)).fetchone()
        o, b = (int(x) for x in (row[0] or "0.0").split(".")) if row and row[0] and "." in row[0] else (0, 0)
        balls = o * 6 + b + (1 if legal else 0)
        conceded = rb + (ex if et in ("wide", "no_ball") else 0)
        credited = 1 if d.get("is_wicket") and d.get("wicket_kind") in ("bowled", "caught", "lbw", "stumped", "hit wicket", "caught and bowled") else 0
        c.execute("""UPDATE scorecards SET overs_bowled=?, runs_conceded=COALESCE(runs_conceded,0)+?, wickets=COALESCE(wickets,0)+? WHERE match_id=? AND innings_no=? AND player_id=?""",
                  ("%d.%d" % divmod(balls, 6), conceded, credited, mid, ino, wid))

def admin_expert(c, who, d):
    name = (d.get("display_name") or "").strip()
    if not name:
        raise bad("display_name required")
    uid = None
    if d.get("username"):
        r = c.execute("SELECT user_id FROM accounts WHERE username=? AND status='active'", (str(d["username"]).lower(),)).fetchone()
        if not r:
            raise bad("unknown username")
        uid = r[0]
        c.execute("UPDATE users SET role='expert' WHERE id=? AND role='user'", (uid,))
        c.execute("UPDATE accounts SET account_type='tipster' WHERE user_id=? AND account_type='viewer'", (uid,))
    elif d.get("phone"):
        if not re.fullmatch(r"[0-9]{10,15}", str(d["phone"])):
            raise bad("invalid phone")
        c.execute("INSERT OR IGNORE INTO users(phone,created_at) VALUES(?,?)", (d["phone"], now()))
        uid = c.execute("SELECT id FROM users WHERE phone=?", (d["phone"],)).fetchone()[0]
        c.execute("UPDATE users SET role='expert' WHERE id=? AND role='user'", (uid,))
    country = get_or_create(c, "countries", ["name"], {"name": d["country"].strip()}) if d.get("country") else None
    lang = d.get("language_code") or "en"
    if not c.execute("SELECT 1 FROM languages WHERE code=?", (lang,)).fetchone():
        raise bad("unknown language_code")
    contact = d.get("contact_url")
    if contact and not str(contact).startswith("https://"):
        raise bad("contact_url must be https")
    try:
        c.execute("INSERT INTO expert_profiles(user_id,display_name,country_id,language_code,bio,contact_url,created_at) VALUES(?,?,?,?,?,?,?)",
                  (uid, name, country, lang, d.get("bio"), contact, now()))
    except sqlite3.IntegrityError:
        raise ApiError(409, "DUPLICATE", "this user already has an expert profile")
    eid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(c, who["actor"], "expert.create", "expert", eid, d)
    return {"expert_id": eid, "verified": False}

def admin_verify_expert(c, who, eid, d):
    x = c.execute("SELECT * FROM expert_profiles WHERE id=?", (eid,)).fetchone()
    if not x:
        raise ApiError(404, "NOT_FOUND", "expert not found")
    v = 1 if d.get("verified", True) else 0
    c.execute("UPDATE expert_profiles SET verified=?,verified_at=? WHERE id=?", (v, now() if v else None, eid))
    audit(c, who["actor"], "expert.verify" if v else "expert.unverify", "expert", eid, d, dict(x))
    return {"expert_id": eid, "verified": bool(v)}

def preferences(c, who, d=None):
    if not who["user_id"]:
        raise ApiError(400, "USER_REQUIRED", "preferences belong to a logged-in user")
    c.execute("INSERT OR IGNORE INTO user_preferences(user_id,updated_at) VALUES(?,?)", (who["user_id"], now()))
    if d is not None:
        cur = dict(c.execute("SELECT * FROM user_preferences WHERE user_id=?", (who["user_id"],)).fetchone())
        if "language_code" in d:
            if not c.execute("SELECT 1 FROM languages WHERE code=?", (d["language_code"],)).fetchone():
                raise bad("unknown language_code")
            cur["language_code"] = d["language_code"]
        if "theme" in d:
            if d["theme"] not in ("dark", "light"):
                raise bad("theme must be dark or light")
            cur["theme"] = d["theme"]
        for k in ("favorite_team_ids", "favorite_competition_ids"):
            if k in d:
                if not isinstance(d[k], list) or not all(isinstance(x, int) for x in d[k]) or len(d[k]) > 50:
                    raise bad(k + " must be a list of up to 50 integers")
                cur[k] = json.dumps(d[k])
        c.execute("UPDATE user_preferences SET language_code=?,theme=?,favorite_team_ids=?,favorite_competition_ids=?,updated_at=? WHERE user_id=?",
                  (cur["language_code"], cur["theme"], cur["favorite_team_ids"], cur["favorite_competition_ids"], now(), who["user_id"]))
    r = dict(c.execute("SELECT * FROM user_preferences WHERE user_id=?", (who["user_id"],)).fetchone())
    for k in ("favorite_team_ids", "favorite_competition_ids"):
        r[k] = json.loads(r[k])
    return r

def demo_seed(c, who):
    """Clearly-labelled DEMO data so screens can be reviewed. Never counted in headline accuracy."""
    comp = get_or_create(c, "competitions", ["name"], {"name": "SH Demo League"}, {"source": "SH demo generator", "data_origin": "demo"})
    teams = [("Demo Ultra Blasters", "DUB"), ("Demo Eagle Eyes", "DEE"), ("Demo Royal Rhinos", "DRR"), ("Demo Coastal Kings", "DCK")]
    ids = [admin_team(c, who, {"name": n, "short_code": s})["team_id"] for n, s in teams]
    fixtures = [(0, 1, "2026-01-05T14:00:00+00:00", 0, "bat", 0), (2, 3, "2026-01-06T14:00:00+00:00", 3, "bowl", 3),
                (1, 2, "2026-01-07T14:00:00+00:00", 1, "bowl", 2), (3, 0, "2026-01-08T14:00:00+00:00", 0, "bat", None),
                (0, 2, "2030-01-09T14:00:00+00:00", None, None, None)]
    made = []
    for n, (hi, ai, st, toss, dec, win) in enumerate(fixtures, 1):
        r = admin_match(c, who, {"competition": "SH Demo League", "season": "Demo", "home": teams[hi][0], "away": teams[ai][0], "start_utc": st,
                                 "source": "SH demo generator", "data_origin": "demo", "match_no": "D%d" % n, "venue": "Demo Oval", "format": "T10"})
        mid = r["match_id"]
        made.append(mid)
        if r["status"] != "created":
            continue
        ts = engine.pdt(st)
        pre = (ts.replace(hour=10)).isoformat()
        for kind, pick in (("toss", ids[hi]), ("winner", ids[hi] if n % 2 else ids[ai])):
            c.execute("""INSERT INTO predictions(prediction_uid,match_id,source_type,model_version_id,prediction_type,predicted_team_id,confidence,
                         explanation,created_at,locked_at,status,data_origin) VALUES(?,?,'model',?,?,?,?,?,?,?,'locked','demo')""",
                      (str(uuid.uuid4()), mid, engine.model_params(c)[0]["id"], kind, pick, 55.0, "Demo prediction", pre, pre))
        if toss is not None:
            c.execute("INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)",
                      (mid, ids[toss], dec, "SH demo generator", now()))
        if n <= 3:
            c.execute("INSERT INTO match_results(match_id,result_type,winner_team_id,source,verified_at) VALUES(?,?,?,?,?)",
                      (mid, "win", ids[win], "SH demo generator", now()))
            c.execute("UPDATE matches SET status='completed' WHERE id=?", (mid,))
        elif n == 4:
            c.execute("INSERT INTO match_results(match_id,result_type,winner_team_id,source,verified_at) VALUES(?,?,?,?,?)",
                      (mid, "no_result", None, "SH demo generator", now()))
            c.execute("UPDATE matches SET status='no_result' WHERE id=?", (mid,))
        engine.reevaluate_match(c, mid)
    audit(c, who["actor"], "demo.seed", "match", ",".join(map(str, made)), {})
    return {"demo_match_ids": made, "data_origin": "demo"}

def monitor(c):
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {"migrations": rows(c.execute("SELECT * FROM schema_migrations")),
            "counts": {t: c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0] for t in tables if t != "login_sessions"},
            "time_utc": now()}

# ------------------------------------------------------------------ publishing
def publish(c, who, pid, d):
    p = c.execute("SELECT * FROM predictions WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ApiError(404, "NOT_FOUND", "prediction not found")
    if not p["locked_at"]:
        raise ApiError(409, "NOT_LOCKED", "lock the prediction before publishing")
    if c.execute("SELECT 1 FROM prediction_publications WHERE prediction_id=?", (pid,)).fetchone():
        raise ApiError(409, "ALREADY_PUBLISHED", "already published")
    note = (d.get("public_note") or "").strip()[:1000] or None
    c.execute("INSERT INTO prediction_publications(prediction_id,published_at,published_by,public_note) VALUES(?,?,?,?)", (pid, now(), who["actor"], note))
    audit(c, who["actor"], "prediction.publish", "prediction", pid, d)
    return {"prediction_id": pid, "published": True}

def unpublish(c, who, pid, d):
    if not (d.get("reason") or "").strip():
        raise bad("reason required to unpublish")
    old = c.execute("SELECT * FROM prediction_publications WHERE prediction_id=?", (pid,)).fetchone()
    if not old:
        raise ApiError(404, "NOT_FOUND", "prediction is not published")
    c.execute("DELETE FROM prediction_publications WHERE prediction_id=?", (pid,))
    audit(c, who["actor"], "prediction.unpublish", "prediction", pid, d, dict(old))
    return {"prediction_id": pid, "published": False}

# ------------------------------------------------------------------ match centre extras
def graphs(c, mid):
    get_match(c, mid)
    out = []
    for inn in c.execute("SELECT * FROM innings WHERE match_id=? ORDER BY innings_no", (mid,)).fetchall():
        per = c.execute("""SELECT over_no, SUM(runs_bat+extras) AS runs, SUM(is_wicket) AS wkts FROM ball_events WHERE match_id=? AND innings_no=?
                           GROUP BY over_no ORDER BY over_no""", (mid, inn["innings_no"])).fetchall()
        cum, worm = 0, []
        for r in per:
            cum += r["runs"]
            worm.append(cum)
        out.append({"innings_no": inn["innings_no"], "batting_team_id": inn["batting_team_id"],
                    "manhattan": [{"over": r["over_no"] + 1, "runs": r["runs"], "wickets": r["wkts"]} for r in per],
                    "worm": worm, "run_rate": [round(w * 1.0 / (i + 1), 2) for i, w in enumerate(worm)]})
    return {"match_id": mid, "innings": out}

def partnerships(c, mid):
    get_match(c, mid)
    out = []
    for inn in c.execute("SELECT innings_no FROM innings WHERE match_id=? ORDER BY innings_no", (mid,)).fetchall():
        parts, cur, wk = [], {"runs": 0, "balls": 0}, 0
        for b in c.execute("SELECT * FROM ball_events WHERE match_id=? AND innings_no=? ORDER BY seq", (mid, inn[0])):
            cur["runs"] += b["runs_bat"] + b["extras"]
            cur["balls"] += b["extra_type"] not in ("wide", "no_ball")
            if b["is_wicket"]:
                wk += 1
                parts.append(dict(cur, wicket=wk, ended="%d.%d" % (b["over_no"], b["ball_in_over"])))
                cur = {"runs": 0, "balls": 0}
        if cur["balls"] or cur["runs"]:
            parts.append(dict(cur, wicket=wk + 1, ended=None))
        out.append({"innings_no": inn[0], "partnerships": parts})
    return {"match_id": mid, "innings": out}

def fall_of_wickets(c, mid):
    get_match(c, mid)
    out = []
    for inn in c.execute("SELECT innings_no FROM innings WHERE match_id=? ORDER BY innings_no", (mid,)).fetchall():
        tot, wk, fow = 0, 0, []
        for b in c.execute("""SELECT b.*, p.name AS batter FROM ball_events b LEFT JOIN players p ON p.id=b.batter_id
                              WHERE b.match_id=? AND b.innings_no=? ORDER BY b.seq""", (mid, inn[0])):
            tot += b["runs_bat"] + b["extras"]
            if b["is_wicket"]:
                wk += 1
                fow.append({"wicket": wk, "score": tot, "over": "%d.%d" % (b["over_no"], b["ball_in_over"]), "batter": b["batter"], "how": b["wicket_kind"]})
        out.append({"innings_no": inn[0], "fall_of_wickets": fow})
    return {"match_id": mid, "innings": out}

def final_result(c, mid):
    r = get_match(c, mid)
    names = {r["home_team_id"]: r["home_name"], r["away_team_id"]: r["away_name"]}
    if not r["result_type"]:
        return {"match_id": mid, "available": False, "status": r["status"]}
    text = {"win": "%s won", "awarded": "%s awarded the match", "tie_super_over": "Tie; %s won the Super Over"}.get(r["result_type"])
    return {"match_id": mid, "available": True, "result_type": r["result_type"], "winner_team_id": r["winner_team_id"],
            "summary": (text % names[r["winner_team_id"]]) if text else {"tie": "Match tied", "no_result": "No result", "abandoned": "Match abandoned", "canceled": "Match canceled"}[r["result_type"]],
            "margin": r["margin"], "method": r["method"]}

# ------------------------------------------------------------------ admin: players, squads, XI, stats, edits
def admin_player(c, who, d):
    name = (d.get("name") or "").strip()
    if not name:
        raise bad("name required")
    if d.get("role") not in ("batter", "bowler", "all_rounder", "wicket_keeper"):
        raise bad("role must be batter, bowler, all_rounder or wicket_keeper")
    pid = d.get("player_id")
    if pid:
        c.execute("UPDATE players SET name=?,role=?,batting_style=?,bowling_style=? WHERE id=?", (name, d["role"], d.get("batting_style"), d.get("bowling_style"), int_id(pid)))
    else:
        c.execute("INSERT INTO players(name,role,batting_style,bowling_style) VALUES(?,?,?,?)", (name, d["role"], d.get("batting_style"), d.get("bowling_style")))
        pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(c, who["actor"], "player.upsert", "player", pid, d)
    return {"player_id": pid}

def admin_player_stats(c, who, d):
    pid = int_id(d.get("player_id"), "player_id")
    if not c.execute("SELECT 1 FROM players WHERE id=?", (pid,)).fetchone():
        raise ApiError(404, "NOT_FOUND", "player not found")
    fmt = d.get("format")
    if fmt not in ("T10", "T20", "The Hundred", "ODI", "List A", "Test", "First-class", "Other"):
        raise bad("invalid format")
    vals = []
    for k in ("matches", "runs", "batting_avg", "strike_rate", "wickets", "economy"):
        v = d.get(k)
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
            raise bad(k + " must be a non-negative number")
        vals.append(v)
    if not (d.get("source") or "").strip():
        raise bad("source required")
    c.execute("""INSERT INTO player_statistics(player_id,format,matches,runs,batting_avg,strike_rate,wickets,economy,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(player_id,format) DO UPDATE SET matches=excluded.matches,runs=excluded.runs,batting_avg=excluded.batting_avg,
                 strike_rate=excluded.strike_rate,wickets=excluded.wickets,economy=excluded.economy,updated_at=excluded.updated_at""", [pid, fmt] + vals + [now()])
    audit(c, who["actor"], "player.stats", "player", pid, d)
    return {"player_id": pid, "format": fmt}

def admin_lineup(c, who, mid, d, table):
    m = get_match(c, mid)
    team = int_id(d.get("team_id"), "team_id")
    if team not in (m["home_team_id"], m["away_team_id"]):
        raise bad("team must play in this match")
    players = d.get("players")
    if not isinstance(players, list) or not 1 <= len(players) <= 25:
        raise bad("players must be a list of 1..25 entries")
    if table == "playing_xi" and len([p for p in players if not p.get("is_impact_sub")]) > 11:
        raise bad("a Playing XI has at most 11 players (plus impact substitutes)")
    old = rows(c.execute("SELECT * FROM %s WHERE match_id=? AND team_id=?" % table, (mid, team)))
    c.execute("DELETE FROM %s WHERE match_id=? AND team_id=?" % table, (mid, team))
    for i, p in enumerate(players, 1):
        pid = int_id(p.get("player_id"), "player_id")
        if not c.execute("SELECT 1 FROM players WHERE id=?", (pid,)).fetchone():
            raise bad("unknown player_id %d" % pid)
        if table == "playing_xi":
            c.execute("INSERT INTO playing_xi(match_id,team_id,player_id,batting_order,is_captain,is_keeper,is_impact_sub) VALUES(?,?,?,?,?,?,?)",
                      (mid, team, pid, p.get("batting_order", i), 1 if p.get("is_captain") else 0, 1 if p.get("is_keeper") else 0, 1 if p.get("is_impact_sub") else 0))
        else:
            c.execute("INSERT INTO match_squads(match_id,team_id,player_id) VALUES(?,?,?)", (mid, team, pid))
    audit(c, who["actor"], table + ".set", "match", mid, d, {"previous": old})
    return {"match_id": mid, "team_id": team, "count": len(players)}

def admin_scorecard_row(c, who, mid, d):
    get_match(c, mid)
    pid = int_id(d.get("player_id"), "player_id")
    ino = int_id(d.get("innings_no"), "innings_no")
    cols = ("runs", "balls", "fours", "sixes", "dismissal", "overs_bowled", "maidens", "runs_conceded", "wickets")
    c.execute("""INSERT INTO scorecards(match_id,innings_no,player_id,%s) VALUES(?,?,?,%s)
                 ON CONFLICT(match_id,innings_no,player_id) DO UPDATE SET %s""" % (",".join(cols), ",".join("?" * len(cols)), ",".join("%s=excluded.%s" % (k, k) for k in cols)),
              [mid, ino, pid] + [d.get(k) for k in cols])
    audit(c, who["actor"], "scorecard.row", "match", mid, d)
    return {"match_id": mid, "player_id": pid}

EDITABLE = ("venue", "city", "match_no", "weather", "pitch_report", "format", "start_utc", "status")

def admin_edit_match(c, who, mid, d):
    m = get_match(c, mid)
    changes = {k: d[k] for k in EDITABLE if k in d}
    if not changes:
        raise bad("nothing to change; editable: " + ", ".join(EDITABLE))
    if "start_utc" in changes:
        locked = c.execute("SELECT COUNT(*) FROM predictions WHERE match_id=? AND locked_at IS NOT NULL AND prediction_type<>'live_winner'", (mid,)).fetchone()[0]
        if locked and not (d.get("reason") or "").strip():
            raise ApiError(409, "HAS_LOCKED_PREDICTIONS", "locked predictions exist; send a reason to change the start time (eligibility is re-checked)")
        try:
            changes["start_utc"] = engine.pdt(changes["start_utc"]).isoformat()
        except ValueError:
            raise bad("start_utc must be ISO-8601 with timezone")
    if "format" in changes and changes["format"] not in ("T10", "T20", "The Hundred", "ODI", "List A", "Test", "First-class", "Other"):
        raise bad("invalid format")
    if "status" in changes and changes["status"] not in ("scheduled", "live"):
        raise bad("status can only be set to scheduled or live here; record results through Result Verification")
    venue = changes.pop("venue", None)
    city = changes.pop("city", "")
    if venue:
        changes["venue_id"] = get_or_create(c, "venues", ["name", "city"], {"name": venue.strip(), "city": (city or "").strip()})
    old = dict(c.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone())
    c.execute("UPDATE matches SET %s, updated_at=? WHERE id=?" % ",".join(k + "=?" for k in changes), list(changes.values()) + [now(), mid])
    engine.reevaluate_match(c, mid)
    audit(c, who["actor"], "match.edit", "match", mid, d, old)
    return {"match_id": mid, "changed": sorted(changes)}

# ------------------------------------------------------------------ admin: users, settings, providers, import
def admin_users(c, q):
    limit, offset = page(q)
    return {"items": rows(c.execute("""SELECT u.id, substr(u.phone,1,2)||'******'||substr(u.phone,-2) AS phone_masked, u.role, u.created_at,
                                       x.id AS expert_id, x.verified FROM users u LEFT JOIN expert_profiles x ON x.user_id=u.id ORDER BY u.id DESC LIMIT ? OFFSET ?""", (limit, offset))),
            "total": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "note": "Admin rights come only from the admin key. Roles here: user or expert."}

def admin_set_role(c, who, uid, d):
    if d.get("role") not in ("user", "expert"):
        raise bad("role must be user or expert (admin access is only through the admin key)")
    old = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not old:
        raise ApiError(404, "NOT_FOUND", "user not found")
    c.execute("UPDATE users SET role=? WHERE id=?", (d["role"], uid))
    audit(c, who["actor"], "user.role", "user", uid, d, {"role": old["role"]})
    return {"user_id": uid, "role": d["role"]}

SETTINGS = {"public_site_enabled": ("0", "1"), "default_language": None, "viewer_sees_demo_option": ("0", "1")}

def admin_settings(c, who, d=None):
    if d is not None:
        for k, v in d.items():
            if k not in SETTINGS:
                raise bad("unknown setting " + k)
            v = str(v)
            if SETTINGS[k] and v not in SETTINGS[k]:
                raise bad("%s must be one of %s" % (k, ", ".join(SETTINGS[k])))
            if k == "default_language" and not c.execute("SELECT 1 FROM languages WHERE code=?", (v,)).fetchone():
                raise bad("unknown language")
            old = c.execute("SELECT value FROM system_settings WHERE key=?", (k,)).fetchone()
            c.execute("INSERT INTO system_settings(key,value,updated_at,updated_by) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                      (k, v, now(), who["actor"]))
            audit(c, who["actor"], "setting.update", "setting", k, {k: v}, {"value": old[0]} if old else None)
    return {"items": rows(c.execute("SELECT * FROM system_settings ORDER BY key"))}

def admin_provider(c, who, name, d):
    p = c.execute("SELECT * FROM data_providers WHERE name=?", (name,)).fetchone()
    if not p:
        raise ApiError(404, "NOT_FOUND", "unknown provider")
    if "enabled" in d:
        if name == "licensed_feed" and d["enabled"]:
            cfg = json.loads(p["config_json"] or "{}")
            if not cfg.get("contract_reference"):
                raise ApiError(409, "NOT_CONFIGURED", "record the licence/contract reference before enabling a licensed feed")
        c.execute("UPDATE data_providers SET enabled=? WHERE name=?", (1 if d["enabled"] else 0, name))
    if "config" in d:
        cfg = d["config"]
        if not isinstance(cfg, dict) or any(k.lower() in ("api_key", "key", "token", "secret", "password") for k in cfg):
            raise bad("config must be an object without secrets; keep API keys in server environment variables")
        c.execute("UPDATE data_providers SET config_json=? WHERE name=?", (json.dumps(cfg), name))
    audit(c, who["actor"], "provider.update", "provider", name, d, dict(p))
    return dict(c.execute("SELECT * FROM data_providers WHERE name=?", (name,)).fetchone())

IMPORT_COLS = ("competition", "season", "match_no", "home", "away", "start_utc", "venue", "format", "source",
               "toss_winner", "toss_decision", "result_type", "winner", "margin", "method")

def admin_import(c, who, d):
    """Verified manual entry: CSV text with header row. Fixtures are created (deduplicated); toss/result
    columns, when filled, are recorded through the same verified endpoints. Dry run by default."""
    import csv, io
    text = d.get("csv") or ""
    if not 1 <= len(text) <= 500000:
        raise bad("csv text required (max 500 kB)")
    rd = csv.DictReader(io.StringIO(text))
    if not rd.fieldnames or not {"competition", "home", "away", "start_utc", "source"} <= {f.strip() for f in rd.fieldnames}:
        raise bad("header must include competition, home, away, start_utc, source")
    commit = bool(d.get("commit"))
    report = {"rows": 0, "created": 0, "duplicates": 0, "results": 0, "errors": []}
    c.execute("SAVEPOINT import_all")  # outer savepoint: a dry run rolls everything back
    for n, row in enumerate(rd, 2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        report["rows"] += 1
        sp = "imp_%d" % n
        c.execute("SAVEPOINT " + sp)
        try:
            r = admin_match(c, who, {k: row.get(k) or None for k in ("competition", "season", "match_no", "home", "away", "start_utc", "venue", "source")}
                            | {"format": row.get("format") or "T20", "data_origin": "verified"})
            report["created" if r["status"] == "created" else "duplicates"] += 1
            mid = r["match_id"]
            m = get_match(c, mid)
            names = {m["home_name"]: m["home_team_id"], m["away_name"]: m["away_team_id"]}
            if row.get("toss_winner"):
                if row["toss_winner"] not in names:
                    raise ValueError("toss_winner must be the home or away name")
                if not c.execute("SELECT 1 FROM toss_results WHERE match_id=?", (mid,)).fetchone():
                    admin_toss(c, who, {"match_id": mid, "winner_team_id": names[row["toss_winner"]], "decision": (row.get("toss_decision") or "").lower(), "source": row["source"]})
            if row.get("result_type"):
                if not c.execute("SELECT 1 FROM match_results WHERE match_id=?", (mid,)).fetchone():
                    w = names.get(row.get("winner")) if row.get("winner") else None
                    if row.get("winner") and w is None:
                        raise ValueError("winner must be the home or away name")
                    admin_result(c, who, {"match_id": mid, "result_type": row["result_type"], "winner_team_id": w, "margin": row.get("margin") or None,
                                          "method": row.get("method") or None, "source": row["source"]})
                    report["results"] += 1
            c.execute("RELEASE " + sp)
        except (ApiError, ValueError, KeyError, sqlite3.DatabaseError) as e:
            c.execute("ROLLBACK TO " + sp); c.execute("RELEASE " + sp)
            report["errors"].append({"line": n, "error": getattr(e, "message", str(e))})
    report["committed"] = commit
    if not commit:
        c.execute("ROLLBACK TO import_all")
        c.execute("RELEASE import_all")
        return report
    c.execute("RELEASE import_all")
    audit(c, who["actor"], "data.import", "import", report["rows"], {k: v for k, v in report.items() if k != "errors"})
    gateway.clear_cache()
    return report

class _DryRun(Exception):
    def __init__(self, report):
        self.report = report

# ------------------------------------------------------------------ data gateway (public read contract)
def gw_fixtures(c, q):
    d = dataset(q)
    return gateway.cached(("fx", d, qv(q, "competition_id")), gateway.TTL["default"], lambda: {
        "items": [match_out(r) for r in c.execute(MATCH_SQL + " WHERE " + origin_sql(d) + " AND m.status IN ('scheduled','live')"
                                                  + (" AND m.competition_id=%d" % int_id(qv(q, "competition_id")) if qv(q, "competition_id") else "")
                                                  + " ORDER BY m.start_utc LIMIT 200")], "dataset": d})

def gw_results(c, q):
    d = dataset(q)
    return gateway.cached(("res", d), gateway.TTL["default"], lambda: {
        "items": [match_out(r) for r in c.execute(MATCH_SQL + " WHERE " + origin_sql(d) + " AND r.result_type IS NOT NULL ORDER BY m.start_utc DESC LIMIT 200")], "dataset": d})

def gw_live(c, q):
    d = dataset(q)
    def build():
        out = []
        for r in c.execute(MATCH_SQL + " WHERE " + origin_sql(d) + " AND m.status='live' ORDER BY m.start_utc").fetchall():
            x = match_out(r)
            x["live"] = current_live(c, r)
            out.append(x)
        return {"items": out, "dataset": d, "note": "Live data exists only for matches scored in SH PREDICTION or received from a licensed feed."}
    return gateway.cached(("live", d), gateway.TTL["live"], build)

def gw_team_stats(c, tid):
    t = c.execute("SELECT * FROM teams WHERE id=?", (tid,)).fetchone()
    if not t:
        raise ApiError(404, "NOT_FOUND", "team not found")
    rs = c.execute("""SELECT r.winner_team_id, r.result_type FROM matches m JOIN match_results r ON r.match_id=m.id
                      WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.data_origin<>'demo' ORDER BY m.start_utc""", (tid, tid)).fetchall()
    won = sum(1 for r in rs if r[0] == tid)
    nr = sum(1 for r in rs if r[1] in ("no_result", "abandoned", "canceled", "tie"))
    return {"team_id": tid, "name": t["name"], "played": len(rs), "won": won, "lost": len(rs) - won - nr, "no_result_or_tie": nr,
            "last5": "".join("W" if r[0] == tid else ("L" if r[0] else "N") for r in rs[-5:]), "dataset": "verified"}

def gw_venue_stats(c, vid):
    v = c.execute("SELECT * FROM venues WHERE id=?", (vid,)).fetchone()
    if not v:
        raise ApiError(404, "NOT_FOUND", "venue not found")
    st = engine.analytics(c)["venue"].get(v["name"], {"matches": 0})
    avg = c.execute("""SELECT i.innings_no, AVG(i.runs), COUNT(*) FROM innings i JOIN matches m ON m.id=i.match_id WHERE m.venue_id=? AND i.completed=1
                       AND i.is_super_over=0 AND m.data_origin<>'demo' GROUP BY i.innings_no""", (vid,)).fetchall()
    return {"venue_id": vid, "name": v["name"], "results": st, "average_totals": {"innings_%d" % a[0]: {"average": round(a[1]), "innings": a[2]} for a in avg}}

def gw_player_stats(c, pid):
    p = c.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ApiError(404, "NOT_FOUND", "player not found")
    return {"player": dict(p), "statistics": rows(c.execute("SELECT * FROM player_statistics WHERE player_id=?", (pid,)))}

def gw_history(c, q):
    limit, offset = page(q)
    where, args = [origin_sql(dataset(q)), "r.result_type IS NOT NULL"], []
    if qv(q, "team_id"):
        t = int_id(qv(q, "team_id"), "team_id"); where.append("(m.home_team_id=? OR m.away_team_id=?)"); args += [t, t]
    if qv(q, "from"):
        where.append("m.start_utc>=?"); args.append(qv(q, "from"))
    if qv(q, "to"):
        where.append("m.start_utc<=?"); args.append(qv(q, "to"))
    sql = MATCH_SQL + " WHERE " + " AND ".join(where)
    return {"items": [match_out(r) for r in c.execute(sql + " ORDER BY m.start_utc DESC LIMIT ? OFFSET ?", args + [limit, offset])],
            "total": c.execute("SELECT COUNT(*) FROM (" + sql + ")", args).fetchone()[0], "limit": limit, "offset": offset}

def admin_dashboard(c):
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
    acc = engine.accuracy(c)["overall"]
    return {"matches": {"scheduled": one("SELECT COUNT(*) FROM matches WHERE status='scheduled' AND data_origin<>'demo'"),
                        "live": one("SELECT COUNT(*) FROM matches WHERE status='live' AND data_origin<>'demo'"),
                        "awaiting_result": one("SELECT COUNT(*) FROM matches m WHERE m.status IN ('scheduled','live') AND m.start_utc<? AND m.data_origin<>'demo'", now()),
                        "completed": one("SELECT COUNT(*) FROM matches WHERE status NOT IN ('scheduled','live') AND data_origin<>'demo'")},
            "predictions": {"drafts": one("SELECT COUNT(*) FROM predictions WHERE status='draft'"),
                            "locked_unpublished": one("SELECT COUNT(*) FROM predictions p WHERE p.locked_at IS NOT NULL AND p.id NOT IN (SELECT prediction_id FROM prediction_publications)"),
                            "published": one("SELECT COUNT(*) FROM prediction_publications")},
            "experts": {"total": one("SELECT COUNT(*) FROM expert_profiles"), "unverified": one("SELECT COUNT(*) FROM expert_profiles WHERE verified=0")},
            "users": one("SELECT COUNT(*) FROM users"), "accuracy": acc,
            "providers": rows(c.execute("SELECT name,kind,enabled,last_sync_at,last_status FROM data_providers")),
            "pending_migrations": pending(c)}

# ------------------------------------------------------------------ router
SYSTEM_PATHS = (("admin", "system", "status"), ("admin", "system", "migrate"))

def route(h, method, path, q, body_fn):
    c = h_db()
    try:
        ip = h.headers.get("X-Forwarded-For", h.client_address[0]).split(",")[0].strip()
        if not rate_ok(ip):
            raise ApiError(429, "RATE_LIMITED", "too many requests; try again in a minute")
        parts = [p for p in path.split("/") if p][2:]  # strip api, v1
        if method == "GET" and len(parts) == 2 and parts[0] == "i18n":
            return 200, i18n_bundle(c, parts[1])
        todo = pending(c)
        if todo:
            # Database changes are applied only by an admin action that backs up first (never on a page load).
            if tuple(parts) not in SYSTEM_PATHS:
                raise ApiError(503, "MIGRATION_PENDING", "SH PREDICTION v1 is being prepared; an admin must run the database migration")
            if not h.admin_ok():
                raise ApiError(403, "FORBIDDEN", "admin token required")
            who = {"user_id": None, "role": "admin", "actor": "admin-token"}
        else:
            bridge_legacy(c)
            engine.reevaluate_all(c)
            c.commit()
            who = identity(h, c)
            if parts[:1] == ["admin"] and not is_admin(who):
                raise ApiError(403, "FORBIDDEN", "admin token required")
        res = dispatch(c, who, method, parts, q, body_fn, h)
        c.commit()
        if method != "GET":
            live.wake()
        return res
    except (auth.AuthError, media.MediaError, social.SocialError) as e:
        c.rollback()
        return e.status, {"error": {"code": e.code, "message": e.message}}
    except _DryRun as e:
        c.rollback()
        return 200, e.report
    except ApiError as e:
        c.rollback()
        return e.status, {"error": {"code": e.code, "message": e.message}}
    except sqlite3.DatabaseError as e:
        c.rollback()
        if any(w in str(e) for w in ("immutable", "append-only", "cannot be deleted", "only locked")):
            return 409, {"error": {"code": "IMMUTABLE", "message": str(e)}}
        return 400, {"error": {"code": "DATABASE_ERROR", "message": str(e)}}
    except (LookupError,) as e:
        c.rollback()
        return 404, {"error": {"code": "NOT_FOUND", "message": str(e).strip("'")}}
    except PermissionError as e:
        c.rollback()
        return 409, {"error": {"code": "DISABLED", "message": str(e)}}
    except (ValueError, TypeError) as e:
        c.rollback()
        return 400, {"error": {"code": "VALIDATION_ERROR", "message": str(e)}}
    finally:
        c.close()

def i18n_bundle(c, code):
    if code not in {l[0] for l in i18n_langs()}:
        raise ApiError(404, "NOT_FOUND", "unknown language")
    st = i18n.bundle(code)
    cov = i18n.coverage(code)
    rtl = next(l[3] for l in i18n_langs() if l[0] == code)
    return {"code": code, "rtl": bool(rtl), "coverage_percent": cov, "ui_complete": cov == 100,
            "fallback_note": None if cov == 100 else "Some text is shown in English until translated", "strings": st}

def i18n_langs():
    import schema
    return schema.LANGS

DB_FN = None  # set by main.py to its db() so the legacy tables exist too

def h_db():
    c = DB_FN()
    c.execute("PRAGMA foreign_keys=ON")
    return c

def need_user(who):
    if not who or not who.get("user_id"):
        raise ApiError(401, "UNAUTHENTICATED", "login required")

def dispatch(c, who, method, parts, q, body_fn, h=None):
    P = parts
    adm = is_admin(who)
    helpers = {"create_prediction": create_prediction, "signals": signals}
    if P and P[0] in ("auth", "me", "media", "social", "game") and P != ["me", "preferences"]:
        r = api_social.dispatch(c, h, who, method, P, q, body_fn, helpers)
        if r is not None:
            return r
        raise ApiError(404, "NOT_FOUND", "unknown endpoint")
    if method == "GET" and len(P) == 3 and P[0] == "matches" and P[2] in ("community", "replay"):
        mid = int_id(P[1], "match id")
        get_match(c, mid)
        return 200, api_social.match_extras(c, mid, P, q, who, helpers)
    if adm and len(P) >= 2 and P[0] == "admin" and (P[1] in ("social", "media", "mail") or (P[1] == "users" and P[-1] == "verify-email")):
        r = api_social.admin_dispatch(c, who, method, tuple(P[1:]), q, body_fn)
        if r is not None:
            if method != "GET":
                audit(c, who["actor"], "admin." + "/".join(P[1:]), P[1], P[-1], {} if method == "GET" else "see moderation log")
            return r
    if method == "GET":
        # ---------------- public viewer API
        if P == ["languages"]:
            items = []
            for code, name, native, rtl, _ in i18n_langs():
                cov = i18n.coverage(code)
                items.append({"code": code, "name": name, "native_name": native, "rtl": bool(rtl), "coverage_percent": cov, "ui_complete": cov == 100})
            return 200, {"items": sorted(items, key=lambda x: (-x["coverage_percent"], x["name"]))}
        if P and P[0] == "cricket" and len(P) >= 2:
            if P[1:] == ["sources", "status"]:
                return 200, bridge_public_status(c)
            alias = {"playing-xi": "xi"}
            P = P[1:] if P[1] != "matches" or len(P) < 4 else ["matches", P[2], alias.get(P[3], P[3])] + P[4:]
            if len(P) == 3 and P[0] == "matches" and P[2] in ("deliveries", "statistics", "squads", "xi"):
                mid = int_id(P[1], "match id")
                get_match(c, mid)
                return 200, cricket_extra(c, mid, P[2], q)
        if P == ["matches"]:
            return 200, list_matches(c, q)
        if len(P) >= 2 and P[0] == "matches":
            mid = int_id(P[1], "match id")
            if len(P) == 2:
                return 200, match_detail(c, mid)
            sub = {"scorecard": lambda: scorecard(c, mid), "commentary": lambda: commentary(c, mid, q),
                   "predictions": lambda: match_predictions(c, mid, who),
                   "signals": lambda: signals(c, mid) if adm else redact_signals(signals(c, mid)),
                   "graphs": lambda: graphs(c, mid), "partnerships": lambda: partnerships(c, mid),
                   "fall-of-wickets": lambda: fall_of_wickets(c, mid), "result": lambda: final_result(c, mid),
                   "fantasy": lambda: fantasy.suggest(c, mid, qv(q, "rule_set"), store=False),
                   "fantasy-history": lambda: {"items": fantasy.history(c, mid)}}
            if len(P) == 3 and P[2] in sub:
                get_match(c, mid)
                return 200, sub[P[2]]()
        if P == ["sources"]:
            return 200, {"items": [
                {"name": "Cricsheet", "url": "https://cricsheet.org", "licence": "Open Data Commons Attribution License 1.0",
                 "licence_url": cricsheet.LICENSE_URL, "covers": "historical ball-by-ball data (after matches finish; not live)",
                 "matches_imported": c.execute("SELECT COUNT(*) FROM data_provider_syncs WHERE provider='cricsheet' AND provider_entity='match'").fetchone()[0]},
                {"name": "SH PREDICTION verified entry", "covers": "fixtures, tosses, results and live scoring entered by SH admins"},
                {"name": "SH demo generator", "covers": "clearly labelled demo data, never mixed with real data"}]}
        if P == ["competitions"]:
            return 200, {"items": rows(c.execute("SELECT id,name,category,division,format,featured,data_origin FROM competitions ORDER BY featured DESC, category, name"))}
        if P == ["teams"]:
            return 200, {"items": rows(c.execute("SELECT id,name,CASE WHEN short_code_approved=1 THEN short_code END AS short_code,gender FROM teams ORDER BY name"))}
        if P == ["experts"]:
            return 200, experts(c, q, who)
        if len(P) == 3 and P[0] == "experts" and P[2] == "history":
            return 200, expert_history(c, int_id(P[1], "expert id"), q, who)
        if len(P) == 2 and P[0] == "analytics":
            d = dataset(q)
            if P[1] == "accuracy":
                a = engine.accuracy(c, prediction_type=qv(q, "prediction_type"), published_only=not adm, dataset=d)
                if not adm:
                    a["by_model"] = {PUBLIC_MODEL_NAME: engine.tally([r for v in a["by_model"].values() for r in
                                     ["correct"] * v["correct"] + ["incorrect"] * v["incorrect"] + ["pending"] * v["pending"] + ["void"] * v["void"] + ["ineligible"] * v["ineligible"]])}
                return 200, a
            an = {"toss": "toss", "home-away": "home_away", "venue": "venue"}
            if P[1] in an:
                a = engine.analytics(c, dataset=d)
                extra = {"batting_first_vs_chasing": a["batting_first_vs_chasing"]} if P[1] == "toss" else {}
                extra.update({"day_of_week_utc": a["day_of_week_utc"]} if P[1] == "home-away" else {})
                return 200, dict({an[P[1]]: a[an[P[1]]], "sample_matches": a["sample_matches"], "note": a["note"], "dataset": d}, **extra)
        if P[:1] == ["data"]:
            g = {("fixtures",): lambda: gw_fixtures(c, q), ("results",): lambda: gw_results(c, q), ("live",): lambda: gw_live(c, q),
                 ("history",): lambda: gw_history(c, q)}
            if tuple(P[1:]) in g:
                return 200, g[tuple(P[1:])]()
            if len(P) == 3 and P[1] in ("scorecards", "commentary", "squads", "playing-xi"):
                mid = int_id(P[2], "match id")
                if P[1] == "scorecards":
                    return 200, scorecard(c, mid)
                if P[1] == "commentary":
                    return 200, commentary(c, mid, q)
                d = match_detail(c, mid)
                return 200, {"match_id": mid, "items": d["squads"] if P[1] == "squads" else d["playing_xi"]}
            if len(P) == 4 and P[3] == "stats" and P[1] in ("players", "teams", "venues"):
                fn = {"players": gw_player_stats, "teams": gw_team_stats, "venues": gw_venue_stats}[P[1]]
                return 200, fn(c, int_id(P[2]))
        if P == ["me", "preferences"]:
            need_user(who)
            return 200, preferences(c, who)
        # ---------------- admin API (route() already checked the admin token)
        if P[:1] == ["admin"]:
            A = tuple(P[1:])
            if A == ("audit",):
                limit, offset = page(q)
                return 200, {"items": rows(c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))),
                             "total": c.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]}
            simple = {("monitor",): lambda: monitor(c), ("dashboard",): lambda: admin_dashboard(c),
                      ("master-list",): lambda: master_list(c, q), ("predictions",): lambda: prediction_register(c, q),
                      ("users",): lambda: admin_users(c, q), ("settings",): lambda: admin_settings(c, who),
                      ("providers",): lambda: {"items": rows(c.execute("SELECT * FROM data_providers ORDER BY name")),
                                               "runs": rows(c.execute("SELECT * FROM data_sync_runs ORDER BY id DESC LIMIT 20"))},
                      ("calibration",): lambda: engine.backtest(c, dataset=dataset(q)),
                      ("accuracy",): lambda: engine.accuracy(c, dataset=dataset(q)),
                      ("fantasy", "rules"): lambda: {"items": [dict(r, rules=json.loads(r["rules_json"])) for r in c.execute("SELECT * FROM fantasy_rule_sets")]},
                      ("system", "status"): lambda: {"pending": pending(c), "backups": system.backups(_db_path()),
                                                     "applied": rows(c.execute("SELECT * FROM schema_migrations"))
                                                     if c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone() else []}}
            if A in simple:
                return 200, simple[A]()
            if A == ("bridge",):
                return 200, bridge_status(c)
            if A[:1] == ("registry",) and len(A) == 2 and A[1] in ("countries", "competitions", "sources"):
                return 200, registry_list(c, A[1], q)
            if A == ("cricsheet",):
                return 200, {"files": [{"key": k, "file": v[0], "label": v[1]} for k, v in cricsheet.ZIPS.items()],
                             "attribution": cricsheet.ATTRIBUTION, "licence_url": cricsheet.LICENSE_URL,
                             "imported_matches": c.execute("SELECT COUNT(*) FROM data_provider_syncs WHERE provider='cricsheet' AND provider_entity='match'").fetchone()[0],
                             "runs": rows(c.execute("SELECT * FROM data_sync_runs WHERE provider='cricsheet' ORDER BY id DESC LIMIT 10"))}
            if A == ("model-versions",):
                items = rows(c.execute("SELECT * FROM model_versions ORDER BY id DESC"))
                for i in items:
                    i["params"] = json.loads(i.pop("params_json"))
                return 200, {"items": items, "active_id": items[0]["id"] if items else None}
        raise ApiError(404, "NOT_FOUND", "unknown endpoint")
    if method in ("POST", "PUT"):
        d = body_fn()
        if not isinstance(d, dict):
            raise bad("JSON object body required")
        if method == "PUT" and P == ["me", "preferences"]:
            need_user(who)
            return 200, preferences(c, who, d)
        if method != "POST":
            raise ApiError(404, "NOT_FOUND", "unknown endpoint")
        if P == ["assistant"]:
            lang = d.get("language") or "en"
            return 200, assistant.ask(c, d.get("question"), lang, who["user_id"] if who else None)
        if P == ["predictions"]:
            need_user(who) if not adm else None
            if not adm and who["role"] != "expert":
                raise ApiError(403, "FORBIDDEN", "only verified experts or admins can submit predictions")
            return 201, create_prediction(c, who, d)
        if len(P) == 3 and P[0] == "predictions" and P[2] == "lock":
            if not who:
                raise ApiError(401, "UNAUTHENTICATED", "login required")
            return 200, lock_prediction(c, who, int_id(P[1], "prediction id"))
        if len(P) == 3 and P[0] == "experts" and P[2] == "follow":
            need_user(who)
            eid = int_id(P[1], "expert id")
            if not c.execute("SELECT 1 FROM expert_profiles WHERE id=?", (eid,)).fetchone():
                raise ApiError(404, "NOT_FOUND", "expert not found")
            if d.get("follow", True):
                c.execute("INSERT OR IGNORE INTO expert_follows(user_id,expert_id,created_at) VALUES(?,?,?)", (who["user_id"], eid, now()))
            else:
                c.execute("DELETE FROM expert_follows WHERE user_id=? AND expert_id=?", (who["user_id"], eid))
            return 200, {"expert_id": eid, "following": bool(d.get("follow", True))}
        if P[:1] == ["admin"]:
            A = tuple(P[1:])
            flat = {("teams",): admin_team, ("matches",): admin_match, ("toss",): admin_toss, ("results",): admin_result,
                    ("ball-events",): admin_ball, ("experts",): admin_expert, ("players",): admin_player,
                    ("player-stats",): admin_player_stats, ("model-versions",): admin_model_version, ("import",): admin_import, ("owner-master",): admin_owner_master}
            if A in flat:
                return (201 if A == ("model-versions",) else 200), flat[A](c, who, d)
            if A == ("bridge", "plan"):
                mode = d.get("mode")
                if mode not in ("unlimited", "auto"):
                    raise bad("mode must be unlimited or auto")
                until = d.get("until")
                if mode == "unlimited" and not (isinstance(until, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", until)):
                    raise bad("until (YYYY-MM-DD) required for unlimited")
                if mode == "auto":
                    c.execute("DELETE FROM system_settings WHERE key='cricketdata_plan_override'")
                else:
                    c.execute("INSERT INTO system_settings(key,value,updated_at,updated_by) VALUES('cricketdata_plan_override',?,?,?) "
                              "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at,updated_by=excluded.updated_by",
                              (json.dumps({"mode": "unlimited", "until": until}), now(), who["actor"]))
                audit(c, who["actor"], "bridge.plan", "setting", "cricketdata_plan_override", d)
                return 200, {"saved": True}
            if len(A) == 4 and A[:2] == ("bridge", "jobs"):
                return 200, admin_bridge_job(c, who, A[2], A[3], d)
            if A == ("settings",):
                return 200, admin_settings(c, who, d)
            if A == ("cricsheet", "import") or A == ("providers", "cricsheet", "sync"):
                key = d.get("file") or "recent_7"
                if key not in cricsheet.ZIPS:
                    raise bad("file must be one of: " + ", ".join(cricsheet.ZIPS))
                if not c.execute("SELECT enabled FROM data_providers WHERE name='cricsheet'").fetchone()[0]:
                    raise ApiError(409, "DISABLED", "Cricsheet provider is disabled")
                limit = d.get("limit")
                if limit is not None and (not isinstance(limit, int) or not 1 <= limit <= 50000):
                    raise bad("limit must be 1..50000")
                audit(c, who["actor"], "cricsheet.import", "provider", "cricsheet", {"file": key, "limit": limit})
                c.commit()
                try:
                    job, _ = cricsheet.start_job(DB_FN, key, lambda conn: (lambda row: admin_match(conn, {"actor": "cricsheet-import", "role": "admin", "user_id": None}, row)),
                                                 limit=limit, opener=CRICSHEET_OPENER)
                except RuntimeError as e:
                    raise ApiError(409, "BUSY", str(e))
                return 202, job
            if A == ("player-stats", "rebuild"):
                r = cricsheet.rebuild_player_statistics(c)
                audit(c, who["actor"], "player_stats.rebuild", "player_statistics", r["player_format_rows"], {})
                return 200, r
            if A == ("demo-seed",):
                return 200, demo_seed(c, who)
            if A == ("system", "migrate"):
                if d.get("confirm") is not True:
                    raise bad('send {"confirm": true}; a verified backup is taken first')
                r = system.run(c, _db_path())
                if r["status"] != "up_to_date":
                    audit(c, who["actor"], "system.migrate", "database", ",".join(r["applied"]), {"backup": r["backup"]["path"], "checks": r["checks"]})
                return 200, r
            if A == ("fantasy", "rules"):
                R = fantasy.validate_rules(d.get("rules"))
                name = (d.get("name") or "").strip()
                if not name:
                    raise bad("name required")
                c.execute("INSERT INTO fantasy_rule_sets(name,rules_json,created_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET rules_json=excluded.rules_json",
                          (name, json.dumps(R), now()))
                audit(c, who["actor"], "fantasy.rules", "fantasy_rule_set", name, d)
                return 200, {"name": name, "rules": R}
            if len(A) == 3 and A[0] == "experts" and A[2] == "verify":
                return 200, admin_verify_expert(c, who, int_id(A[1], "expert id"), d)
            if len(A) == 3 and A[0] == "users" and A[2] == "role":
                return 200, admin_set_role(c, who, int_id(A[1], "user id"), d)
            if len(A) == 3 and A[0] == "predictions" and A[2] in ("publish", "unpublish", "lock"):
                pid = int_id(A[1], "prediction id")
                return 200, {"publish": publish, "unpublish": unpublish, "lock": lambda c_, w_, p_, d_: lock_prediction(c_, w_, p_)}[A[2]](c, who, pid, d)
            if len(A) == 3 and A[0] == "providers" and A[2] == "sync":
                return 200, gateway.sync(c, A[1], lambda row: admin_match(c, who, row))
            if len(A) == 2 and A[0] == "providers":
                return 200, admin_provider(c, who, A[1], d)
            if len(A) >= 2 and A[0] == "matches":
                mid = int_id(A[1], "match id")
                if len(A) == 2:
                    return 200, admin_edit_match(c, who, mid, d)
                ops = {"model-prediction": lambda: (201, model_prediction(c, who, mid)),
                       "squad": lambda: (200, admin_lineup(c, who, mid, d, "match_squads")),
                       "playing-xi": lambda: (200, admin_lineup(c, who, mid, d, "playing_xi")),
                       "scorecard": lambda: (200, admin_scorecard_row(c, who, mid, d)),
                       "fantasy": lambda: (200, fantasy.suggest(c, mid, d.get("rule_set"), store=True, model_version_id=engine.model_params(c)[0]["id"]))}
                if len(A) == 3 and A[2] in ops:
                    return ops[A[2]]()
        raise ApiError(404, "NOT_FOUND", "unknown endpoint")
    raise ApiError(405, "METHOD_NOT_ALLOWED", "method not allowed")

DB_PATH = None  # set by main.py
CRICSHEET_OPENER = None  # tests inject a fake downloader; production uses urllib

def _db_path():
    return DB_PATH
