"""/api/v1 — versioned SH PREDICTION API.

Auth: Bearer session token (on-screen OTP login) for reads; X-Admin-Token for /api/v1/admin/*;
verified experts (or admin) may POST predictions. Every write is audited.
Errors: {"error": {"code", "message"}} with HTTP 400/401/403/404/409/429.
"""
import hashlib
import json
import re
import threading
import time
import uuid
import sqlite3

import engine
import i18n
from schema import now, migrate, bridge_legacy

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

def get_match(c, mid):
    r = c.execute(MATCH_SQL + " WHERE m.id=?", (mid,)).fetchone()
    if not r:
        raise ApiError(404, "NOT_FOUND", "match not found")
    return r

# ------------------------------------------------------------------ identity
def identity(h, c):
    """Return dict(user_id, role, actor) or None. Admin token wins."""
    if h.admin_ok():
        return {"user_id": None, "role": "admin", "actor": "admin-token"}
    tok = h.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not tok:
        return None
    s = c.execute("SELECT phone FROM login_sessions WHERE token_hash=? AND created_at>=?",
                  (hashlib.sha256(tok.encode()).hexdigest(), time.time() - 30 * 86400)).fetchone()
    if not s:
        return None
    c.execute("INSERT OR IGNORE INTO users(phone,created_at) VALUES(?,?)", (s[0], now()))
    u = c.execute("SELECT * FROM users WHERE phone=?", (s[0],)).fetchone()
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
    if qv(q, "include_demo") != "1":
        where.append("m.data_origin<>'demo'")
    sql = MATCH_SQL + (" WHERE " + " AND ".join(where) if where else "")
    total = c.execute("SELECT COUNT(*) FROM (" + sql + ")", args).fetchone()[0]
    order = " ORDER BY m.start_utc DESC" if st == "completed" else " ORDER BY m.start_utc ASC"
    items = [match_out(r) for r in c.execute(sql + order + " LIMIT ? OFFSET ?", args + [limit, offset])]
    return {"items": items, "total": total, "limit": limit, "offset": offset}

def form_of(c, team_id, before, n=5):
    rs = c.execute("""SELECT r.winner_team_id, r.result_type FROM matches m JOIN match_results r ON r.match_id=m.id
                      WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.start_utc<? AND m.data_origin<>'demo'
                      ORDER BY m.start_utc DESC LIMIT ?""", (team_id, team_id, before, n)).fetchall()
    return "".join("W" if r[0] == team_id else ("L" if r[0] else "N") for r in rs)

def match_detail(c, mid):
    r = get_match(c, mid)
    d = match_out(r)
    h, a = r["home_team_id"], r["away_team_id"]
    h2h = c.execute("""SELECT r.winner_team_id FROM matches m JOIN match_results r ON r.match_id=m.id
                       WHERE ((m.home_team_id=? AND m.away_team_id=?) OR (m.home_team_id=? AND m.away_team_id=?)) AND m.id<>?
                       AND m.data_origin<>'demo'""", (h, a, a, h, mid)).fetchall()
    d["head_to_head"] = {"matches": len(h2h), "home_won": sum(1 for x in h2h if x[0] == h), "away_won": sum(1 for x in h2h if x[0] == a)}
    d["form"] = {"home_last5": form_of(c, h, r["start_utc"]), "away_last5": form_of(c, a, r["start_utc"])}
    d["playing_xi"] = rows(c.execute("""SELECT x.team_id,x.player_id,p.name,p.role,x.batting_order,x.is_captain,x.is_keeper,x.is_impact_sub
                                         FROM playing_xi x JOIN players p ON p.id=x.player_id WHERE x.match_id=? ORDER BY x.team_id,x.batting_order""", (mid,)))
    d["squads"] = rows(c.execute("SELECT s.team_id,p.id AS player_id,p.name,p.role FROM match_squads s JOIN players p ON p.id=s.player_id WHERE s.match_id=?", (mid,)))
    return d

