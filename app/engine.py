"""SH PREDICTION engines: settlement/evaluation, accuracy analytics, the explainable
baseline pre-match model and the live win-probability model.

Settlement follows ICC playing conditions (Men's T20I clause 16 "The Result"):
 * win / awarded           -> the winner settles winner predictions
 * tie decided by Super Over -> the Super Over winner is the match winner
 * tie with no Super Over, no result, abandoned, canceled -> winner predictions are VOID
 * toss predictions settle whenever a toss took place, even if the match later had no result;
   a match abandoned/canceled without a toss makes toss predictions VOID.
Accuracy = Correct / (Correct + Incorrect) x 100; pending, void and ineligible are excluded.
"""
import datetime
import json
import math
from collections import defaultdict
from schema import now

PRE_MATCH_TYPES = ("toss", "winner", "first_innings_score", "second_innings_score")
SCORE_TOLERANCE = 0.10  # a projected innings score is "correct" when within +/-10% of the actual total

def pdt(x):
    d = datetime.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    return d.astimezone(datetime.timezone.utc) if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)

# ------------------------------------------------------------------ settlement
def settle(c, p):
    """Return (result, actual_team_id, actual_value, rule) for one prediction row."""
    m = c.execute("SELECT * FROM matches WHERE id=?", (p["match_id"],)).fetchone()
    if p["status"] == "canceled":
        return "void", None, None, "prediction canceled before lock"
    if not p["locked_at"]:
        return "ineligible", None, None, "not locked"
    if p["prediction_type"] in PRE_MATCH_TYPES and pdt(p["locked_at"]) >= pdt(m["start_utc"]):
        return "ineligible", None, None, "locked at or after match start"
    kind = p["prediction_type"]
    if kind == "toss":
        t = c.execute("SELECT * FROM toss_results WHERE match_id=?", (m["id"],)).fetchone()
        if t:
            return ("correct" if t["winner_team_id"] == p["predicted_team_id"] else "incorrect"), t["winner_team_id"], None, "toss winner"
        if m["status"] in ("abandoned", "canceled", "no_result"):
            return "void", None, None, "no toss took place"
        return "pending", None, None, "toss not verified"
    if kind in ("winner", "live_winner"):
        r = c.execute("SELECT * FROM match_results WHERE match_id=?", (m["id"],)).fetchone()
        if not r:
            if m["status"] in ("abandoned", "canceled", "no_result"):
                return "void", None, None, "match " + m["status"]
            return "pending", None, None, "result not verified"
        if r["result_type"] in ("win", "tie_super_over", "awarded"):
            rule = {"win": "match winner", "tie_super_over": "tie decided by Super Over (ICC 16.3.1 / Appendix F)", "awarded": "match awarded (ICC 16.2)"}[r["result_type"]]
            return ("correct" if r["winner_team_id"] == p["predicted_team_id"] else "incorrect"), r["winner_team_id"], None, rule
        return "void", None, None, "no winner: " + r["result_type"]
    # projected innings totals
    no = 1 if kind == "first_innings_score" else 2
    inn = c.execute("SELECT * FROM innings WHERE match_id=? AND innings_no=? AND is_super_over=0", (m["id"], no)).fetchone()
    if not inn or not inn["completed"]:
        if m["status"] in ("abandoned", "canceled", "no_result"):
            return "void", None, None, "innings not completed"
        return "pending", None, None, "innings not completed"
    actual = inn["runs"]
    ok = abs((p["predicted_value"] or 0) - actual) <= SCORE_TOLERANCE * max(actual, 1)
    return ("correct" if ok else "incorrect"), None, actual, "within +/-10% of actual total"

def reevaluate_match(c, match_id):
    """Recompute evaluations; a changed verdict supersedes (never deletes) the previous one."""
    changed = 0
    for p in c.execute("SELECT * FROM predictions WHERE match_id=?", (match_id,)).fetchall():
        res, team, val, rule = settle(c, p)
        cur = c.execute("SELECT * FROM prediction_evaluations WHERE prediction_id=? AND superseded_at IS NULL", (p["id"],)).fetchone()
        if cur and (cur["result"], cur["actual_team_id"], cur["actual_value"]) == (res, team, val):
            continue
        ts = now()
        if cur:
            c.execute("UPDATE prediction_evaluations SET superseded_at=? WHERE id=?", (ts, cur["id"]))
        c.execute("INSERT INTO prediction_evaluations(prediction_id,actual_team_id,actual_value,result,rule,evaluated_at) VALUES(?,?,?,?,?,?)",
                  (p["id"], team, val, res, rule, ts))
        changed += 1
    return changed

