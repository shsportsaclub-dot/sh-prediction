"""SH Match Center insights: everything the owner's reference screens show, computed only from data we hold.

Parts (GET /matches/{id}/insights?part=...):
  info      team form (last 5 with scores), head-to-head (last 10), team comparison overall / at venue (last 10),
            venue stats (bat/bowl first, averages, highest/lowest, scores at 6/10/15/20 overs, pace vs spin when
            bowling styles are known, recent matches), weather (Open-Meteo, cached), points-table rows of both teams
  fantasy   live SH fantasy points per player with an event-by-event breakdown, and a leaderboard of SH fantasy teams
  graphs    over-by-over runs and wickets per innings (Manhattan, Worm, over history) and the SH win-probability line
  live      partnership, last wicket, last two overs
  points    full points table with each team's series form, and other seasons of the same competition
A figure is left out (null + note) when its data is missing; nothing is estimated or filled in.
"""
import json, os, re, time, urllib.parse, urllib.request
import engine

NA = "Data not available from the current source."
QUOTA = {"T10": 60, "T20": 120, "The Hundred": 100, "ODI": 300, "List A": 300}


# ------------------------------------------------------------------ helpers
def _ovs(balls):
    return "%d.%d" % divmod(int(balls or 0), 6)

def _venue_ids(c, vid):
    if not vid:
        return []
    vname = c.execute("SELECT name FROM venues WHERE id=?", (vid,)).fetchone()[0]
    key = vname.split(",")[0].strip()
    return [x[0] for x in c.execute("SELECT id FROM venues WHERE name=? OR name LIKE ?", (vname, key + ",%"))] or [vid]

def _team_label(c, tid):
    r = c.execute("SELECT name, CASE WHEN short_code_approved THEN short_code END AS short_code FROM teams WHERE id=?", (tid,)).fetchone()
    return (r["short_code"] or r["name"]) if r else ""

def _innings(c, mid):
    return c.execute("""SELECT i.innings_no, i.batting_team_id, i.runs, i.wickets, i.legal_balls, i.max_balls, t.name, CASE WHEN t.short_code_approved THEN t.short_code END AS short_code
                        FROM innings i JOIN teams t ON t.id=i.batting_team_id WHERE i.match_id=? AND i.is_super_over=0 ORDER BY i.innings_no""",
                     (mid,)).fetchall()

def _match_card(c, m, ids=None):
    """One completed match as a small card: competition, match no, date, both innings, result."""
    inn = _innings(c, m["id"])
    winner = m["winner_team_id"]
    res = None
    if m["result_type"] in ("win", "awarded", "tie_super_over") and winner:
        res = _team_label(c, winner) + " won" + (" by " + m["margin"] if m["margin"] else "")
    elif m["result_type"]:
        res = m["result_type"].replace("_", " ").title()
    return {"id": m["id"], "day": m["start_utc"][:10], "competition": m["competition"], "match_no": m["match_no"], "result": res,
            "innings": [{"team": x["short_code"] or x["name"], "runs": x["runs"], "wickets": x["wickets"], "overs": _ovs(x["legal_balls"])} for x in inn],
            "outcome": None if ids is None else ("W" if winner in ids else "L" if winner else "-")}

CARD_SQL = """SELECT m.id, m.start_utc, m.match_no, m.home_team_id, m.away_team_id, m.venue_id, cp.name AS competition,
              mr.result_type, mr.winner_team_id, mr.margin FROM matches m JOIN match_results mr ON mr.match_id=m.id
              JOIN competitions cp ON cp.id=m.competition_id WHERE m.data_origin<>'demo' """


# ------------------------------------------------------------------ info
def _team_matches(c, ids, fmt, before, mid, venue_ids=None, limit=10):
    q = ",".join("?" * len(ids))
    sql = CARD_SQL + "AND m.id<>? AND m.format=? AND m.start_utc<? AND (m.home_team_id IN (%s) OR m.away_team_id IN (%s))" % (q, q)
    args = [mid, fmt, before] + ids + ids
    if venue_ids:
        sql += " AND m.venue_id IN (%s)" % ",".join("?" * len(venue_ids))
        args += venue_ids
    return c.execute(sql + " ORDER BY m.start_utc DESC LIMIT ?", args + [limit]).fetchall()

def _comparison(c, ids, rows_):
    played = len(rows_)
    if not played:
        return {"matches": 0, "win_pct": None, "avg_score": None, "highest": None, "lowest": None}
    won = sum(1 for m in rows_ if m["winner_team_id"] in ids)
    scores = [x["runs"] for m in rows_ for x in _innings(c, m["id"]) if x["batting_team_id"] in ids]
    return {"matches": played, "win_pct": round(100 * won / played), "avg_score": round(sum(scores) / len(scores)) if scores else None,
            "highest": max(scores) if scores else None, "lowest": min(scores) if scores else None}

def _scores_at_overs(c, mids, quota):
    """Average cumulative score at the end of overs 6/10/15/20 (or the format's checkpoints), 1st and 2nd innings,
    from ball-by-ball rows only; an innings counts for a checkpoint only if it reached it."""
    marks = [6, 10, 15, 20] if quota <= 120 else [10, 20, 30, 40, 50]
    marks = [x for x in marks if x * 6 <= quota]
    acc = {k: {1: [], 2: []} for k in marks}
    used = 0
    for mid in mids:
        per = {}
        for r in c.execute("""SELECT innings_no, over_no, SUM(runs_bat+extras) AS r FROM ball_events WHERE match_id=? AND innings_no IN (1,2)
                              GROUP BY innings_no, over_no ORDER BY innings_no, over_no""", (mid,)):
            per.setdefault(r["innings_no"], {})[r["over_no"]] = r["r"]
        if not per:
            continue
        used += 1
        for inn, overs in per.items():
            total, last = 0, max(overs)
            for o in range(last + 1):
                total += overs.get(o, 0)
                if o + 1 in acc and o < last or (o + 1 in acc and o == last):
                    acc[o + 1][inn].append(total)
    if not used:
        return None
    return {"matches": used, "rows": [{"over": k, "first": round(sum(v[1]) / len(v[1])) if v[1] else None,
                                       "second": round(sum(v[2]) / len(v[2])) if v[2] else None} for k, v in acc.items()]}

def _pace_spin(c, mids):
    pace = spin = 0
    known = False
    for mid in mids:
        for r in c.execute("""SELECT p.bowling_style FROM ball_events b JOIN players p ON p.id=b.bowler_id
                              WHERE b.match_id=? AND b.is_wicket=1 AND (b.wicket_kind IS NULL OR b.wicket_kind NOT IN ('run out','retired hurt','retired out','obstructing the field'))""", (mid,)):
            s = (r[0] or "").lower()
            if not s:
                continue
            known = True
            if re.search(r"spin|break|orthodox|googly|chinaman|wrist|off ?spin|leg ?spin|slow left", s) and "medium" not in s:
                spin += 1
            elif re.search(r"fast|medium|pace|seam|swing", s):
                pace += 1
    if not known or pace + spin == 0:
        return None
    return {"pace": pace, "spin": spin, "pace_pct": round(100 * pace / (pace + spin)), "spin_pct": round(100 * spin / (pace + spin))}

_WX = {}
def weather(c, venue_name, city=None, fetch=None, now_fn=time.time):
    """Current weather at the venue's city from Open-Meteo (free, no key; CC BY 4.0, attribution shown). Cached 30 minutes."""
    if fetch is None and os.environ.get("SH_WEATHER", "1") == "0":
        return None
    place = (city or (venue_name.split(",")[1] if venue_name and "," in venue_name else venue_name) or "").strip()
    if not place:
        return None
    hit = _WX.get(place.lower())
    if hit and now_fn() - hit[0] < 1800:
        return hit[1]
    fetch = fetch or (lambda url: json.loads(urllib.request.urlopen(url, timeout=6).read()))
    try:
        g = fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name=" + urllib.parse.quote(place))
        if not g.get("results"):
            _WX[place.lower()] = (now_fn(), None)
            return None
        p = g["results"][0]
        w = fetch("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current=temperature_2m,relative_humidity_2m,weather_code,precipitation_probability&timezone=auto"
                  % (p["latitude"], p["longitude"]))
        cur = w.get("current") or {}
        code = cur.get("weather_code")
        out = {"place": ", ".join(x for x in (p.get("name"), p.get("country")) if x), "temperature_c": cur.get("temperature_2m"),
               "humidity_pct": cur.get("relative_humidity_2m"), "rain_chance_pct": cur.get("precipitation_probability"),
               "condition": WMO.get(code, "—"), "updated": cur.get("time"), "source": "Open-Meteo.com (CC BY 4.0)"}
    except Exception:
        return hit[1] if hit else None
    _WX[place.lower()] = (now_fn(), out)
    return out