def match_predictions(c, mid):
    get_match(c, mid)
    out = []
    for p in c.execute("""SELECT p.*, e.result AS evaluation, e.actual_team_id, e.actual_value, e.rule, e.evaluated_at,
                          x.display_name AS expert_name, x.verified AS expert_verified, mv.name||' '||mv.version AS model
                          FROM predictions p LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                          LEFT JOIN expert_profiles x ON x.id=p.expert_id LEFT JOIN model_versions mv ON mv.id=p.model_version_id
                          WHERE p.match_id=? AND p.status<>'draft' ORDER BY p.created_at""", (mid,)):
        d = dict(p)
        d["factors"] = json.loads(d.pop("factors_json") or "null")
        d["versions"] = rows(c.execute("SELECT * FROM prediction_versions WHERE prediction_id=? ORDER BY version_no", (p["id"],)))
        out.append(d)
    return {"items": out}

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
    return {"items": items, "total": c.execute("SELECT COUNT(*) FROM ball_events WHERE match_id=?", (mid,)).fetchone()[0], "limit": limit, "offset": offset}

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
    out = {"match_id": mid, "data_origin": r["data_origin"], "pre_match": engine.predict_match(c, mid),
           "projected_first_innings": engine.projected_first_innings(c, mid), "live": current_live(c, r)}
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
    where, args = ["m.data_origin<>'demo'"] if qv(q, "include_demo") != "1" else [], []
    if qv(q, "competition_id"):
        where.append("m.competition_id=?"); args.append(int_id(qv(q, "competition_id"), "competition_id"))
    source = qv(q, "source") or "primary"
    out = []
    for r in c.execute(MATCH_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.start_utc, m.id", args):
        teams = {r["home_team_id"]: ("H", r["home_code"] if r["home_code_ok"] else None, r["home_name"]),
                 r["away_team_id"]: ("A", r["away_code"] if r["away_code_ok"] else None, r["away_name"])}

        def cell(team_id, outcome):
            if not team_id:
                return None
            side, code, name = teams[team_id]
            return {"side": side, "code": code, "name": name, "outcome": outcome}

        def pred(kind):
            p = c.execute("""SELECT p.predicted_team_id, e.result FROM predictions p LEFT JOIN prediction_evaluations e
                             ON e.prediction_id=p.id AND e.superseded_at IS NULL WHERE p.match_id=? AND p.prediction_type=?
                             AND p.locked_at IS NOT NULL AND p.status='locked' ORDER BY CASE p.source_type WHEN 'legacy' THEN 0 WHEN 'expert' THEN 1 ELSE 2 END, p.id LIMIT 1""",
                          (r["id"], kind)).fetchone()
            if not p:
                return None
            return cell(p[0], {"correct": "won", "incorrect": "lost"}.get(p[1] or "pending", "unknown"))

        toss_actual = cell(r["toss_winner_id"], "won") if r["toss_winner_id"] else None
        win_actual = cell(r["winner_team_id"], "won") if r["winner_team_id"] else None
        out.append({"match_id": r["id"], "match": r["match_no"] or "M%d" % r["id"], "start_utc": r["start_utc"],
                    "competition": r["competition"], "data_origin": r["data_origin"], "status": r["status"],
                    "home": {"side": "H", "code": r["home_code"] if r["home_code_ok"] else None, "name": r["home_name"]},
                    "away": {"side": "A", "code": r["away_code"] if r["away_code_ok"] else None, "name": r["away_name"]},
                    "toss_prediction": pred("toss"), "winner_prediction": pred("winner"),
                    "toss_actual": toss_actual, "winner_actual": win_actual})
    return {"columns": ["Match", "Home", "Away", "Toss", "Winner"], "items": out, "view": source}

def experts(c, q):
    limit, offset = page(q)
    acc = engine.accuracy(c)["by_expert"]
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

def expert_history(c, eid, q):
    limit, offset = page(q)
    x = c.execute("SELECT * FROM expert_profiles WHERE id=?", (eid,)).fetchone()
    if not x:
        raise ApiError(404, "NOT_FOUND", "expert not found")
    items = rows(c.execute("""SELECT p.id,p.match_id,p.prediction_type,p.predicted_team_id,t.name AS predicted_team,p.confidence,p.explanation,
                              p.created_at,p.locked_at,e.result AS evaluation,e.rule FROM predictions p LEFT JOIN teams t ON t.id=p.predicted_team_id
                              LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                              WHERE p.expert_id=? AND p.status<>'draft' ORDER BY p.created_at DESC LIMIT ? OFFSET ?""", (eid, limit, offset)))
    res = [r[0] or "pending" for r in c.execute("""SELECT e.result FROM predictions p LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id
                                                    AND e.superseded_at IS NULL WHERE p.expert_id=? AND p.status<>'draft'""", (eid,))]
    return {"expert": dict(x), "summary": engine.tally(res), "items": items, "limit": limit, "offset": offset}

# ------------------------------------------------------------------ writes
PRED_TYPES = ("toss", "winner", "first_innings_score", "second_innings_score", "live_winner")

def create_prediction(c, who, d, model=False):
    mid = int_id(d.get("match_id"), "match_id")
    m = get_match(c, mid)
    kind = d.get("prediction_type")
    if kind not in PRED_TYPES:
        raise bad("prediction_type must be one of " + ", ".join(PRED_TYPES))
    expert_id = None
    if who["role"] != "admin":
        x = c.execute("SELECT * FROM expert_profiles WHERE user_id=?", (who["user_id"],)).fetchone()
        if not x or not x["verified"]:
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

RESULT_TYPES = ("win", "tie_super_over", "tie", "no_result", "abandoned", "canceled", "awarded")

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
    status = {"win": "completed", "tie_super_over": "completed", "tie": "completed", "awarded": "completed",
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
    live = current_live(c, m)
    if live and m["status"] == "live":
        team = m["home_team_id"] if live["home_win_probability"] >= 50 else m["away_team_id"]
        conf = max(live["home_win_probability"], live["away_win_probability"])
        p = c.execute("SELECT id FROM predictions WHERE match_id=? AND prediction_type='live_winner' AND source_type='model'", (mid,)).fetchone()
        if not p:
            c.execute("""INSERT INTO predictions(prediction_uid,match_id,source_type,model_version_id,prediction_type,predicted_team_id,confidence,
                         explanation,created_at,locked_at,status,data_origin) VALUES(?,?,'model',?,'live_winner',?,?,?,?,?,'locked',?)""",
                      (str(uuid.uuid4()), mid, engine.model_params(c)[0]["id"], team, conf, "Ball-by-ball live model; every update is a new version.",
                       now(), now(), "demo" if m["data_origin"] == "demo" else "verified"))
            p = c.execute("SELECT last_insert_rowid()").fetchone()
        add_version(c, p[0], team, None, conf, "inn%d %d/%d (%s ov)" % (ino, runs, wk, "%d.%d" % divmod(lb, 6)), live)
    return {"innings_no": ino, "score": "%d/%d" % (runs, wk), "overs": "%d.%d" % divmod(lb, 6), "innings_completed": bool(done), "live": live}

def admin_expert(c, who, d):
    name = (d.get("display_name") or "").strip()
    if not name:
        raise bad("display_name required")
    uid = None
    if d.get("phone"):
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

# ------------------------------------------------------------------ router
def route(h, method, path, q, body_fn):
    c = h_db()
    try:
        migrate(c)
        bridge_legacy(c)
        engine.reevaluate_all(c)
        c.commit()
        ip = h.headers.get("X-Forwarded-For", h.client_address[0]).split(",")[0].strip()
        if not rate_ok(ip):
            raise ApiError(429, "RATE_LIMITED", "too many requests; try again in a minute")
        parts = [p for p in path.split("/") if p][2:]  # strip api, v1
        # public endpoints
        if method == "GET" and parts == ["languages"]:
            return 200, {"items": rows(c.execute("SELECT * FROM languages ORDER BY ui_complete DESC, name"))}
        if method == "GET" and len(parts) == 2 and parts[0] == "i18n":
            if not c.execute("SELECT 1 FROM languages WHERE code=?", (parts[1],)).fetchone():
                raise ApiError(404, "NOT_FOUND", "unknown language")
            r = c.execute("SELECT * FROM languages WHERE code=?", (parts[1],)).fetchone()
            return 200, {"code": parts[1], "rtl": bool(r["rtl"]), "ui_complete": bool(r["ui_complete"]), "strings": i18n.bundle(parts[1])}
        who = identity(h, c)
        if parts[:1] == ["admin"]:
            if not who or who["role"] != "admin":
                raise ApiError(403, "FORBIDDEN", "admin token required")
        elif not who:
            raise ApiError(401, "UNAUTHENTICATED", "login required")
        res = dispatch(c, who, method, parts, q, body_fn)
        c.commit()
        return res
    except ApiError as e:
        c.rollback()
        return e.status, {"error": {"code": e.code, "message": e.message}}
    except sqlite3.DatabaseError as e:
        c.rollback()
        if "immutable" in str(e) or "append-only" in str(e) or "cannot be deleted" in str(e):
            return 409, {"error": {"code": "IMMUTABLE", "message": str(e)}}
        return 400, {"error": {"code": "DATABASE_ERROR", "message": str(e)}}
    except (ValueError, TypeError, KeyError) as e:
        c.rollback()
        return 400, {"error": {"code": "VALIDATION_ERROR", "message": str(e)}}
    finally:
        c.close()

DB_FN = None  # set by main.py to its db() so the legacy tables exist too

def h_db():
    c = DB_FN()
    c.execute("PRAGMA foreign_keys=ON")
    return c

def dispatch(c, who, method, parts, q, body_fn):
    P = parts
    if method == "GET":
        if P == ["matches"]:
            return 200, list_matches(c, q)
        if len(P) >= 2 and P[0] == "matches":
            mid = int_id(P[1], "match id")
            if len(P) == 2:
                return 200, match_detail(c, mid)
            sub = {"scorecard": lambda: scorecard(c, mid), "commentary": lambda: commentary(c, mid, q),
                   "predictions": lambda: match_predictions(c, mid), "signals": lambda: signals(c, mid)}
            if len(P) == 3 and P[2] in sub:
                return 200, sub[P[2]]()
        if P == ["master-list"]:
            return 200, master_list(c, q)
        if P == ["competitions"]:
            return 200, {"items": rows(c.execute("SELECT * FROM competitions ORDER BY featured DESC, category, name"))}
        if P == ["teams"]:
            return 200, {"items": rows(c.execute("SELECT id,name,CASE WHEN short_code_approved=1 THEN short_code END AS short_code,gender FROM teams ORDER BY name"))}
        if P == ["experts"]:
            return 200, experts(c, q)
        if len(P) == 3 and P[0] == "experts" and P[2] == "history":
            return 200, expert_history(c, int_id(P[1], "expert id"), q)
        demo = qv(q, "include_demo") == "1"
        if P == ["analytics", "accuracy"]:
            return 200, engine.accuracy(c, demo, qv(q, "prediction_type"))
        an = {"toss": "toss", "home-away": "home_away", "venue": "venue"}
        if len(P) == 2 and P[0] == "analytics" and P[1] in an:
            a = engine.analytics(c, demo)
            extra = {"batting_first_vs_chasing": a["batting_first_vs_chasing"]} if P[1] == "toss" else {}
            extra.update({"day_of_week_utc": a["day_of_week_utc"]} if P[1] == "home-away" else {})
            return 200, dict({an[P[1]]: a[an[P[1]]], "sample_matches": a["sample_matches"], "note": a["note"], "includes_demo": demo}, **extra)
        if P == ["me", "preferences"]:
            return 200, preferences(c, who)
        if P == ["admin", "audit"]:
            limit, offset = page(q)
            return 200, {"items": rows(c.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))),
                         "total": c.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]}
        if P == ["admin", "monitor"]:
            return 200, monitor(c)
        raise ApiError(404, "NOT_FOUND", "unknown endpoint")
    if method in ("POST", "PUT"):
        d = body_fn()
        if not isinstance(d, dict):
            raise bad("JSON object body required")
        if method == "PUT" and P == ["me", "preferences"]:
            return 200, preferences(c, who, d)
        if method == "POST":
            if P == ["predictions"]:
                if who["role"] not in ("admin", "expert"):
                    raise ApiError(403, "FORBIDDEN", "only verified experts or admins can publish predictions")
                return 201, create_prediction(c, who, d)
            if len(P) == 3 and P[0] == "predictions" and P[2] == "lock":
                return 200, lock_prediction(c, who, int_id(P[1], "prediction id"))
            if len(P) == 3 and P[0] == "experts" and P[2] == "follow":
                eid = int_id(P[1], "expert id")
                if not who["user_id"]:
                    raise ApiError(400, "USER_REQUIRED", "follow needs a logged-in user")
                if not c.execute("SELECT 1 FROM expert_profiles WHERE id=?", (eid,)).fetchone():
                    raise ApiError(404, "NOT_FOUND", "expert not found")
                if d.get("follow", True):
                    c.execute("INSERT OR IGNORE INTO expert_follows(user_id,expert_id,created_at) VALUES(?,?,?)", (who["user_id"], eid, now()))
                else:
                    c.execute("DELETE FROM expert_follows WHERE user_id=? AND expert_id=?", (who["user_id"], eid))
                return 200, {"expert_id": eid, "following": bool(d.get("follow", True))}
            admin = {("admin", "teams"): admin_team, ("admin", "matches"): admin_match, ("admin", "toss"): admin_toss,
                     ("admin", "results"): admin_result, ("admin", "ball-events"): admin_ball, ("admin", "experts"): admin_expert}
            if tuple(P) in admin:
                return 200, admin[tuple(P)](c, who, d)
            if len(P) == 4 and P[:2] == ["admin", "experts"] and P[3] == "verify":
                return 200, admin_verify_expert(c, who, int_id(P[2], "expert id"), d)
            if len(P) == 4 and P[:2] == ["admin", "matches"] and P[3] == "model-prediction":
                return 201, model_prediction(c, who, int_id(P[2], "match id"))
            if P == ["admin", "demo-seed"]:
                return 200, demo_seed(c, who)
        raise ApiError(404, "NOT_FOUND", "unknown endpoint")
    raise ApiError(405, "METHOD_NOT_ALLOWED", "method not allowed")