def reevaluate_all(c):
    return sum(reevaluate_match(c, r[0]) for r in c.execute("SELECT DISTINCT match_id FROM predictions").fetchall())

# ------------------------------------------------------------------ accuracy
def tally(results):
    k = defaultdict(int)
    for r in results:
        k[r] += 1
    n = k["correct"] + k["incorrect"]
    return {"total_predictions": len(results), "correct": k["correct"], "incorrect": k["incorrect"], "pending": k["pending"],
            "void": k["void"], "ineligible": k["ineligible"], "settled": n,
            "accuracy": round(100.0 * k["correct"] / n, 1) if n else None,
            "formula": "Correct / (Correct + Incorrect) x 100; pending, void (canceled/no result) and ineligible are excluded"}

EVAL_SQL = """SELECT p.*, e.result, e.actual_team_id, e.rule, m.competition_id, m.home_team_id, m.away_team_id, m.start_utc, m.data_origin AS match_origin,
 comp.name AS competition, x.display_name AS expert_name
 FROM predictions p JOIN matches m ON m.id=p.match_id JOIN competitions comp ON comp.id=m.competition_id
 LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
 LEFT JOIN expert_profiles x ON x.id=p.expert_id WHERE p.status<>'draft'"""

def accuracy(c, include_demo=False, prediction_type=None):
    rows = c.execute(EVAL_SQL).fetchall()
    if not include_demo:
        rows = [r for r in rows if r["data_origin"] != "demo" and r["match_origin"] != "demo"]
    if prediction_type:
        rows = [r for r in rows if r["prediction_type"] == prediction_type]
    res = lambda rs: tally([r["result"] or "pending" for r in rs])
    by = lambda key: {k: res([r for r in rows if key(r) == k]) for k in sorted({key(r) for r in rows if key(r) is not None}, key=str)}
    team_names = {r[0]: r[1] for r in c.execute("SELECT id,name FROM teams")}
    team_rows = defaultdict(list)
    for r in rows:
        team_rows[team_names.get(r["home_team_id"])].append(r)
        team_rows[team_names.get(r["away_team_id"])].append(r)
    return {"overall": res(rows), "by_type": by(lambda r: r["prediction_type"]),
            "by_league": by(lambda r: r["competition"]),
            "by_expert": by(lambda r: r["expert_name"] if r["source_type"] == "expert" else None),
            "by_model": by(lambda r: "model #%d" % r["model_version_id"] if r["model_version_id"] else None),
            "by_team": {t: res(v) for t, v in sorted(team_rows.items(), key=lambda kv: str(kv[0]))},
            "includes_demo": include_demo}

def completed_matches(c, include_demo=False):
    sql = """SELECT m.*, r.result_type, r.winner_team_id, t.winner_team_id AS toss_winner, t.decision FROM matches m
             JOIN match_results r ON r.match_id=m.id LEFT JOIN toss_results t ON t.match_id=m.id"""
    rows = c.execute(sql + ("" if include_demo else " WHERE m.data_origin<>'demo'") + " ORDER BY m.start_utc").fetchall()
    return rows

def batting_first(m):
    if not m["toss_winner"] or not m["decision"]:
        return None
    other = m["away_team_id"] if m["toss_winner"] == m["home_team_id"] else m["home_team_id"]
    return m["toss_winner"] if m["decision"] == "bat" else other

