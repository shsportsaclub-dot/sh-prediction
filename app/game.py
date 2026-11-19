"""SH Cricket Game engine — our own virtual cricket simulation and real-match replay directives.

Virtual matches are stored in game_matches / game_events only and are never mixed with real results.
Law and playing-condition checks implemented (validate_over / LawsError):
 * Law 17: six fair balls per over; wides and no balls are re-bowled; a bowler may not bowl two consecutive overs.
 * Playing conditions: bowler quota (T10 2, T20 4, ODI 10 overs); free hit after a no ball (only run out is possible).
 * Law 18: batters change ends on odd runs; ends change at the end of an over.
 * Law 13/16: innings ends at 10 wickets, end of allotted overs, or when the target is passed.
Animation: every ball produces a directive {type, result, direction_deg, distance, height, reconstructed}. Virtual balls carry
simulated geometry (reconstructed=False because the simulation itself decided it). Real-match replays only know the
recorded outcome, so geometry is a labelled reconstruction (reconstructed=True) unless a scorer recorded a direction.
"""
import json
import random

from schema import now

FORMATS = {"T10": {"overs": 10, "quota": 2, "intent": 1.25, "risk": 0.05}, "T20": {"overs": 20, "quota": 4, "intent": 1.0, "risk": 0.042},
           "ODI": {"overs": 50, "quota": 10, "intent": 0.6, "risk": 0.028}}
DISMISSALS_PACE = ["bowled", "caught", "caught", "caught", "lbw", "run out"]
DISMISSALS_SPIN = ["bowled", "caught", "caught", "lbw", "stumped", "run out"]

class LawsError(Exception):
    pass

def default_team(name, seed):
    r = random.Random(seed)
    roles = ["bat"] * 5 + ["wk"] + ["all"] * 2 + ["bowl"] * 3
    players = []
    for i, role in enumerate(roles):
        bat = r.randint(55, 85) if role in ("bat", "wk") else (r.randint(45, 70) if role == "all" else r.randint(15, 40))
        bowl = r.randint(60, 85) if role == "bowl" else (r.randint(50, 72) if role == "all" else r.randint(5, 25))
        players.append({"name": "%s %d" % (name, i + 1), "bat": bat, "aggression": r.randint(30, 80), "bowl": bowl,
                        "bowl_type": "spin" if i in (7, 9) else "pace", "keeper": role == "wk"})
    return {"name": name, "players": players}

def validate_team(t):
    if not isinstance(t, dict) or not str(t.get("name") or "").strip() or not isinstance(t.get("players"), list) or len(t["players"]) != 11:
        raise LawsError("a team needs a name and exactly 11 players (Law 1)")
    for p in t["players"]:
        for k in ("bat", "bowl", "aggression"):
            if not isinstance(p.get(k), (int, float)) or not 0 <= p[k] <= 100:
                raise LawsError("player attributes bat/bowl/aggression must be 0-100")
    if sum(1 for p in t["players"] if p.get("keeper")) != 1:
        raise LawsError("exactly one wicket-keeper is required")
    return t