WMO = {0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog", 51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
       80: "Rain showers", 81: "Rain showers", 82: "Heavy showers", 95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail"}

def info(c, r, team_family, fetch=None):
    mid, fmt = r["id"], r["format"]
    H, A = team_family(c, r["home_team_id"]), team_family(c, r["away_team_id"])
    before = r["start_utc"] if r["status"] == "scheduled" else "9999"
    vids = _venue_ids(c, r["venue_id"])
    out = {"form": {}, "comparison": {"overall": {}, "venue": {}}}
    for side, ids in (("home", H), ("away", A)):
        last10 = _team_matches(c, ids, fmt, before, mid)
        out["form"][side] = [_match_card(c, m, ids) for m in last10[:5]]
        out["comparison"]["overall"][side] = _comparison(c, ids, last10)
        out["comparison"]["venue"][side] = _comparison(c, ids, _team_matches(c, ids, fmt, before, mid, vids)) if vids else None
    qh, qa = ",".join("?" * len(H)), ",".join("?" * len(A))
    h2h = c.execute(CARD_SQL + "AND m.id<>? AND m.format=? AND ((m.home_team_id IN (%s) AND m.away_team_id IN (%s)) OR (m.home_team_id IN (%s) AND m.away_team_id IN (%s))) ORDER BY m.start_utc DESC LIMIT 10"
                    % (qh, qa, qa, qh), [mid, fmt] + H + A + A + H).fetchall()
    out["h2h"] = {"matches": len(h2h), "home_won": sum(1 for m in h2h if m["winner_team_id"] in H), "away_won": sum(1 for m in h2h if m["winner_team_id"] in A),
                  "items": [_match_card(c, m) for m in h2h]}
    venue = None
    if vids:
        vname = c.execute("SELECT name, city FROM venues WHERE id=?", (r["venue_id"],)).fetchone()
        ms = c.execute(CARD_SQL + "AND m.id<>? AND m.format=? AND m.venue_id IN (%s) ORDER BY m.start_utc DESC" % ",".join("?" * len(vids)), [mid, fmt] + vids).fetchall()
        decided = [m for m in ms if m["result_type"] in ("win", "awarded") and m["winner_team_id"]]
        first, second, bat_first_won, tot = [], [], 0, []
        for m in decided:
            inn = _innings(c, m["id"])
            if len(inn) >= 2:
                first.append(inn[0]["runs"]); second.append(inn[1]["runs"])
                bat_first_won += m["winner_team_id"] == inn[0]["batting_team_id"]
            tot += [(x["runs"], -x["wickets"], x["legal_balls"], x["short_code"] or x["name"], m["id"], x["wickets"]) for x in inn]
        n = len(first)
        card = lambda x: {"runs": x[0], "wickets": x[5], "overs": _ovs(x[2]), "team": x[3], "match_id": x[4]} if x else None
        last10 = [m["id"] for m in ms[:10]]
        venue = {"name": vname["name"], "matches": n, "bat_first_win_pct": round(100 * bat_first_won / n) if n else None,
                 "bowl_first_win_pct": round(100 * (n - bat_first_won) / n) if n else None,
                 "avg_first_innings": round(sum(first) / n) if n else None, "avg_second_innings": round(sum(second) / n) if n else None,
                 "highest": card(max(tot) if tot else None), "lowest": card(min(tot, key=lambda x: (x[0], x[1])) if tot else None),
                 "scores_at_overs": _scores_at_overs(c, last10, QUOTA.get(fmt, 120)) if fmt in QUOTA else None,
                 "pace_spin": _pace_spin(c, last10),
                 "pace_spin_note": None if _pace_spin(c, last10) else "Bowler types are not recorded for these matches yet.",
                 "recent": [_match_card(c, m) for m in ms[:5]]}
        venue["weather"] = weather(c, vname["name"], vname["city"], fetch=fetch)
    out["venue"] = venue
    out["note"] = "From completed %s matches in the SH database. Demo data excluded." % fmt
    return out


# ------------------------------------------------------------------ fantasy
# SH Points (T20). Values follow the T20 fantasy scoring widely published by fantasy platforms
# (e.g. dream11.com/games/point-system, checked 19 Nov 2026). Free to play: no entry fee, no prizes.
PTS = {"xi": 4, "run": 1, "four": 4, "six": 6, "milestones": [(100, 16), (75, 12), (50, 8), (25, 4)], "duck": -2,
       "wicket": 30, "lbw_bowled": 8, "hauls": [(5, 12), (4, 8), (3, 4)], "maiden": 12, "dot": 1,
       "catch": 8, "three_catch": 4, "stumping": 12, "runout_direct": 12, "runout_assist": 6}
SR_BANDS = [(170.0001, 6), (150.0001, 4), (130, 2)]           # min 10 balls; penalties below
SR_PEN = [(50, -6), (60, -4), (70.0001, -2)]
ECO_BANDS = [(5, 6), (6, 4), (7.0001, 2)]                     # min 2 overs; penalties above
ECO_PEN = [(12, -6), (11, -4), (10, -2)]

def _balls(o):
    s = str(o if o is not None else "0").split(".")
    return int(float(s[0] or 0)) * 6 + (int(s[1]) if len(s) > 1 and s[1] else 0)

def _sr_pts(r, b):
    if not b or b < 10:
        return 0
    sr = 100 * r / b
    for lo, p in SR_BANDS:
        if sr >= lo:
            return p
    for hi, p in SR_PEN:
        if sr < hi:
            return p
    return 0

def _eco_pts(runs, balls):
    if balls < 12:
        return 0
    e = runs * 6 / balls
    for hi, p in ECO_BANDS:
        if e < hi:
            return p
    for lo, p in ECO_PEN:
        if e > lo:
            return p
    return 0

def _scorecard_source(c, mid, pd):
    """(innings list, roles by name, source label) from the provider scorecard, else from our own scorecards table."""
    roles = {}
    if pd and pd.get("squads"):
        for t in pd["squads"]:
            for p in t.get("players") or []:
                roles[(p.get("name") or "").lower()] = p.get("role")
    if pd and pd.get("scorecard"):
        return pd["scorecard"], roles, pd.get("source")
    inns = []
    for i in c.execute("SELECT DISTINCT innings_no FROM scorecards WHERE match_id=? ORDER BY innings_no", (mid,)):
        bat, bowl = [], []
        for s in c.execute("SELECT s.*, p.name, p.role FROM scorecards s JOIN players p ON p.id=s.player_id WHERE s.match_id=? AND s.innings_no=?", (mid, i[0])):
            roles.setdefault(s["name"].lower(), s["role"])
            if s["runs"] is not None:
                bat.append({"name": s["name"], "r": s["runs"], "b": s["balls"], "fours": s["fours"], "sixes": s["sixes"], "dismissal": s["dismissal"]})
            if s["overs_bowled"] is not None:
                bowl.append({"name": s["name"], "o": s["overs_bowled"], "m": s["maidens"], "r": s["runs_conceded"], "w": s["wickets"]})
        inns.append({"inning": "Innings %d" % i[0], "batting": bat, "bowling": bowl})
    return inns, roles, "SH database"

def _find(name_part, names):
    """Fielder named in a dismissal ('c Ginger b White', 'st †Wilson') -> full player name when it matches exactly one player."""
    part = re.sub(r"[†(c)\s]+$", "", name_part.replace("†", "")).strip().lower()
    if not part:
        return None
    hits = [n for n in names if n.lower() == part or n.lower().endswith(" " + part.split()[-1]) and (len(part.split()) == 1 or n.lower().endswith(part))]
    return hits[0] if len(hits) == 1 else None

def fantasy(c, r, pd):
    mid = r["id"]
    inns, roles, src = _scorecard_source(c, mid, pd)
    if not inns:
        return {"players": [], "note": NA, "rules": PTS}
    P = {}
    def pl(name, team=None):
        k = name
        if k not in P:
            P[k] = {"name": name, "team": team, "role": roles.get(name.lower()), "ev": {}}
        if team and not P[k]["team"]:
            P[k]["team"] = team
        return P[k]
    def add(p, key, actual, pts):
        e = p["ev"].setdefault(key, [0, 0])
        e[0] += actual; e[1] += pts
    # which team each innings belongs to: batting side is the innings name, bowling side the other
    names = [(r["home_name"], r["home_short"]), (r["away_name"], r["away_short"])]
    def side(inn_name):
        n = re.sub(r"\s*inning\s*\d+$", "", str(inn_name or ""), flags=re.I).strip().lower()
        for i, (full, short) in enumerate(names):
            if n and (n == (full or "").lower() or n == (short or "").lower()):
                return i
        return None
    dots = {}
    balls_full = False
    if pd:
        row = c.execute("SELECT balls_json FROM ext_match_detail WHERE match_id=?", (mid,)).fetchone()
        allb = json.loads(row[0]) if row and row[0] else []
        firsts = {}
        for b in allb:
            firsts.setdefault(str(b.get("inning")), (b.get("over"), b.get("ball")))
            if (b.get("runs") or 0) == 0 and not b.get("extra") and b.get("bowler"):
                dots[b["bowler"]] = dots.get(b["bowler"], 0) + 1
        balls_full = bool(firsts) and all(v == (0, 1) for v in firsts.values())
    else:
        for b in c.execute("""SELECT p.name, COUNT(*) FROM ball_events b JOIN players p ON p.id=b.bowler_id WHERE b.match_id=? AND b.runs_bat=0 AND b.extras=0
                              GROUP BY p.name""", (mid,)):
            dots[b[0]] = b[1]
        balls_full = bool(dots)
    for inn in inns:
        si = side(inn.get("inning"))
        bat_team = names[si][1] or names[si][0] if si is not None else None
        bowl_team = names[1 - si][1] or names[1 - si][0] if si is not None else None
        bowlers = [b["name"] for b in inn.get("bowling") or [] if b.get("name")]
        # fielders = the bowling side: this innings' bowlers plus whoever batted for that side in its own innings
        fielders = sorted(set(bowlers) | {x["name"] for i2 in inns if i2 is not inn and side(i2.get("inning")) not in (si, None) or (si is None and i2 is not inn)
                                          for x in i2.get("batting") or [] if x.get("name")})
        for b in inn.get("batting") or []:
            if not b.get("name"):
                continue
            p = pl(b["name"], bat_team)
            runs, balls = b.get("r") or 0, b.get("b") or 0
            add(p, "runs", runs, runs * PTS["run"])
            add(p, "fours", b.get("fours") or 0, (b.get("fours") or 0) * PTS["four"])
            add(p, "sixes", b.get("sixes") or 0, (b.get("sixes") or 0) * PTS["six"])
            ms = next(((m, v) for m, v in PTS["milestones"] if runs >= m), None)
            if ms:
                add(p, "milestone", ms[0], ms[1])
            sr = _sr_pts(runs, balls)
            if balls >= 10:
                add(p, "sr", round(100 * runs / balls, 2), sr)
            d = (b.get("dismissal") or "").strip()
            out = d and not re.search(r"not out|batting|retired hurt", d, re.I)
            if out and runs == 0 and (p["role"] or "").lower() not in ("bowler",):
                add(p, "duck", 1, PTS["duck"])
            # fielding from the dismissal text
            m_c = re.match(r"^c\s+(.+?)\s+b\s+(.+)$", d)
            m_cb = re.match(r"^c\s*(?:&|and)\s*b\s+(.+)$", d)
            m_st = re.match(r"^st\s+(.+?)\s+b\s+(.+)$", d)
            m_ro = re.match(r"^run out\s*\((.+)\)", d, re.I)
            if m_cb:
                f = _find(m_cb.group(1), fielders)
                if f:
                    add(pl(f, bowl_team), "catches", 1, PTS["catch"])
            elif m_c:
                f = _find(m_c.group(1), fielders)
                if f:
                    add(pl(f, bowl_team), "catches", 1, PTS["catch"])
            elif m_st:
                f = _find(m_st.group(1), fielders)
                if f:
                    add(pl(f, bowl_team), "stumpings", 1, PTS["stumping"])
            elif m_ro:
                who = [x.strip() for x in m_ro.group(1).split("/") if x.strip()]
                for w in who:
                    f = _find(w, fielders)
                    if f:
                        add(pl(f, bowl_team), "run_outs", 1, PTS["runout_direct"] if len(who) == 1 else PTS["runout_assist"])
            m_b = re.match(r"^(?:lbw\s+)?b\s+(.+)$", d)
            if m_b:
                bw = _find(m_b.group(1), bowlers)
                if bw:
                    add(pl(bw, bowl_team), "lbw_bowled", 1, PTS["lbw_bowled"])
        for w in inn.get("bowling") or []:
            if not w.get("name"):
                continue
            p = pl(w["name"], bowl_team)
            wk = w.get("w") or 0
            add(p, "wickets", wk, wk * PTS["wicket"])
            haul = next(((n, v) for n, v in PTS["hauls"] if wk >= n), None)
            if haul:
                add(p, "haul", haul[0], haul[1])
            if w.get("m"):
                add(p, "maidens", w["m"], w["m"] * PTS["maiden"])
            ep = _eco_pts(w.get("r") or 0, _balls(w.get("o")))
            if _balls(w.get("o")) >= 12:
                add(p, "economy", round((w.get("r") or 0) * 6 / _balls(w.get("o")), 2), ep)
            if w["name"] in dots:
                add(p, "dots", dots[w["name"]], dots[w["name"]] * PTS["dot"])
    for p in P.values():
        p["ev"]["announced"] = [1, PTS["xi"]]
        c3 = p["ev"].get("catches", [0])[0]
        if c3 >= 3:
            p["ev"]["three_catch"] = [1, PTS["three_catch"]]
        p["points"] = sum(v[1] for v in p["ev"].values())
    order = ["announced", "runs", "fours", "sixes", "sr", "milestone", "duck", "dots", "wickets", "lbw_bowled", "haul", "maidens", "economy",
             "catches", "three_catch", "stumpings", "run_outs"]
    players = sorted(P.values(), key=lambda x: -x["points"])
    for p in players:
        p["breakdown"] = [{"event": k, "actual": p["ev"].get(k, [None])[0], "points": p["ev"].get(k, [None, None])[1]} for k in order]
        del p["ev"]
    board = _leaderboard(c, mid, {p["name"].lower(): p["points"] for p in players})
    return {"players": players, "source": src, "live": r["status"] == "live", "leaderboard": board,
            "dot_balls": "counted from every ball received" if balls_full else "counted only from the balls received (not every ball of the match)" if dots else "not reported by the source",
            "rules": PTS, "rules_note": "SH Points (T20): free to play, no entry fee, no prizes. Values follow widely published T20 fantasy scoring."}

def _leaderboard(c, mid, pts_by_name):
    out = []
    for t in c.execute("""SELECT f.id, f.user_id, f.players_json, f.captain_id, f.vice_captain_id, COALESCE(a.display_name, a.username, 'SH user') AS name
                          FROM fantasy_teams f LEFT JOIN accounts a ON a.user_id=f.user_id WHERE f.match_id=? AND f.user_id IS NOT NULL""", (mid,)):
        try:
            ids = [x if isinstance(x, int) else x.get("player_id") or x.get("id") for x in json.loads(t["players_json"])]
        except Exception:
            continue
        total = 0.0
        for pid in ids:
            n = c.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()
            v = pts_by_name.get((n[0] if n else "").lower(), 0)
            total += v * (2 if pid == t["captain_id"] else 1.5 if pid == t["vice_captain_id"] else 1)
        out.append({"team_id": t["id"], "name": t["name"], "points": round(total, 1)})
    out.sort(key=lambda x: -x["points"])
    for i, x in enumerate(out):
        x["rank"] = i + 1
    return {"teams": len(out), "items": out[:50]}


# ------------------------------------------------------------------ graphs + live extras
def _over_rows(c, r, pd):
    """[(innings_index, batting_side 'home'/'away'/None, [{over, runs, wkts, balls:[...]}])] from our balls, else the provider's."""
    out = []
    ev = c.execute("SELECT * FROM ball_events WHERE match_id=? ORDER BY innings_no, seq", (r["id"],)).fetchall()
    if ev:
        bat = {i["innings_no"]: i["batting_team_id"] for i in c.execute("SELECT innings_no, batting_team_id FROM innings WHERE match_id=?", (r["id"],))}
        names = {p[0]: p[1] for p in c.execute("SELECT id, name FROM players WHERE id IN (SELECT batter_id FROM ball_events WHERE match_id=? UNION SELECT bowler_id FROM ball_events WHERE match_id=?)", (r["id"], r["id"]))}
        cur = {}
        for b in ev:
            if b["innings_no"] > 2 and r["format"] in QUOTA:
                continue
            o = cur.setdefault(b["innings_no"], {}).setdefault(b["over_no"], {"over": b["over_no"] + 1, "runs": 0, "wkts": 0, "balls": []})
            o["runs"] += b["runs_bat"] + b["extras"]; o["wkts"] += b["is_wicket"]
            o["balls"].append({"r": b["runs_bat"] + b["extras"], "w": bool(b["is_wicket"]), "x": b["extra_type"], "legal": b["extra_type"] not in ("wide", "no_ball"),
                               "batter": names.get(b["batter_id"]), "bowler": names.get(b["bowler_id"])})
        for inn in sorted(cur):
            t = bat.get(inn)
            out.append((inn, "home" if t == r["home_team_id"] else "away" if t == r["away_team_id"] else None, [cur[inn][k] for k in sorted(cur[inn])], True))
        return out, "SH database ball-by-ball"
    if not pd:
        return [], None
    row = c.execute("SELECT balls_json, scorecard_json FROM ext_match_detail WHERE match_id=?", (r["id"],)).fetchone()
    allb = json.loads(row[0]) if row and row[0] else []
    sc = json.loads(row[1]) if row and row[1] else []
    cur, first = {}, {}
    for b in allb:
        k = str(b.get("inning"))
        first.setdefault(k, (b.get("over"), b.get("ball")))
        o = cur.setdefault(k, {}).setdefault(int(b.get("over") or 0), {"over": int(b.get("over") or 0) + 1, "runs": 0, "wkts": 0, "balls": []})
        o["runs"] += b.get("runs") or 0; o["wkts"] += 1 if b.get("wicket") else 0
        o["balls"].append({"r": b.get("runs") or 0, "w": bool(b.get("wicket")), "x": b.get("extra"), "legal": b.get("extra") not in ("wd", "nb", "wide", "no_ball"),
                           "batter": b.get("batter"), "bowler": b.get("bowler")})
    hn, an = (r["home_name"] or "").lower(), (r["away_name"] or "").lower()
    for idx, k in enumerate(sorted(cur, key=lambda x: (len(x), x))):
        name = ""
        try:
            name = re.sub(r"\s*inning\s*\d+$", "", sc[int(k)]["inning"], flags=re.I).strip().lower()
        except Exception:
            pass
        sidek = "home" if name and name == hn else "away" if name and name == an else None
        out.append((idx + 1, sidek, [cur[k][o] for o in sorted(cur[k])], first[k] == (0, 1)))
    return out, "live ball-by-ball"

def graphs(c, r, pd):
    inns, src = _over_rows(c, r, pd)
    if not inns:
        return {"innings": [], "win_probability": [], "note": NA}
    quota = QUOTA.get(r["format"])
    try:
        pre = engine.predict_match(c, r["id"])["home_win_probability"]
    except Exception:
        pre = 50.0
    wp = [{"innings": 1, "over": 0, "home": pre}] if quota else []
    out, first_total = [], None
    for inn, sidek, overs, complete in inns:
        cum_r = cum_w = legal = 0
        rows_ = []
        for o in overs:
            cum_r += o["runs"]; cum_w += o["wkts"]; legal += sum(1 for b in o["balls"] if b["legal"])
            rows_.append({"over": o["over"], "runs": o["runs"], "wickets": o["wkts"], "total": cum_r, "total_wickets": cum_w,
                          "balls": [{"r": b["r"], "w": b["w"], "x": b["x"]} for b in o["balls"]]})
            if quota and complete and inn in (1, 2) and sidek:
                lp = engine.live_probability(r["format"], inn, cum_r, min(cum_w, 10), min(legal, quota),
                                             target=(first_total + 1) if inn == 2 and first_total is not None else None, max_balls=quota,
                                             prematch_home=pre, batting_is_home=sidek == "home")
                if inn == 2 and first_total is None:
                    continue
                bat = lp["batting_team_win_probability"]
                wp.append({"innings": inn, "over": o["over"], "home": bat if sidek == "home" else round(100 - bat, 1)})
        if inn == 1:
            first_total = cum_r if complete else None
        out.append({"innings": inn, "side": sidek, "complete_from_first_ball": complete, "overs": rows_})
    return {"innings": out, "win_probability": wp if len(wp) > 1 else [], "source": src,
            "win_probability_note": "SH AI win probability after each over (our own model; not betting odds)." if len(wp) > 1 else
            "Win probability needs every ball of the innings from the first over; not available for this match.",
            "note": None if all(i["complete_from_first_ball"] for i in out) else "Some overs are missing: the source started sending balls after the match began."}

def live(c, r, pd):
    inns, src = _over_rows(c, r, pd)
    if not inns:
        return {"note": NA}
    inn, sidek, overs, complete = inns[-1]
    balls = [b for o in overs for b in o["balls"]]
    last_w = max((i for i, b in enumerate(balls) if b["w"]), default=None)
    pship = None
    if last_w is not None or complete:
        seg = balls[(last_w + 1) if last_w is not None else 0:]
        pship = {"runs": sum(b["r"] for b in seg), "balls": sum(1 for b in seg if b["legal"])}
    lastwk = None
    if last_w is not None:
        nm = balls[last_w]["batter"]
        lastwk = {"name": nm}
        sc = (pd or {}).get("scorecard") or []
        for i2 in sc[-1:]:
            for b in i2.get("batting") or []:
                if nm and b.get("name") and (b["name"] == nm or b["name"].split()[-1] == nm.split()[-1]):
                    lastwk.update(runs=b.get("r"), balls=b.get("b"), name=b["name"])
    return {"innings": inn, "partnership": pship, "last_wicket": lastwk,
            "last_overs": [{"over": o["over"], "runs": o["runs"], "balls": [{"r": b["r"], "w": b["w"], "x": b["x"]} for b in o["balls"]]} for o in overs[-2:]],
            "source": src}


# ------------------------------------------------------------------ points table + other seasons
def points(c, r, series_detail):
    if not r["competition_id"]:
        return {"table": [], "note": NA}
    d = series_detail(c, r["competition_id"])
    form = {}
    for m in sorted(d["results"], key=lambda x: x["start_utc"]):
        w = m.get("winner_team_id")
        for s in ("home", "away"):
            tid = m[s]["id"]
            form.setdefault(tid, []).append("W" if w == tid else "L" if w else "-")
    for t in d["points_table"]:
        t["form"] = form.get(t["team_id"], [])[-5:]
    name = c.execute("SELECT name FROM competitions WHERE id=?", (r["competition_id"],)).fetchone()[0]
    base = re.sub(r"[\s,]*\b(19|20)\d{2}(/\d{2,4})?\b.*$", "", name).strip()
    others = [dict(x) for x in c.execute("""SELECT id, name FROM competitions WHERE id<>? AND name LIKE ? ORDER BY name DESC LIMIT 10""",
                                           (r["competition_id"], base + "%"))] if len(base) >= 4 else []
    return {"series": d["series"], "table": d["points_table"], "rule": d["points_rule"], "teams": [r["home_team_id"], r["away_team_id"]],
            "other_seasons": others, "top_batters": d["top_batters"], "top_bowlers": d["top_bowlers"]}


# ------------------------------------------------------------------ discussions (fan poll + sorted posts)
def _poll_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS match_fan_votes(match_id INTEGER NOT NULL REFERENCES matches(id), user_id INTEGER NOT NULL REFERENCES users(id),
                 team_id INTEGER NOT NULL REFERENCES teams(id), voted_at TEXT NOT NULL, PRIMARY KEY(match_id, user_id))""")

def fan_poll(c, r, user_id=None, vote_team=None, now=None):
    _poll_table(c)
    if vote_team is not None:
        if r["status"] not in ("scheduled", "live"):
            raise ValueError("voting is closed for this match")
        if int(vote_team) not in (r["home_team_id"], r["away_team_id"]):
            raise ValueError("vote for one of the two teams")
        c.execute("INSERT INTO match_fan_votes VALUES(?,?,?,?) ON CONFLICT(match_id,user_id) DO UPDATE SET team_id=excluded.team_id, voted_at=excluded.voted_at",
                  (r["id"], user_id, int(vote_team), now))
    cnt = dict(c.execute("SELECT team_id, COUNT(*) FROM match_fan_votes WHERE match_id=? GROUP BY team_id", (r["id"],)).fetchall())
    mine = c.execute("SELECT team_id FROM match_fan_votes WHERE match_id=? AND user_id=?", (r["id"], user_id)).fetchone() if user_id else None
    total = sum(cnt.values())
    opt = lambda tid, nm: {"team_id": tid, "team": nm, "votes": cnt.get(tid, 0), "pct": round(100 * cnt.get(tid, 0) / total) if total else 0}
    return {"question": "Who will win this match?", "votes": total, "open": r["status"] in ("scheduled", "live"),
            "options": [opt(r["home_team_id"], r["home_short"] or r["home_name"]), opt(r["away_team_id"], r["away_short"] or r["away_name"])],
            "my_vote": mine[0] if mine else None, "note": "Fan vote of SH users. Free, no money involved; it is not the SH AI prediction."}


# ------------------------------------------------------------------ tipster reports for the Live tab
def tipsters(c, r, window):
    """Every tipster's locked pre-match report for this match (never changed) and, below it, their one innings-break update."""
    rows_ = c.execute("""SELECT p.id, p.expert_id, p.prediction_type, p.predicted_value, p.confidence, p.explanation, p.locked_at,
            x.display_name, x.verified, a.username, t.name AS team, e.result,
            (SELECT body FROM posts po WHERE po.prediction_id=p.id AND po.status='published' ORDER BY po.id LIMIT 1) AS post_body
            FROM predictions p JOIN expert_profiles x ON x.id=p.expert_id LEFT JOIN accounts a ON a.user_id=x.user_id
            LEFT JOIN teams t ON t.id=p.predicted_team_id
            LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
            WHERE p.match_id=? AND p.expert_id IS NOT NULL AND p.locked_at IS NOT NULL AND p.status='locked' AND p.data_origin<>'demo'
              AND (EXISTS(SELECT 1 FROM prediction_publications pp WHERE pp.prediction_id=p.id)
                   OR EXISTS(SELECT 1 FROM posts po WHERE po.prediction_id=p.id AND po.status='published'))
            ORDER BY p.locked_at, p.id""", (r["id"],)).fetchall()
    import api_v1
    timing = lambda at: api_v1.timing_weight(c, r["id"], at)
    by = {}
    for p in rows_:
        e = by.setdefault(p["expert_id"], {"expert_id": p["expert_id"], "name": p["display_name"], "username": p["username"],
                                           "verified": bool(p["verified"]), "first_at": p["locked_at"], "reports": [], "update": None})
        item = {"type": p["prediction_type"], "pick": p["team"] if p["team"] else (None if p["predicted_value"] is None else int(p["predicted_value"])),
                "confidence": p["confidence"], "note": p["explanation"] or p["post_body"], "at": p["locked_at"], "result": p["result"],
                "after_toss": timing(p["locked_at"]) < 1}
        if p["prediction_type"] == "live_winner":
            e["update"] = item
        else:
            e["reports"].append(item)
    return {"items": sorted(by.values(), key=lambda x: x["first_at"]), "window": window,
            "rule": "Toss picks lock at the toss; winner and score picks close 10 minutes after the toss or at the first ball. A pick can be changed for 5 minutes after posting. "
                    "Each tipster may add one update only in the innings break, before the next innings' first ball; the original report never changes. Picks made before the toss rank higher."}


# ------------------------------------------------------------------ series player stats + Analysis drill-down
CATS = {"fantasy": "Fantasy Points", "runs": "Most Runs", "wickets": "Most Wickets", "sixes": "Most Sixes", "highest": "Highest Score",
        "figures": "Best Figures", "sr": "Best Strike Rate", "econ": "Best Economy"}
MIN_SR_BALLS = 10                    # strike rate needs at least 10 balls faced in the selection
MIN_ECON_BALLS = {"T10": 6}          # economy needs 1 over in T10, 2 overs elsewhere

def _records(c, r, provider_detail):
    """One record per player per completed match of this series: batting, bowling, fantasy points, opponent, venue, date."""
    ms = c.execute("""SELECT m.id, m.start_utc, m.venue_id, m.home_team_id, m.away_team_id, m.format, h.name AS home_name, a.name AS away_name,
                      CASE WHEN h.short_code_approved THEN h.short_code END AS home_short, CASE WHEN a.short_code_approved THEN a.short_code END AS away_short
                      FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
                      WHERE m.competition_id=? AND m.data_origin<>'demo' AND m.status='completed' ORDER BY m.start_utc""", (r["competition_id"],)).fetchall()
    out, used = [], []
    for m in ms:
        M = dict(m)
        M["status"] = "completed"
        pd = provider_detail(c, m["id"])
        inns, _, src = _scorecard_source(c, m["id"], pd)
        if not inns or not any(i.get("batting") or i.get("bowling") for i in inns):
            continue
        used.append(m["id"])
        fp = {p["name"]: p for p in fantasy(c, M, pd)["players"]}
        names = [(m["home_name"], m["home_short"], m["home_team_id"]), (m["away_name"], m["away_short"], m["away_team_id"])]
        def side(inn_name, idx):
            n = re.sub(r"\s*inning\s*\d+$", "", str(inn_name or ""), flags=re.I).strip().lower()
            for i, (full, short, _) in enumerate(names):
                if n and n in ((full or "").lower(), (short or "").lower()):
                    return i
            if pd is None:
                b = c.execute("SELECT batting_team_id FROM innings WHERE match_id=? AND innings_no=?", (m["id"], idx + 1)).fetchone()
                if b:
                    return 0 if b[0] == m["home_team_id"] else 1
            return None
        P = {}
        def rec(name, si):
            k = name
            if k not in P:
                team = names[si] if si is not None else (None, None, None)
                opp = names[1 - si] if si is not None else (None, None, None)
                P[k] = {"name": name, "team": team[1] or team[0], "team_id": team[2], "opp_id": opp[2], "opp": opp[1] or opp[0],
                        "match_id": m["id"], "date": m["start_utc"][:10], "venue_id": m["venue_id"],
                        "bat": None, "bowl": None, "fantasy": fp.get(name, {}).get("points", 0.0), "source": src}
            return P[k]
        for idx, inn in enumerate(inns):
            si = side(inn.get("inning"), idx)
            for b in inn.get("batting") or []:
                if not b.get("name"):
                    continue
                x = rec(b["name"], si)
                d = (b.get("dismissal") or "").strip()
                x["bat"] = {"r": b.get("r") or 0, "b": b.get("b") or 0, "fours": b.get("fours") or 0, "sixes": b.get("sixes") or 0,
                            "out": bool(d) and not re.search(r"not out|batting|retired hurt", d, re.I)}
            for w in inn.get("bowling") or []:
                if not w.get("name"):
                    continue
                x = rec(w["name"], 1 - si if si is not None else None)
                x["bowl"] = {"balls": _balls(w.get("o")), "o": str(w.get("o")), "r": w.get("r") or 0, "w": w.get("w") or 0}
        out += P.values()
    return out, used

def series_stats(c, r, provider_detail, cat="fantasy", last=None, venue=False, vs=None, view="table", limit=50):
    if not r["competition_id"]:
        return {"items": [], "note": NA}
    if cat not in CATS:
        raise ValueError("cat must be one of " + ", ".join(CATS))
    if vs not in (None, "", "home", "away"):
        raise ValueError("vs must be home or away")
    recs, used = _records(c, r, provider_detail)
    # filters are independent dimensions: time window (last N per player), venue, opponent
    if venue:
        vids = _venue_ids(c, r["venue_id"])
        recs = [x for x in recs if x["venue_id"] in vids]
    if vs:
        opp = r["home_team_id"] if vs == "home" else r["away_team_id"]
        recs = [x for x in recs if x["opp_id"] == opp]
    by = {}
    for x in sorted(recs, key=lambda x: x["date"], reverse=True):
        by.setdefault((x["name"], x["team"]), []).append(x)
    if last:
        by = {k: v[:int(last)] for k, v in by.items()}
    rows_, min_econ = [], MIN_ECON_BALLS.get(r["format"], 12)
    for (name, team), xs in by.items():
        bats = [x["bat"] for x in xs if x["bat"]]
        bowls = [x["bowl"] for x in xs if x["bowl"]]
        row = {"name": name, "team": team, "matches": len(xs), "match_ids": [x["match_id"] for x in xs]}
        if cat == "fantasy":
            row.update(value=round(sum(x["fantasy"] for x in xs), 1), inns=len(xs), display="%g" % round(sum(x["fantasy"] for x in xs), 1))
        elif cat in ("runs", "sixes"):
            if not bats:
                continue
            key = "r" if cat == "runs" else "sixes"
            v = sum(b[key] for b in bats)
            row.update(value=v, inns=len(bats), display=str(v), runs=sum(b["r"] for b in bats), balls=sum(b["b"] for b in bats),
                       fours=sum(b["fours"] for b in bats), sixes=sum(b["sixes"] for b in bats),
                       avg=round(sum(b["r"] for b in bats) / max(1, sum(1 for b in bats if b["out"])), 2) if any(b["out"] for b in bats) else None,
                       sr=round(100 * sum(b["r"] for b in bats) / sum(b["b"] for b in bats), 2) if sum(b["b"] for b in bats) else None)
        elif cat == "highest":
            if not bats:
                continue
            best = max(bats, key=lambda b: (b["r"], not b["out"], -b["b"]))
            row.update(value=best["r"], inns=len(bats), display="%d%s" % (best["r"], "" if best["out"] else "*"), balls=best["b"])
        elif cat == "sr":
            balls = sum(b["b"] for b in bats)
            if balls < MIN_SR_BALLS:
                continue
            v = round(100 * sum(b["r"] for b in bats) / balls, 2)
            row.update(value=v, inns=len(bats), display="%.2f" % v, runs=sum(b["r"] for b in bats), balls=balls)
        elif cat == "wickets":
            if not bowls:
                continue
            v = sum(b["w"] for b in bowls)
            balls = sum(b["balls"] for b in bowls)
            row.update(value=v, inns=len(bowls), display=str(v), runs_conceded=sum(b["r"] for b in bowls), overs=_ovs(balls),
                       econ=round(6 * sum(b["r"] for b in bowls) / balls, 2) if balls else None)
        elif cat == "figures":
            if not bowls:
                continue
            best = max(bowls, key=lambda b: (b["w"], -b["r"], -b["balls"]))
            row.update(value=(best["w"], -best["r"]), inns=len(bowls), display="%d-%d" % (best["r"], best["w"]), overs=best["o"])
        elif cat == "econ":
            balls = sum(b["balls"] for b in bowls)
            if balls < min_econ:
                continue
            v = round(6 * sum(b["r"] for b in bowls) / balls, 2)
            row.update(value=v, inns=len(bowls), display="%.2f" % v, overs=_ovs(balls))
        rows_.append(row)
    asc = cat == "econ"
    rows_.sort(key=lambda x: (x["value"] if not asc else -x["value"], -x["inns"] if cat in ("sr", "econ") else 0), reverse=True)
    for i, x in enumerate(rows_):
        x["rank"] = i + 1
        if isinstance(x["value"], tuple):
            x["value"] = x["value"][0]
    recent = None
    if view == "recent":
        keys = {(x["name"], x["team"]) for x in rows_[:10]}
        recent = []
        for (name, team), xs in by.items():
            if (name, team) not in keys:
                continue
            for x in xs:
                b, w = x["bat"], x["bowl"]
                recent.append({"name": name, "team": team, "match_id": x["match_id"], "date": x["date"], "opp": x["opp"], "fantasy": x["fantasy"],
                               "bat": "%d%s (%d)" % (b["r"], "" if b["out"] else "*", b["b"]) if b else None,
                               "bowl": "%d-%d (%s)" % (b2["r"], b2["w"], b2["o"]) if (b2 := w) else None})
        recent.sort(key=lambda x: (x["date"], x["name"]), reverse=True)
    teams = {"home": r["home_short"] or r["home_name"], "away": r["away_short"] or r["away_name"]}
    return {"category": cat, "label": CATS[cat], "categories": CATS, "filters": {"last": int(last) if last else None, "venue": bool(venue), "vs": vs or None},
            "teams": teams, "items": rows_[:limit], "recent": recent, "matches_used": len(used),
            "qualification": {"sr": "at least %d balls faced" % MIN_SR_BALLS, "econ": "at least %s overs bowled" % _ovs(min_econ)}.get(cat),
            "empty": "No matching statistics" if not rows_ else None,
            "note": "From %d completed match(es) of this series with a scorecard. Last 5 = each player's own last 5 matches." % len(used)}


# ------------------------------------------------------------------ SH Prediction XI (dream-team style, free to play)
def _role(s):
    s = (s or "").lower()
    if "keeper" in s or "wk" in s:
        return "wicket_keeper"
    if "allrounder" in s.replace("-", "").replace(" ", ""):
        return "all_rounder"
    if "bowl" in s:
        return "bowler"
    return "batter"

def _nkey(n):
    t = re.sub(r"[^a-z ]", "", (n or "").lower()).split()
    return (t[0][0] + " " + t[-1]) if len(t) >= 2 else (t[0] if t else "")

_FP_CACHE = {}
def _form_points(c, fmt, before, provider_detail, max_matches=80):
    """SH fantasy points per player from recent completed matches of the same format (any competition), newest first."""
    ms = c.execute("""SELECT m.id, m.start_utc, m.home_team_id, m.away_team_id, m.format, m.venue_id, h.name AS home_name, a.name AS away_name,
                      CASE WHEN h.short_code_approved THEN h.short_code END AS home_short, CASE WHEN a.short_code_approved THEN a.short_code END AS away_short,
                      (SELECT scorecard_at FROM ext_match_detail e WHERE e.match_id=m.id) AS sc_at
                      FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
                      WHERE m.format=? AND m.status='completed' AND m.start_utc<? AND m.data_origin<>'demo'
                        AND (EXISTS(SELECT 1 FROM ext_match_detail e WHERE e.match_id=m.id AND e.scorecard_json IS NOT NULL)
                             OR EXISTS(SELECT 1 FROM scorecards s WHERE s.match_id=m.id))
                      ORDER BY m.start_utc DESC LIMIT ?""", (fmt, before, max_matches)).fetchall()
    out = {}
    for m in ms:
        ck = (m["id"], m["sc_at"])
        if ck not in _FP_CACHE:
            M = dict(m); M["status"] = "completed"
            try:
                _FP_CACHE[ck] = [(p["name"], p["points"]) for p in fantasy(c, M, provider_detail(c, m["id"]))["players"]]
            except Exception:
                _FP_CACHE[ck] = []
        for name, pts in _FP_CACHE[ck]:
            for k in {(name or "").lower(), _nkey(name)}:
                out.setdefault(k, []).append((m["start_utc"], pts, m["venue_id"]))
    return out

def _xi_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS prediction_xi_snapshots(match_id INTEGER PRIMARY KEY REFERENCES matches(id), team_json TEXT NOT NULL,
                 created_at TEXT NOT NULL, locked INTEGER NOT NULL DEFAULT 0)""")

def prediction_xi(c, r, provider_detail, now_fn, locked_fn):
    import fantasy as F
    _xi_table(c)
    snap = c.execute("SELECT * FROM prediction_xi_snapshots WHERE match_id=?", (r["id"],)).fetchone()
    is_locked = locked_fn(c, r)
    pd = provider_detail(c, r["id"])
    rule_name, R = F.rules(c)
    if snap and (snap["locked"] or is_locked):
        team = json.loads(snap["team_json"])
        if is_locked and not snap["locked"]:
            c.execute("UPDATE prediction_xi_snapshots SET locked=1 WHERE match_id=?", (r["id"],))
    else:
        # pool: the announced XI (12 or fewer per side) or the squad from the source, else our own XI / squad tables
        pool, status = [], "squad"
        teams = {(r["home_name"] or "").lower(): r["home_team_id"], (r["away_name"] or "").lower(): r["away_team_id"],
                 (r["home_short"] or "~").lower(): r["home_team_id"], (r["away_short"] or "~").lower(): r["away_team_id"]}
        if pd and pd.get("squads"):
            sq = [t for t in pd["squads"] if (t.get("team") or "").lower() in teams]
            if sq and all(len(t.get("players") or []) <= 12 for t in sq):
                status = "playing_xi"
            for t in sq:
                for p in t.get("players") or []:
                    if p.get("name"):
                        pool.append({"name": p["name"], "team_id": teams[(t["team"] or "").lower()], "role": _role(p.get("role"))})
        if not pool:
            try:
                _, ps, st = F.pool(c, r["id"])
                pool = [{"name": p["name"], "team_id": p["team_id"], "role": p["role"]} for p in ps]
                status = "playing_xi" if st == "confirmed" else "squad"
            except LookupError:
                pool = []
        if len(pool) < R["team_size"]:
            return {"available": False, "reason": "Playing XI / squad not available from the source yet.", "rule_set": rule_name}
        form = _form_points(c, r["format"], r["start_utc"], provider_detail)
        vids = set(_venue_ids(c, r["venue_id"])) if r["venue_id"] else set()
        for i, p in enumerate(pool):
            hist = form.get(p["name"].lower()) or form.get(_nkey(p["name"])) or []
            last = [x[1] for x in sorted(hist, reverse=True)[:5]]
            at_v = [x[1] for x in hist if x[2] in vids]
            if last:
                exp = sum(last) / len(last)
                if len(at_v) >= 2:
                    exp = 0.8 * exp + 0.2 * (sum(at_v) / len(at_v))
                conf = "high" if len(last) >= 5 else "medium" if len(last) >= 2 else "low"
            else:
                exp, conf = F.ROLE_BASE[p["role"]], "low"
            p.update(player_id=i + 1, expected_points=round(exp, 1), confidence=conf, form=last, venue_matches=len(at_v))
        team, ok = F._pick(pool, R, r["home_team_id"], r["away_team_id"])
        if not ok:
            return {"available": False, "reason": "Role limits of rule set '%s' cannot be met with the known players." % rule_name, "rule_set": rule_name}
        order = sorted(team, key=lambda p: -p["expected_points"])
        for p in team:
            p["captain"] = p is order[0]
            p["vice_captain"] = p is order[1]
        team = {"players": team, "pool_status": status, "built_at": now_fn()}
        c.execute("INSERT INTO prediction_xi_snapshots(match_id,team_json,created_at,locked) VALUES(?,?,?,?) "
                  "ON CONFLICT(match_id) DO UPDATE SET team_json=excluded.team_json, created_at=excluded.created_at, locked=excluded.locked",
                  (r["id"], json.dumps(team), now_fn(), 1 if is_locked else 0))
    mult = lambda p: R["captain_multiplier"] if p.get("captain") else R["vice_captain_multiplier"] if p.get("vice_captain") else 1
    expected = round(sum(p["expected_points"] * mult(p) for p in team["players"]), 1)
    out = {"available": True, "rule_set": rule_name, "rules": R, "pool_status": team["pool_status"], "built_at": team["built_at"],
           "locked": bool(is_locked), "players": team["players"], "expected_points": expected,
           "note": "SH Prediction XI: our model's best 11 from recent SH fantasy points in this format (last 5 matches, venue form when known). "
                   "Free to play, no money. It updates until the toss and is then locked."}
    # after the first ball: how the locked XI actually scored, and the best possible XI (dream team) for comparison
    if r["status"] in ("live", "completed"):
        actual = {p["name"].lower(): p["points"] for p in fantasy(c, r, pd)["players"]}
        akey = {_nkey(k): v for k, v in actual.items()}
        got = lambda n: actual.get(n.lower(), akey.get(_nkey(n), 0.0))
        for p in out["players"]:
            p["actual_points"] = got(p["name"])
        out["actual_points"] = round(sum(p["actual_points"] * mult(p) for p in out["players"]), 1)
        allp = [dict(p, expected_points=got(p["name"])) for p in _pool_for_dream(c, r, pd, team["players"])]
        best, ok = F._pick(allp, R, r["home_team_id"], r["away_team_id"]) if len(allp) >= R["team_size"] else ([], False)
        if ok:
            bo = sorted(best, key=lambda p: -p["expected_points"])
            dream = [{"name": p["name"], "team_id": p["team_id"], "role": p["role"], "actual_points": p["expected_points"],
                      "captain": p is bo[0], "vice_captain": p is bo[1]} for p in best]
            out["dream_team"] = {"players": dream, "points": round(sum(p["actual_points"] * mult(p) for p in dream), 1)}
            out["accuracy_pct"] = round(100 * out["actual_points"] / out["dream_team"]["points"]) if out["dream_team"]["points"] > 0 else None
            names = {p["name"] for p in dream}
            out["in_dream_team"] = sum(1 for p in out["players"] if p["name"] in names)
    return out

def _pool_for_dream(c, r, pd, fallback):
    teams = {(r["home_name"] or "").lower(): r["home_team_id"], (r["away_name"] or "").lower(): r["away_team_id"]}
    pool = []
    for t in (pd or {}).get("squads") or []:
        tid = teams.get((t.get("team") or "").lower())
        for p in t.get("players") or []:
            if tid and p.get("name"):
                pool.append({"name": p["name"], "team_id": tid, "role": _role(p.get("role"))})
    pool = pool or [{"name": p["name"], "team_id": p["team_id"], "role": p["role"]} for p in fallback]
    for i, p in enumerate(pool):
        p["player_id"] = i + 1
        p["confidence"] = "high"
    return pool


# ------------------------------------------------------------------ SH Agent Prediction: immutable stage snapshots
STAGES = ("pre_match", "post_toss", "playing_xi")

def _agent_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS sh_agent_snapshots(match_id INTEGER NOT NULL REFERENCES matches(id), stage TEXT NOT NULL,
                 payload_json TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(match_id, stage))""")

