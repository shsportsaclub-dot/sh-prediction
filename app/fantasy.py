"""SH Fantasy Engine — free-to-play suggestions only (no entry fees, no money).

Rules are configurable rule sets (fantasy_rule_sets) because platforms differ: team size, players per
real team, role minimum/maximum, optional credit cap, captain / vice-captain multipliers.
Player pool: announced Playing XI ("confirmed") or, before that, the squad ("provisional").
Expected points use our own simple scoring from verified player_statistics; players without
statistics get a role baseline and are marked low-confidence.
"""
import json
from schema import now

ROLE_BASE = {"batter": 22.0, "bowler": 20.0, "all_rounder": 26.0, "wicket_keeper": 20.0}

def rules(c, name=None):
    r = c.execute("SELECT * FROM fantasy_rule_sets WHERE name=?" if name else "SELECT * FROM fantasy_rule_sets ORDER BY id LIMIT 1",
                  (name,) if name else ()).fetchone()
    if not r:
        raise LookupError("fantasy rule set not found")
    return r["name"], json.loads(r["rules_json"])

def validate_rules(R):
    need = {"team_size", "max_per_team", "roles", "captain_multiplier", "vice_captain_multiplier"}
    if not isinstance(R, dict) or not need <= set(R):
        raise ValueError("rules need: " + ", ".join(sorted(need)))
    if not 5 <= int(R["team_size"]) <= 15 or not 1 <= int(R["max_per_team"]) <= int(R["team_size"]):
        raise ValueError("team_size 5..15 and max_per_team 1..team_size")
    lo = sum(v[0] for v in R["roles"].values())
    hi = sum(v[1] for v in R["roles"].values())
    if set(R["roles"]) - set(ROLE_BASE) or not lo <= int(R["team_size"]) <= hi:
        raise ValueError("role limits must use batter/bowler/all_rounder/wicket_keeper and allow the team size")
    return R

def pool(c, match_id):
    m = c.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not m:
        raise LookupError("match not found")
    xi = c.execute("""SELECT x.team_id, p.id, p.name, p.role FROM playing_xi x JOIN players p ON p.id=x.player_id
                      WHERE x.match_id=? AND x.is_impact_sub=0""", (match_id,)).fetchall()
    status = "confirmed"
    if not xi:
        xi = c.execute("""SELECT s.team_id, p.id, p.name, p.role FROM match_squads s JOIN players p ON p.id=s.player_id WHERE s.match_id=?""",
                       (match_id,)).fetchall()
        status = "provisional"
    fmt = m["format"]
    out = []
    for r in xi:
        role = r["role"] or "batter"
        s = c.execute("SELECT * FROM player_statistics WHERE player_id=? AND format=?", (r["id"], fmt)).fetchone()
        if s and s["matches"]:
            rpm = (s["runs"] or 0) / s["matches"]
            wpm = (s["wickets"] or 0) / s["matches"]
            sr_bonus = ((s["strike_rate"] or 100) - 100) / 10 if rpm >= 10 else 0
            eco_bonus = (8 - (s["economy"] or 8)) * 2 if wpm > 0 else 0
            pts = rpm + 25 * wpm + sr_bonus + eco_bonus + (4 if role == "wicket_keeper" else 0)
            conf = "high" if s["matches"] >= 10 else "medium"
        else:
            pts, conf = ROLE_BASE[role], "low"
        out.append({"player_id": r["id"], "name": r["name"], "team_id": r["team_id"], "role": role,
                    "expected_points": round(pts, 1), "confidence": conf, "availability": status})
    return m, out, status