class Innings:
    def __init__(self, bat, bowl, fmt, target, rng):
        self.bat, self.bowl, self.fmt, self.target, self.rng = bat, bowl, FORMATS[fmt], target, rng
        self.runs = self.wkts = self.legal = 0
        self.striker, self.non_striker, self.next_in = 0, 1, 2
        self.bowler_overs = {}
        self.last_bowler = None
        self.free_hit = False
        self.events = []
        self.batter_runs = {}

    def done(self):
        return self.wkts >= 10 or self.legal >= self.fmt["overs"] * 6 or (self.target is not None and self.runs >= self.target)

    def choose_bowler(self, over_no):
        """AI: best bowler allowed by Law 17.8 and quota; spinners preferred in the middle overs."""
        overs = self.fmt["overs"]
        middle = 0.3 * overs <= over_no < 0.75 * overs
        cands = [i for i, p in enumerate(self.bowl["players"]) if i != self.last_bowler and self.bowler_overs.get(i, 0) < self.fmt["quota"] and not p.get("keeper")]
        if not cands:
            raise LawsError("no legal bowler available")
        def score(i):
            p = self.bowl["players"][i]
            return p["bowl"] + (8 if middle and p["bowl_type"] == "spin" else 0) + (6 if not middle and p["bowl_type"] == "pace" else 0) - 3 * self.bowler_overs.get(i, 0)
        return max(cands, key=score)

    def aggression(self, batter):
        """AI batting intent from phase, wickets in hand and required rate."""
        overs_left = self.fmt["overs"] - self.legal / 6
        a = batter["aggression"] / 100
        if self.legal < 0.3 * self.fmt["overs"] * 6:
            a += 0.1
        if overs_left < 0.25 * self.fmt["overs"]:
            a += 0.25
        if self.target is not None and overs_left > 0:
            rrr = (self.target - self.runs) / overs_left
            a += max(-0.2, min(0.4, (rrr - 8) * 0.06))
        a -= 0.04 * max(0, self.wkts - 5)
        return max(0.05, min(0.95, a * self.fmt["intent"]))

    def ball(self, bowler_i, over_no, ball_in_over):
        bt = self.bat["players"][self.striker]
        bw = self.bowl["players"][bowler_i]
        r = self.rng.random()
        if r < 0.035:
            return {"extra_type": "wide", "runs_bat": 0, "extras": 1}
        if r < 0.05:
            return {"extra_type": "no_ball", "runs_bat": self.rng.choice([0, 0, 1, 4]), "extras": 1}
        skill = (bt["bat"] - bw["bowl"]) / 100
        agg = self.aggression(bt)
        p_out = max(0.008, self.fmt["risk"] - 0.035 * skill + 0.025 * agg)
        if self.free_hit:
            p_out *= 0.15  # only a run out is possible on a free hit
        x = self.rng.random()
        if x < p_out:
            kinds = DISMISSALS_SPIN if bw["bowl_type"] == "spin" else DISMISSALS_PACE
            kind = "run out" if self.free_hit else self.rng.choice(kinds)
            return {"wicket": kind, "runs_bat": 0, "extras": 0}
        if self.rng.random() < 0.02:
            return {"extra_type": self.rng.choice(["bye", "leg_bye"]), "runs_bat": 0, "extras": self.rng.choice([1, 1, 4])}
        weights = [max(0.08, 0.42 - 0.22 * agg - 0.08 * skill), 0.36, 0.07 + 0.03 * agg, 0.01, 0.06 + 0.08 * agg + 0.04 * skill, 0.015 + 0.07 * agg + 0.03 * skill]
        runs = self.rng.choices([0, 1, 2, 3, 4, 6], weights)[0]
        return {"runs_bat": runs, "extras": 0}

    def play(self, seq_start, innings_no):
        seq = seq_start
        over_no = 0
        while not self.done():
            bi = self.choose_bowler(over_no)
            if bi == self.last_bowler:
                raise LawsError("Law 17.8: consecutive overs by the same bowler")
            legal_in_over = 0
            while legal_in_over < 6 and not self.done():
                o = self.ball(bi, over_no, legal_in_over)
                seq += 1
                et = o.get("extra_type")
                legal = et not in ("wide", "no_ball")
                runs = o["runs_bat"] + o["extras"]
                self.runs += runs
                striker_name = self.bat["players"][self.striker]["name"]
                wicket = o.get("wicket")
                if legal:
                    legal_in_over += 1
                    self.legal += 1
                if o["runs_bat"]:
                    self.batter_runs[striker_name] = self.batter_runs.get(striker_name, 0) + o["runs_bat"]
                ev = {"innings_no": innings_no, "seq": seq, "over_no": over_no, "ball_in_over": legal_in_over, "batter": striker_name,
                      "bowler": self.bowl["players"][bi]["name"], "runs_bat": o["runs_bat"], "extras": o["extras"], "extra_type": et,
                      "is_wicket": 1 if wicket else 0, "wicket_kind": wicket, "free_hit": self.free_hit, "batting_team_id": innings_no,
                      "score": "%d/%d" % (self.runs, self.wkts + (1 if wicket else 0))}
                ev["animation"] = directive(ev, self.rng, reconstructed=False)
                self.events.append(ev)
                # free hit carries over if the free-hit delivery is itself a wide or no ball
                self.free_hit = et == "no_ball" or (self.free_hit and et == "wide")
                if wicket:
                    self.wkts += 1
                    if self.wkts >= 10:
                        break
                    self.striker = self.next_in
                    self.next_in += 1
                # Law 18: odd runs completed by running change ends (boundaries and wides of 1 are not run)
                ran = o["runs_bat"] if o["runs_bat"] not in (4, 6) else 0
                if et in ("bye", "leg_bye") and o["extras"] != 4:
                    ran = o["extras"]
                if ran % 2 == 1:
                    self.striker, self.non_striker = self.non_striker, self.striker
            self.bowler_overs[bi] = self.bowler_overs.get(bi, 0) + 1
            self.last_bowler = bi
            self.striker, self.non_striker = self.non_striker, self.striker  # ends change after the over
            over_no += 1
        return seq

def directive(ev, rng, reconstructed):
    if ev["is_wicket"]:
        t = {"bowled": "stumps_hit", "lbw": "pad_hit", "stumped": "stumping", "run out": "run_out"}.get(ev.get("wicket_kind"), "catch")
        return {"type": t, "result": "W", "direction_deg": rng.randint(0, 359), "distance": rng.randint(5, 60), "height": "air" if t == "catch" else "ground",
                "reconstructed": reconstructed}
    if ev["extra_type"] in ("wide", "no_ball"):
        return {"type": ev["extra_type"], "result": ev["runs_bat"] + ev["extras"], "direction_deg": None, "distance": 0, "height": "ground", "reconstructed": reconstructed}
    r = ev["runs_bat"]
    dist = {0: rng.randint(2, 15), 1: rng.randint(15, 35), 2: rng.randint(35, 55), 3: rng.randint(55, 65), 4: 70, 6: 85}.get(r, 20)
    return {"type": "shot" if r else "defence", "result": r, "direction_deg": rng.randint(0, 359), "distance": dist,
            "height": "air" if r == 6 else "ground", "reconstructed": reconstructed}