def _ball_bowled(c, r, pd):
    if c.execute("SELECT 1 FROM ball_events WHERE match_id=? LIMIT 1", (r["id"],)).fetchone():
        return True
    if pd and (pd.get("scorecard") or []):
        if any((i.get("total") or {}).get("o") not in (None, 0, "0", "0.0") for i in pd["scorecard"]) or \
           any((b.get("b") or 0) > 0 for i in pd["scorecard"] for b in i.get("batting") or []) or \
           any(_balls(w.get("o")) > 0 for i in pd["scorecard"] for w in i.get("bowling") or []):
            return True
    if pd and pd.get("balls"):
        return True
    ls = c.execute("SELECT innings_json FROM live_scores WHERE match_id=?", (r["id"],)).fetchone() if \
        c.execute("SELECT 1 FROM sqlite_master WHERE name='live_scores'").fetchone() else None
    if ls and any(_balls(x.get("o")) > 0 for x in json.loads(ls[0] or "[]")):
        return True
    return r["status"] in ("completed",)

def agent_capture(c, r, provider_detail, now_fn, xi_fn=None):
    """Store each stage once (INSERT OR IGNORE): pre-match before the toss, post-toss after the toss and before the first ball,
    Playing XI once both XIs are known and before the first ball. A stored stage is never changed."""
    _agent_table(c)
    pd = provider_detail(c, r["id"])
    toss = c.execute("SELECT winner_team_id, decision, verified_at, source FROM toss_results WHERE match_id=?", (r["id"],)).fetchone()
    bowled = _ball_bowled(c, r, pd)
    have = {x[0] for x in c.execute("SELECT stage FROM sh_agent_snapshots WHERE match_id=?", (r["id"],))}
    made = []
    def put(stage, p, extra=None):
        payload = {"home_win_probability": p["home_win_probability"], "away_win_probability": p["away_win_probability"],
                   "predicted_team_id": p["predicted_team_id"], "confidence": p["confidence"], "confidence_level": p.get("confidence_level"),
                   "factors": p.get("factors"), "history_matches_used": p.get("history_matches_used")}
        payload.update(extra or {})
        if c.execute("INSERT OR IGNORE INTO sh_agent_snapshots(match_id,stage,payload_json,model,created_at) VALUES(?,?,?,?,?)",
                     (r["id"], stage, json.dumps(payload), p["model"], now_fn())).rowcount:
            made.append(stage)
    if "pre_match" not in have and not toss and r["status"] == "scheduled":
        put("pre_match", engine.predict_match(c, r["id"], use_toss=False))
    if toss and not bowled and "post_toss" not in have:
        put("post_toss", engine.predict_match(c, r["id"], use_toss=True),
            {"toss": {"team_id": toss[0], "decision": toss[1], "source": toss[3]}})
    if not bowled and "playing_xi" not in have and xi_fn:
        xi = xi_fn()
        if xi and xi.get("available") and xi.get("pool_status") == "playing_xi":
            p = engine.predict_match(c, r["id"], use_toss=bool(toss))
            sh = sum(x["expected_points"] for x in xi["players"] if x["team_id"] == r["home_team_id"])
            sa = sum(x["expected_points"] for x in xi["players"] if x["team_id"] == r["away_team_id"])
            # XI adjustment: shift the log-odds by the two XIs' expected SH fantasy strength (bounded to +/-0.4)
            adj = max(-0.4, min(0.4, 1.5 * (sh - sa) / (sh + sa))) if sh + sa > 0 else 0.0
            import math
            x = math.log(p["home_win_probability"] / max(0.1, 100 - p["home_win_probability"])) + adj
            ph = 100 / (1 + math.exp(-x))
            p = dict(p, home_win_probability=round(ph, 1), away_win_probability=round(100 - ph, 1),
                     predicted_team_id=r["home_team_id"] if ph >= 50 else r["away_team_id"], confidence=round(max(ph, 100 - ph), 1),
                     factors=(p.get("factors") or []) + [{"factor": "playing_xi_strength", "detail": "SH Prediction XI expected points %.0f v %.0f" % (sh, sa),
                                                          "contribution": round(adj, 3)}])
            put("playing_xi", p)
    return made