def analytics(c, include_demo=False):
    rows = [r for r in completed_matches(c, include_demo) if r["result_type"] in ("win", "tie_super_over", "awarded")]
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None
    toss_known = [r for r in rows if r["toss_winner"]]
    tw = sum(1 for r in toss_known if r["toss_winner"] == r["winner_team_id"])
    bf = [r for r in rows if batting_first(r)]
    bfw = sum(1 for r in bf if batting_first(r) == r["winner_team_id"])
    hw = sum(1 for r in rows if r["winner_team_id"] == r["home_team_id"])
    days = defaultdict(lambda: [0, 0])
    for r in rows:
        d = pdt(r["start_utc"]).strftime("%A")
        days[d][0] += 1
        days[d][1] += r["winner_team_id"] == r["home_team_id"]
    venues = defaultdict(lambda: [0, 0, 0])
    vn = {v[0]: v[1] for v in c.execute("SELECT id,name FROM venues")}
    for r in bf:
        v = venues[vn.get(r["venue_id"], "Unknown venue")]
        v[0] += 1
        v[1] += batting_first(r) == r["winner_team_id"]
        v[2] += batting_first(r) != r["winner_team_id"]
    return {
        "sample_matches": len(rows), "includes_demo": include_demo,
        "toss": {"matches_with_toss": len(toss_known), "toss_winner_won": tw, "toss_winner_lost": len(toss_known) - tw,
                 "toss_winner_win_pct": pct(tw, len(toss_known))},
        "batting_first_vs_chasing": {"matches": len(bf), "batting_first_won": bfw, "chasing_won": len(bf) - bfw,
                                     "batting_first_win_pct": pct(bfw, len(bf))},
        "home_away": {"matches": len(rows), "home_won": hw, "away_won": len(rows) - hw, "home_win_pct": pct(hw, len(rows))},
        "day_of_week_utc": {d: {"matches": v[0], "home_won": v[1], "home_win_pct": pct(v[1], v[0])} for d, v in days.items()},
        "venue": {k: {"matches": v[0], "batting_first_won": v[1], "chasing_won": v[2], "batting_first_win_pct": pct(v[1], v[0])}
                  for k, v in sorted(venues.items())},
        "note": "Home/away follows the fixture's listed home team. Day of week is in UTC.",
    }

# ------------------------------------------------------------------ baseline pre-match model
def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))

def _sig(x):
    return 1 / (1 + math.exp(-x))

def model_params(c):
    mv = c.execute("SELECT * FROM model_versions WHERE name='sh-baseline' ORDER BY id DESC LIMIT 1").fetchone()
    return mv, json.loads(mv["params_json"])

def predict_match(c, match_id):
    """Explainable pre-match winner probability for the HOME team plus factor breakdown."""
    mv, P = model_params(c)
    m = c.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not m:
        raise LookupError("match not found")
    h, a = m["home_team_id"], m["away_team_id"]
    hist = [r for r in completed_matches(c) if pdt(r["start_utc"]) < pdt(m["start_utc"]) and r["id"] != m["id"]
            and r["result_type"] in ("win", "tie_super_over", "awarded")]
    L, W = P["laplace"], P["form_window"]

    def form(team):
        games = [r for r in hist if team in (r["home_team_id"], r["away_team_id"])][-W:]
        wins = sum(1 for r in games if r["winner_team_id"] == team)
        return (wins + L) / (len(games) + 2 * L), len(games), wins

    fh, nh, wh = form(h)
    fa, na, wa = form(a)
    h2h = [r for r in hist if {r["home_team_id"], r["away_team_id"]} == {h, a}]
    hh = sum(1 for r in h2h if r["winner_team_id"] == h)
    h2h_rate = (hh + L) / (len(h2h) + 2 * L)
    venue_bias = 0.0
    venue_note = "no venue history"
    vh = [r for r in hist if r["venue_id"] and r["venue_id"] == m["venue_id"] and batting_first(r)]
    toss = c.execute("SELECT * FROM toss_results WHERE match_id=?", (match_id,)).fetchone()
    if vh and toss and toss["decision"]:
        bfw = (sum(1 for r in vh if batting_first(r) == r["winner_team_id"]) + L) / (len(vh) + 2 * L)
        home_bats_first = (toss["winner_team_id"] == h) == (toss["decision"] == "bat")
        venue_bias = _logit(bfw) if home_bats_first else -_logit(bfw)
        venue_note = "%d venue matches, batting first won %.0f%% (smoothed); home %s first" % (
            len(vh), 100 * bfw, "bats" if home_bats_first else "bowls")
    factors = [
        {"factor": "recent_form", "home": "%d/%d" % (wh, nh), "away": "%d/%d" % (wa, na),
         "contribution": round(P["form_weight"] * (_logit(fh) - _logit(fa)), 3)},
        {"factor": "head_to_head", "detail": "home won %d of %d" % (hh, len(h2h)),
         "contribution": round(P["h2h_weight"] * _logit(h2h_rate), 3)},
        {"factor": "home_advantage", "detail": "listed home team", "contribution": P["home_weight"]},
        {"factor": "venue_toss_bias", "detail": venue_note, "contribution": round(P["venue_weight"] * venue_bias, 3)},
    ]
    x = sum(f["contribution"] for f in factors)
    ph = _sig(x)
    sample = nh + na
    conf_level = "low" if sample < 6 else ("medium" if sample < 16 else "high")
    return {"match_id": match_id, "model": "%s %s" % (mv["name"], mv["version"]), "model_version_id": mv["id"],
            "home_win_probability": round(100 * ph, 1), "away_win_probability": round(100 * (1 - ph), 1),
            "toss_probability": {"home": 50.0, "away": 50.0, "note": "the toss is a fair coin; no model can beat 50%"},
            "factors": factors, "history_matches_used": len(hist), "confidence_level": conf_level,
            "predicted_team_id": h if ph >= 0.5 else a, "confidence": round(100 * max(ph, 1 - ph), 1)}