def simulate(fmt="T20", home=None, away=None, seed=None):
    if fmt not in FORMATS:
        raise LawsError("format must be one of " + ", ".join(FORMATS))
    seed = int(seed if seed is not None else random.SystemRandom().randrange(1, 2**31))
    rng = random.Random(seed)
    home = validate_team(home or default_team("SH Virtual Lions", seed))
    away = validate_team(away or default_team("SH Virtual Tigers", seed + 1))
    toss_winner = rng.choice([0, 1])
    bat_first = toss_winner if rng.random() < 0.5 else 1 - toss_winner
    teams = [home, away]
    i1 = Innings(teams[bat_first], teams[1 - bat_first], fmt, None, rng)
    seq = i1.play(0, 1)
    i2 = Innings(teams[1 - bat_first], teams[bat_first], fmt, i1.runs + 1, rng)
    i2.play(seq, 2)
    if i2.runs > i1.runs:
        winner, margin = teams[1 - bat_first]["name"], "%d wickets" % (10 - i2.wkts)
    elif i1.runs > i2.runs:
        winner, margin = teams[bat_first]["name"], "%d runs" % (i1.runs - i2.runs)
    else:
        winner, margin = None, "tie"
    result = {"virtual": True, "seed": seed, "format": fmt, "toss": {"winner": teams[toss_winner]["name"], "decision": "bat" if toss_winner == bat_first else "bowl"},
              "innings": [{"team": teams[bat_first]["name"], "runs": i1.runs, "wickets": i1.wkts, "overs": "%d.%d" % divmod(i1.legal, 6)},
                          {"team": teams[1 - bat_first]["name"], "runs": i2.runs, "wickets": i2.wkts, "overs": "%d.%d" % divmod(i2.legal, 6), "target": i1.runs + 1}],
              "winner": winner, "margin": margin,
              "top_scorers": sorted(list(i1.batter_runs.items()) + list(i2.batter_runs.items()), key=lambda x: -x[1])[:3]}
    events = i1.events + i2.events
    validate_events(events, fmt)
    return result, events, {"home": home["name"], "away": away["name"]}

def validate_events(events, fmt):
    """Independent Laws check of a finished event list (used in tests and on every simulation)."""
    q = FORMATS[fmt]["quota"]
    for ino in (1, 2):
        evs = [e for e in events if e["innings_no"] == ino]
        overs = {}
        for e in evs:
            overs.setdefault(e["over_no"], []).append(e)
        prev = None
        quota = {}
        for o in sorted(overs):
            balls = overs[o]
            bowlers = {e["bowler"] for e in balls}
            if len(bowlers) != 1:
                raise LawsError("over %d bowled by more than one bowler" % o)
            b = bowlers.pop()
            if b == prev:
                raise LawsError("Law 17.8 broken in over %d" % o)
            quota[b] = quota.get(b, 0) + 1
            if quota[b] > q:
                raise LawsError("bowler quota exceeded by %s" % b)
            legal = sum(1 for e in balls if e["extra_type"] not in ("wide", "no_ball"))
            last = o == max(overs)
            if legal > 6 or (legal < 6 and not last):
                raise LawsError("over %d has %d legal balls" % (o, legal))
            prev = b
        fh = False
        for e in evs:
            if fh and e["is_wicket"] and e["wicket_kind"] != "run out":
                raise LawsError("free hit dismissal other than run out")
            fh = e["extra_type"] == "no_ball" or (fh and e["extra_type"] == "wide")
    return True

def store(c, user_id, fmt, result, events, teams):
    c.execute("INSERT INTO game_matches(created_by,format,seed,config_json,result_json,created_at) VALUES(?,?,?,?,?,?)",
              (user_id, fmt, result["seed"], json.dumps(teams), json.dumps(result), now()))
    gid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.executemany("INSERT INTO game_events(game_id,seq,payload) VALUES(?,?,?)", [(gid, e["seq"], json.dumps(e)) for e in events])
    return gid

def replay_directives(ball_rows, seed=1):
    """Real match: we know outcomes but not trajectories, so geometry is a labelled reconstruction."""
    rng = random.Random(seed)
    out = []
    for b in ball_rows:
        ev = dict(b)
        ev["animation"] = directive(ev, rng, reconstructed=True)
        ev["animation"]["note"] = "Reconstruction: ball path and shot direction were not recorded."
        out.append(ev)
    return out