def _innings_now(c, r, pd):
    """Current innings totals [(batting side 'home'/'away'/None, runs, wkts, balls)] from the live score row, else the provider scorecard."""
    out = []
    ls = c.execute("SELECT innings_json FROM live_scores WHERE match_id=?", (r["id"],)).fetchone() if \
        c.execute("SELECT 1 FROM sqlite_master WHERE name='live_scores'").fetchone() else None
    rows_ = json.loads(ls[0]) if ls and ls[0] else []
    src = "live score"
    if not rows_ and pd and pd.get("scorecard"):
        src = "scorecard"
        for i in pd["scorecard"]:
            t = i.get("total") or {}
            if t.get("r") is None:
                bat = i.get("batting") or []
                t = {"r": sum(b.get("r") or 0 for b in bat) + ((i.get("extras") or {}).get("total") or 0),
                     "w": sum(1 for b in bat if b.get("dismissal") and not re.search(r"not out|batting", b["dismissal"], re.I)),
                     "o": _ovs(sum(_balls(b.get("o")) for b in i.get("bowling") or []))}
            rows_.append({"inning": i.get("inning"), "r": t.get("r"), "w": t.get("w"), "o": t.get("o")})
    hn, an = (r["home_name"] or "").lower(), (r["away_name"] or "").lower()
    for x in rows_:
        n = re.sub(r"\s*inning\s*\d+$", "", str(x.get("inning") or ""), flags=re.I).strip().lower()
        side = "home" if n in (hn, (r["home_short"] or "~").lower()) else "away" if n in (an, (r["away_short"] or "~").lower()) else None
        out.append((side, int(x.get("r") or 0), int(x.get("w") or 0), _balls(x.get("o"))))
    return out, src