def projected_first_innings(c, match_id):
    m = c.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    rows = c.execute("""SELECT i.runs FROM innings i JOIN matches m ON m.id=i.match_id WHERE i.innings_no=1 AND i.completed=1
                        AND i.is_super_over=0 AND m.format=? AND m.venue_id IS ? AND m.id<>? AND m.data_origin<>'demo'""",
                     (m["format"], m["venue_id"], match_id)).fetchall()
    if len(rows) < 3:
        return {"available": False, "reason": "needs at least 3 completed first innings at this venue in this format", "samples": len(rows)}
    vals = sorted(r[0] for r in rows)
    mean = sum(vals) / len(vals)
    return {"available": True, "projected": round(mean), "low": vals[len(vals) // 4], "high": vals[(3 * len(vals)) // 4], "samples": len(vals)}

# ------------------------------------------------------------------ live win probability
FORMAT_BALLS = {"T10": 60, "T20": 120, "The Hundred": 100, "ODI": 300, "List A": 300}
PAR_RPO = {"T10": 11.5, "T20": 8.4, "The Hundred": 8.6, "ODI": 5.6, "List A": 5.6}

def resources(balls_left, wickets_lost, max_balls):
    """Original SH resource curve (not the proprietary DLS table): share of scoring potential left."""
    if balls_left <= 0 or wickets_lost >= 10:
        return 0.0
    b = balls_left / max_balls
    w = (10 - wickets_lost) / 10
    return (1 - math.exp(-3.2 * b)) / (1 - math.exp(-3.2)) * (w ** 0.9 if b > 0.3 else w ** 0.6)

def live_probability(fmt, innings_no, runs, wickets, legal_balls, target=None, max_balls=None, prematch_home=None, batting_is_home=True):
    max_balls = max_balls or FORMAT_BALLS.get(fmt, 120)
    par = PAR_RPO.get(fmt, 8.0) * max_balls / 6
    left = max_balls - legal_balls
    crr = round(runs * 6 / legal_balls, 2) if legal_balls else 0.0
    out = {"current_run_rate": crr, "balls_left": left, "wickets_in_hand": 10 - wickets}
    if innings_no == 1:
        projected = runs + resources(left, wickets, max_balls) * par
        bat_p = _sig((projected - par) / (0.12 * par))
        if prematch_home is not None:  # blend toward the pre-match view early in the innings
            pre = prematch_home / 100 if batting_is_home else 1 - prematch_home / 100
            share = legal_balls / max_balls
            bat_p = (1 - share) * pre + share * bat_p
        out.update(projected_score=round(projected), batting_team_win_probability=round(100 * bat_p, 1))
    else:
        need = target - runs
        if need <= 0:
            bat_p = 1.0
        elif left <= 0 or wickets >= 10:
            bat_p = 0.0
        else:
            expected = resources(left, wickets, max_balls) * par
            bat_p = _sig((expected - need) / (4 + 0.08 * par * math.sqrt(left / max_balls)))
        out.update(runs_needed=max(need, 0), required_run_rate=round(need * 6 / left, 2) if left > 0 and need > 0 else 0.0,
                   batting_team_win_probability=round(100 * bat_p, 1))
    out["bowling_team_win_probability"] = round(100 - out["batting_team_win_probability"], 1)
    return out