def _pick(players, R, home, away, exclude=()):
    """Best feasible team by expected points under role and per-team limits (greedy with role minimums first)."""
    roles = R["roles"]
    cand = sorted((p for p in players if p["player_id"] not in exclude), key=lambda p: -p["expected_points"])
    team, per_team, per_role = [], {home: 0, away: 0}, {k: 0 for k in roles}

    def ok(p):
        return (per_team.get(p["team_id"], 0) < R["max_per_team"] and per_role.get(p["role"], 0) < roles.get(p["role"], [0, 0])[1]
                and p not in team)

    for role, (mn, _) in roles.items():
        for p in cand:
            if per_role[role] >= mn:
                break
            if p["role"] == role and ok(p):
                team.append(p); per_team[p["team_id"]] += 1; per_role[role] += 1
    for p in cand:
        if len(team) >= R["team_size"]:
            break
        if ok(p):
            team.append(p); per_team[p["team_id"]] += 1; per_role[p["role"]] += 1
    feasible = len(team) == R["team_size"] and all(per_role[k] >= v[0] for k, v in roles.items())
    return team, feasible

def suggest(c, match_id, rule_name=None, store=True, model_version_id=None):
    name, R = rules(c, rule_name)
    m, players, status = pool(c, match_id)
    if len(players) < R["team_size"]:
        return {"available": False, "reason": "Playing XI / squad not available for this match yet", "players_known": len(players)}
    combos = []
    first, ok1 = _pick(players, R, m["home_team_id"], m["away_team_id"])
    if not ok1:
        return {"available": False, "reason": "role limits of rule set '%s' cannot be met with the known players" % name}
    top = sorted(first, key=lambda p: -p["expected_points"])
    variants = [("Safe", first, ())]
    # Balanced: swap out the two lowest-confidence picks; High risk: drop the top two scorers for differentials
    low = [p["player_id"] for p in sorted(first, key=lambda p: ({"low": 0, "medium": 1, "high": 2}[p["confidence"]], p["expected_points"]))[:2]]
    b, okb = _pick(players, R, m["home_team_id"], m["away_team_id"], exclude=low)
    if okb:
        variants.append(("Balanced", b, low))
    hi = [p["player_id"] for p in top[:2]]
    h, okh = _pick(players, R, m["home_team_id"], m["away_team_id"], exclude=hi)
    if okh:
        variants.append(("High risk", h, hi))
    seen = set()
    for label, team, _ in variants:
        key = tuple(sorted(p["player_id"] for p in team))
        if key in seen:
            continue
        seen.add(key)
        order = sorted(team, key=lambda p: -p["expected_points"])
        cap, vc = order[0], order[1]
        total = sum(p["expected_points"] for p in team) + cap["expected_points"] * (R["captain_multiplier"] - 1) + vc["expected_points"] * (R["vice_captain_multiplier"] - 1)
        lowc = sum(1 for p in team if p["confidence"] == "low")
        risk = "low" if label == "Safe" and lowc <= 2 and status == "confirmed" else ("high" if label == "High risk" or lowc > 5 else "medium")
        combo = {"label": label, "risk": risk, "captain": cap, "vice_captain": vc, "players": team, "expected_points": round(total, 1),
                 "low_confidence_players": lowc, "availability": status}
        if store:
            c.execute("""INSERT INTO fantasy_teams(match_id,model_version_id,players_json,captain_id,vice_captain_id,risk,created_at)
                         VALUES(?,?,?,?,?,?,?)""", (match_id, model_version_id, json.dumps([p["player_id"] for p in team]), cap["player_id"], vc["player_id"], risk, now()))
            combo["fantasy_team_id"] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        combos.append(combo)
    return {"available": True, "rule_set": name, "rules": R, "availability": status, "teams": combos,
            "note": "Free-to-play suggestions from verified statistics. Provisional until the Playing XI is announced." if status != "confirmed" else
                    "Free-to-play suggestions from verified statistics and the announced Playing XI."}

def history(c, match_id):
    rows = c.execute("SELECT * FROM fantasy_teams WHERE match_id=? AND user_id IS NULL ORDER BY id DESC LIMIT 30", (match_id,)).fetchall()
    return [dict(r, players=json.loads(r["players_json"])) for r in rows]