def live_from_score(c, r, pd, snaps):
    """SH live win % from the current score (runs, wickets, balls, target) with the saved pre-match view as the prior. Limited-overs only."""
    quota = QUOTA.get(r["format"])
    inns, src = _innings_now(c, r, pd)
    if not quota or not inns or inns[-1][0] is None:
        return None
    base = (snaps.get("playing_xi") or snaps.get("post_toss") or snaps.get("pre_match") or {}).get("home_win_probability")
    if base is None:
        try:
            base = engine.predict_match(c, r["id"])["home_win_probability"]
        except Exception:
            base = 50.0
    k = len(inns)
    side, runs, wk, balls = inns[-1]
    if k >= 2 and inns[0][0] is None:
        return None
    lp = engine.live_probability(r["format"], min(k, 2), runs, min(wk, 10), min(balls, quota), target=(inns[0][1] + 1) if k >= 2 else None,
                                 max_balls=quota, prematch_home=base, batting_is_home=side == "home")
    bat = lp["batting_team_win_probability"]
    home = bat if side == "home" else round(100 - bat, 1)
    return {"home_win_probability": home, "away_win_probability": round(100 - home, 1), "after_over": _ovs(balls), "innings": min(k, 2),
            "source": "SH model from the %s (%d-%d in %s overs)" % (src, runs, wk, _ovs(balls))}

def agent(c, r, provider_detail, now_fn, xi_fn=None):
    agent_capture(c, r, provider_detail, now_fn, xi_fn)
    snaps = {x["stage"]: dict(json.loads(x["payload_json"]), stage=x["stage"], model=x["model"], created_at=x["created_at"])
             for x in c.execute("SELECT * FROM sh_agent_snapshots WHERE match_id=?", (r["id"],))}
    live = None
    if r["status"] == "live":
        g = graphs(c, r, provider_detail(c, r["id"]))
        if g.get("win_probability"):
            w = g["win_probability"][-1]
            live = {"home_win_probability": w["home"], "away_win_probability": round(100 - w["home"], 1), "after_over": w["over"], "innings": w["innings"],
                    "source": g.get("source")}
        else:
            live = live_from_score(c, r, provider_detail(c, r["id"]), snaps)
    res = c.execute("SELECT result_type, winner_team_id, source FROM match_results WHERE match_id=?", (r["id"],)).fetchone()
    for s in snaps.values():
        if res and res[0] == "win":
            s["outcome"] = "correct" if s["predicted_team_id"] == res[1] else "incorrect"
        elif res:
            s["outcome"] = "void"
    tm = lambda tid: r["home_name"] if tid == r["home_team_id"] else r["away_name"] if tid == r["away_team_id"] else None
    for s in snaps.values():
        s["predicted_team"] = tm(s["predicted_team_id"])
    order = [s for s in STAGES if s in snaps]
    head = snaps[order[-1]] if order else None
    insufficient = bool(head and not live and not (head.get("history_matches_used") or 0))
    return {"stages": [snaps[s] for s in order], "live": live, "insufficient": insufficient,
            "insufficient_note": "Not enough verified match history for these two teams yet, so SH shows no percentage instead of a guessed 50-50." if insufficient else None,
            "headline": snaps[order[-1]] if order else None,
            "result": {"type": res[0], "winner": tm(res[1]), "source": res[2]} if res else None,
            "verification": "Model output from verified match history; not a guarantee. Each stage is saved once and never changed.",
            "note": None if order else ("No prediction was saved before this match started." if r["status"] != "scheduled"
                                        else "The pre-match prediction is saved when this page or the scheduler first sees the match before the toss.")}
