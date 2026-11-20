"""Match Center insights (owner's reference screens) and the tipster timing rules (owner, 19 Nov 2026)."""
import datetime, json, os, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import test_v1 as T
import insights


def iso_min(minutes):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


class FantasyPoints(unittest.TestCase):
    def _r(self):
        return {"id": -1, "home_name": "Brisbane Heat Women", "home_short": "BH-W", "away_name": "Sydney Thunder Women", "away_short": "SYT-W", "status": "live"}

    def test_reference_breakdown(self):
        # the owner's screenshot: 62 (34) with 8 fours, 3 sixes, SR 182.35, 50 bonus, 2 dot balls bowled = 132
        pd = {"source": "test", "squads": [], "scorecard": [
            {"inning": "Brisbane Heat Women Inning 1", "batting": [{"name": "Charli Knott", "r": 62, "b": 34, "fours": 8, "sixes": 3, "dismissal": "c Litchfield b Bates"}],
             "bowling": [{"name": "Samantha Bates", "o": "4", "m": 0, "r": 30, "w": 3}]},
            {"inning": "Sydney Thunder Women Inning 1", "batting": [{"name": "Phoebe Litchfield", "r": 28, "b": 17, "fours": 4, "sixes": 1, "dismissal": "b Ginger"}],
             "bowling": [{"name": "Charli Knott", "o": "1", "m": 0, "r": 8, "w": 0}, {"name": "Sianna Ginger", "o": "2", "m": 0, "r": 10, "w": 1}]}]}
        P = {p["name"]: p for p in self._run(pd)}
        k = {b["event"]: b["points"] for b in P["Charli Knott"]["breakdown"]}
        self.assertEqual((k["announced"], k["runs"], k["fours"], k["sixes"], k["sr"], k["milestone"]), (4, 62, 32, 18, 6, 8))
        self.assertEqual(P["Charli Knott"]["points"], 130)                      # 132 in the reference includes 2 dot balls we have no balls for
        b = {x["event"]: x for x in P["Samantha Bates"]["breakdown"]}
        self.assertEqual((b["wickets"]["points"], b["haul"]["points"]), (90, 4))
        self.assertEqual(b["economy"]["points"], 0)                            # 7.5 an over: no bonus, no penalty
        self.assertEqual({x["event"]: x["points"] for x in P["Phoebe Litchfield"]["breakdown"]}["catches"], 8)   # caught Knott off Bates
        self.assertEqual({x["event"]: x["points"] for x in P["Sianna Ginger"]["breakdown"]}["lbw_bowled"], 8)

    def _run(self, pd):
        class C:   # tiny stand-in: no provider ball rows, no SH fantasy teams
            def execute(self, sql, args=()):
                class R:
                    def fetchone(s): return None
                    def fetchall(s): return []
                    def __iter__(s): return iter([])
                return R()
        return insights.fantasy(C(), self._r(), pd)["players"]


class TipsterTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def _toss(self, mid, team, minutes_ago):
        c = T.db()
        c.execute("INSERT OR REPLACE INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)",
                  (mid, team, "bat", "test", iso_min(-minutes_ago)))
        c.commit(); c.close()

    def test_toss_closes_toss_picks_then_ten_minutes_for_winner(self):
        eid = T.expert("Timing Tipster")
        mid = T.mk_match("TmA", "TmB", days=0.05)
        h, a = T.team_ids(mid)
        self.assertEqual(T.predict(mid, "toss", h, eid)[0], 201)              # before the toss: open
        self._toss(mid, h, 3)
        s, r = T.predict(mid, "toss", h, eid)
        self.assertEqual((s, r["error"]["code"]), (409, "MATCH_STARTED"))     # toss picks shut at the toss
        s, w = T.predict(mid, "winner", a, eid)
        self.assertEqual(s, 201, w)                                            # winner pick inside the 10-minute window
        j = T.call("/api/v1/matches/%d/insights?part=tipsters" % mid, h=T.A)[1]
        self.assertEqual(j["window"]["pre_match"], "post_toss")
        self._toss(mid, h, 11)
        s, r = T.predict(mid, "winner", h, eid)
        self.assertEqual((s, r["error"]["code"]), (409, "MATCH_STARTED"))     # window over

    def test_five_minute_change_keeps_history(self):
        eid = T.expert("Change Tipster")
        mid = T.mk_match("ChA", "ChB", days=1)
        h, a = T.team_ids(mid)
        p = T.predict(mid, "winner", h, eid)[1]["prediction_id"]
        s, r = T.call("/api/v1/predictions/%d/change" % p, {"predicted_team_id": a}, T.A)
        self.assertEqual(s, 200, r)
        c = T.db()
        old = c.execute("SELECT status, predicted_team_id, created_at FROM predictions WHERE id=?", (p,)).fetchone()
        new = c.execute("SELECT status, predicted_team_id, created_at FROM predictions WHERE id=?", (r["prediction_id"],)).fetchone()
        self.assertEqual((old["status"], old["predicted_team_id"]), ("canceled", h))          # the first pick stays on record
        self.assertEqual((new["status"], new["predicted_team_id"], new["created_at"]), ("locked", a, old["created_at"]))
        # a pick first submitted more than 5 minutes ago is locked for good
        c.execute("""INSERT INTO predictions(prediction_uid,match_id,source_type,expert_id,prediction_type,predicted_team_id,created_at,locked_at,status,data_origin)
                     VALUES('old-pick-test',?,'expert',?,'winner',?,?,?,'locked','verified')""", (mid, eid, h, iso_min(-6), iso_min(-6)))
        oid = c.execute("SELECT id FROM predictions WHERE prediction_uid='old-pick-test'").fetchone()[0]
        c.commit(); c.close()
        s, r = T.call("/api/v1/predictions/%d/change" % oid, {"predicted_team_id": a}, T.A)
        self.assertEqual((s, r["error"]["code"]), (409, "LOCKED"))

    def test_one_innings_break_update_only(self):
        eid = T.expert("Update Tipster")
        mid = T.mk_match("UpA", "UpB", days=-0.01, format="T10")
        h, a = T.team_ids(mid)
        ev = lambda seq, inn, team, **k: T.call("/api/v1/admin/ball-events", dict({"match_id": mid, "innings_no": inn, "batting_team_id": team, "seq": seq, "runs_bat": 1}, **k), T.A)
        ev(1, 1, h)
        s, r = T.call("/api/v1/predictions", {"match_id": mid, "prediction_type": "live_winner", "predicted_team_id": h, "expert_id": eid}, T.A)
        self.assertEqual((s, r["error"]["code"]), (409, "UPDATE_CLOSED"))     # first innings still going
        c = T.db(); c.execute("UPDATE innings SET completed=1 WHERE match_id=? AND innings_no=1", (mid,)); c.commit(); c.close()
        s, r = T.call("/api/v1/predictions", {"match_id": mid, "prediction_type": "live_winner", "predicted_team_id": a, "expert_id": eid}, T.A)
        self.assertEqual(s, 201, r)                                            # innings break: allowed once
        s, r = T.call("/api/v1/predictions", {"match_id": mid, "prediction_type": "live_winner", "predicted_team_id": h, "expert_id": eid}, T.A)
        self.assertEqual((s, r["error"]["code"]), (409, "UPDATE_USED"))
        # the SH model's own live line is not a tipster and is not limited
        self.assertEqual(T.call("/api/v1/matches/%d/signals" % mid, h=T.A)[0], 200)

    def test_timing_weight(self):
        import api_v1
        mid = T.mk_match("TwA", "TwB", days=1)
        h, _ = T.team_ids(mid)
        self._toss(mid, h, 20)
        c = T.db()
        toss_at = c.execute("SELECT verified_at FROM toss_results WHERE match_id=?", (mid,)).fetchone()[0]
        t0 = datetime.datetime.fromisoformat(toss_at)
        w = lambda m: api_v1.timing_weight(c, mid, (t0 + datetime.timedelta(minutes=m)).isoformat())
        self.assertEqual((w(-5), w(0), w(1), w(5), w(30)), (1.0, 1.0, 0.57, 0.45, 0.3))
        c.close()


class InsightParts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_parts_and_poll(self):
        mid = T.mk_match("InA", "InB", days=1)
        h, a = T.team_ids(mid)
        for part in ("info", "fantasy", "graphs", "live", "points", "tipsters"):
            s, j = T.call("/api/v1/matches/%d/insights?part=%s" % (mid, part))
            self.assertEqual(s, 200, (part, j))
        info = T.call("/api/v1/matches/%d/insights?part=info" % mid)[1]
        self.assertEqual(set(info), {"form", "comparison", "h2h", "venue", "note"})
        self.assertEqual(T.call("/api/v1/matches/%d/insights?part=nope" % mid)[0], 400)
        self.assertEqual(T.call("/api/v1/matches/%d/fan-poll" % mid, {"team_id": h})[0], 401)   # login needed to vote
        H = T.account("poll_voter_1")
        s, p = T.call("/api/v1/matches/%d/fan-poll" % mid, {"team_id": h}, H)
        self.assertEqual((s, p["votes"], p["my_vote"]), (200, 1, h))
        s, p = T.call("/api/v1/matches/%d/fan-poll" % mid, {"team_id": a}, H)                    # change of mind: still one vote
        self.assertEqual((p["votes"], p["my_vote"], p["options"][1]["pct"]), (1, a, 100))
        self.assertEqual(T.call("/api/v1/matches/%d/fan-poll" % mid, {"team_id": 999999}, H)[0], 400)
        d = T.call("/api/v1/matches/%d/discussions?sort=latest" % mid, h=H)[1]
        self.assertEqual((d["sort"], d["poll"]["my_vote"]), ("latest", a))
        self.assertEqual(T.call("/api/v1/matches/%d/discussions?sort=mine" % mid)[0], 401)

    def test_weather_cached_and_fails_safe(self):
        calls = []
        def fake(url):
            calls.append(url)
            if "geocoding" in url:
                return {"results": [{"name": "Brisbane", "country": "Australia", "latitude": -27.4, "longitude": 153.0}]}
            return {"current": {"temperature_2m": 22.2, "relative_humidity_2m": 68, "weather_code": 3, "precipitation_probability": 16, "time": "2026-11-19T15:51"}}
        insights._WX.clear()
        w = insights.weather(None, "Allan Border Field, Brisbane", None, fetch=fake)
        self.assertEqual((w["temperature_c"], w["humidity_pct"], w["rain_chance_pct"], w["condition"]), (22.2, 68, 16, "Cloudy"))
        insights.weather(None, "Allan Border Field, Brisbane", None, fetch=fake)
        self.assertEqual(len(calls), 2)                                        # second call served from the 30-minute cache
        def boom(url): raise OSError("offline")
        insights._WX.clear()
        self.assertIsNone(insights.weather(None, "Nowhere Park, Atlantis", None, fetch=boom))


if __name__ == "__main__":
    unittest.main()


class TipsterDesk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_desk_picks_change_and_private_sheet(self):
        H = T.account("desk_tipster_1")
        c = T.db(); uid = c.execute("SELECT user_id FROM accounts WHERE username='desk_tipster_1'").fetchone()[0]; c.close()
        self.assertEqual(T.call("/api/v1/me/tipster/series", h=H)[0], 403)                 # not a tipster yet
        T.call("/api/v1/me/tipster-application", {}, H)
        T.call("/api/v1/admin/social/moderate", {"action": "approve_tipster", "target_type": "user", "target_id": uid, "reason": "test"}, T.A)
        mid = T.mk_match("DkA", "DkB", days=1, comp="Desk Cup 2026")
        T.mk_match("DkC", "DkD", days=2, comp="Desk Cup 2026")
        h, a = T.team_ids(mid)
        ser = T.call("/api/v1/me/tipster/series", h=H)[1]["items"]
        cid = next(s["id"] for s in ser if s["name"] == "Desk Cup 2026")
        s, p = T.call("/api/v1/social/posts", {"kind": "toss_prediction", "prediction_type": "toss", "predicted_team_id": h, "match_id": mid, "body": ""}, H)
        self.assertEqual(s, 201, p)
        T.call("/api/v1/social/posts", {"kind": "prediction", "prediction_type": "winner", "predicted_team_id": a, "match_id": mid, "body": ""}, H)
        b = T.call("/api/v1/me/tipster/board?competition_id=%d" % cid, h=H)[1]
        m = next(x for x in b["matches"] if x["id"] == mid)
        self.assertEqual((m["picks"]["toss"]["team_id"], m["picks"]["winner"]["team_id"], len(b["matches"])), (h, a, 2))
        self.assertTrue(0 < m["picks"]["toss"]["changeable_seconds"] <= 300)
        s, r = T.call("/api/v1/predictions/%d/change" % m["picks"]["toss"]["prediction_id"], {"predicted_team_id": a}, H)
        self.assertEqual(s, 200, r)
        b = T.call("/api/v1/me/tipster/board?competition_id=%d" % cid, h=H)[1]
        self.assertEqual(next(x for x in b["matches"] if x["id"] == mid)["picks"]["toss"]["team_id"], a)
        L = T.call("/api/v1/me/tipster/link", h=H)[1]
        import urllib.request
        csv_text = urllib.request.urlopen(T.B + L["csv"] + "?competition_id=%d" % cid).read().decode()
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0], "Desk Cup 2026")
        self.assertTrue(lines[1].startswith("Match,Date,Time (UTC),Home,Away,Venue,Toss,Decision,My toss pick"))
        self.assertIn("A-DkB", lines[2])
        x = urllib.request.urlopen(T.B + L["xlsx"]).read()
        self.assertEqual(x[:2], b"PK")                                                     # a real .xlsx
        L2 = T.call("/api/v1/me/tipster/link", {"reset": True}, H)[1]
        self.assertNotEqual(L2["csv"], L["csv"])
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(T.B + L["csv"])                                         # old link stops working


class SeriesAnalysis(unittest.TestCase):
    """Player stats in series: categories and independent filters (last 5 / venue / vs team) from provider scorecards."""
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def _played(self, home, away, days, venue, card):
        mid = T.mk_match(home, away, days=days, comp="Analysis Cup 2026", venue=venue)
        c = T.db()
        c.execute("UPDATE matches SET status='completed' WHERE id=?", (mid,))
        c.execute("INSERT INTO ext_match_detail(match_id,source,scorecard_json,scorecard_at) VALUES(?,?,?,?)", (mid, "cricketdata", json.dumps(card), iso_min(0)))
        c.commit(); c.close()
        return mid

    def test_categories_and_filters(self):
        inn = lambda team, bat, bowl: {"inning": team + " Inning 1", "batting": [{"name": n, "r": r, "b": b, "fours": 0, "sixes": s, "dismissal": d} for n, r, b, s, d in bat],
                                       "bowling": [{"name": n, "o": o, "m": 0, "r": r, "w": w} for n, o, r, w in bowl]}
        # three Lions v Tigers games and one Lions v Bears game
        self._played("An Lions", "An Tigers", -9, "North Park", [inn("An Lions", [("Leo Bat", 40, 20, 3, "c X b Tim Ball"), ("Lou Hit", 10, 12, 0, "not out")], [("Tim Ball", "4", 30, 1)]),
                                                                 inn("An Tigers", [("Tom Bat", 25, 25, 1, "b Lee Spin")], [("Lee Spin", "4", 21, 3)])])
        self._played("An Lions", "An Tigers", -7, "South Park", [inn("An Lions", [("Leo Bat", 5, 6, 0, "b Tim Ball")], [("Tim Ball", "2", 6, 2)]),
                                                                 inn("An Tigers", [("Tom Bat", 70, 40, 5, "not out")], [("Lee Spin", "4", 40, 0)])])
        self._played("An Lions", "An Bears", -5, "North Park", [inn("An Lions", [("Leo Bat", 60, 30, 4, "c Y b Z")], [("Bo Bowl", "4", 23, 2)]),
                                                                inn("An Bears", [("Ben Bat", 12, 10, 0, "lbw b Lee Spin")], [("Lee Spin", "4", 18, 2)])])
        cur = T.mk_match("An Lions", "An Tigers", days=1, comp="Analysis Cup 2026", venue="North Park")
        q = lambda **k: T.call("/api/v1/matches/%d/insights?part=series_stats&%s" % (cur, "&".join("%s=%s" % x for x in k.items())))[1]
        runs = q(cat="runs")
        self.assertEqual([(x["name"], x["value"], x["inns"]) for x in runs["items"][:3]], [("Leo Bat", 105, 3), ("Tom Bat", 95, 2), ("Ben Bat", 12, 1)])
        self.assertEqual(runs["matches_used"], 3)
        self.assertEqual([x["name"] for x in q(cat="runs", vs="away")["items"]], ["Leo Bat", "Lou Hit"])              # players who faced the Tigers
        self.assertEqual([(x["name"], x["value"]) for x in q(cat="runs", venue="1")["items"][:2]], [("Leo Bat", 100), ("Tom Bat", 25)])
        # venue and opponent combine: North Park AND vs Tigers -> only the first game
        self.assertEqual([(x["name"], x["value"]) for x in q(cat="runs", venue="1", vs="away")["items"]], [("Leo Bat", 40), ("Lou Hit", 10)])
        self.assertEqual(q(cat="runs", last="1")["items"][0]["value"], 70)                                          # each player's own last match
        fig = q(cat="figures")["items"]
        self.assertEqual([(x["name"], x["display"]) for x in fig[:3]], [("Lee Spin", "21-3"), ("Tim Ball", "6-2"), ("Bo Bowl", "23-2")])  # wkts desc, runs asc
        econ = q(cat="econ")["items"]
        self.assertEqual([(x["name"], x["display"]) for x in econ[:3]], [("Bo Bowl", "5.75"), ("Tim Ball", "6.00"), ("Lee Spin", "6.58")])  # ascending
        self.assertEqual([x["display"] for x in q(cat="highest")["items"][:2]], ["70*", "60"])
        self.assertEqual(q(cat="sr")["items"][0]["name"], "Leo Bat")                                                # 105 off 56
        self.assertEqual(q(cat="runs", vs="home", venue="1", last="5")["items"][0]["name"], "Tom Bat")
        empty = q(cat="sixes", vs="home", venue="1")
        self.assertTrue(empty["items"][0]["name"] == "Tom Bat")
        self.assertEqual(T.call("/api/v1/matches/%d/insights?part=series_stats&cat=nope" % cur)[0], 400)
        rec = q(cat="fantasy", view="recent")
        self.assertTrue(rec["recent"] and all("opp" in x for x in rec["recent"]))
        none = q(cat="wickets", vs="away", venue="1", last="1")      # Lions bowlers vs Tigers at North Park: Lee Spin's last such match
        self.assertEqual([x["name"] for x in none["items"]], ["Lee Spin"])
        lone = T.mk_match("An Lions", "An Tigers", days=1, comp="Empty Cup 2026")
        e = T.call("/api/v1/matches/%d/insights?part=series_stats&cat=runs&last=5&venue=1" % lone)[1]
        self.assertEqual((e["items"], e["empty"]), ([], "No matching statistics"))   # never borrows other series' records


class PredictionXI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_build_lock_and_dream_team(self):
        roles = ["WK-Batsman"] + ["Batsman"] * 4 + ["Batting Allrounder"] * 2 + ["Bowler"] * 4
        squad = lambda team: {"team": team, "players": [{"name": "%s P%d" % (team.split()[-1], i), "role": roles[i]} for i in range(11)]}
        # one earlier match where X Opener P1 scored big: form should make him captain
        past = T.mk_match("Xi Hawks", "Xi Owls", days=-4, comp="XI Cup 2026")
        c = T.db()
        c.execute("UPDATE matches SET status='completed' WHERE id=?", (past,))
        card = [{"inning": "Xi Hawks Inning 1", "batting": [{"name": "Hawks P1", "r": 90, "b": 45, "fours": 9, "sixes": 4, "dismissal": "not out"}], "bowling": [{"name": "Owls P9", "o": "4", "m": 0, "r": 20, "w": 3}]},
                {"inning": "Xi Owls Inning 1", "batting": [{"name": "Owls P2", "r": 30, "b": 25, "fours": 3, "sixes": 0, "dismissal": "b Hawks P8"}], "bowling": [{"name": "Hawks P8", "o": "4", "m": 1, "r": 18, "w": 2}]}]
        c.execute("INSERT INTO ext_match_detail(match_id,source,scorecard_json,scorecard_at) VALUES(?,?,?,?)", (past, "cricketdata", json.dumps(card), iso_min(-5000)))
        c.commit(); c.close()
        mid = T.mk_match("Xi Hawks", "Xi Owls", days=1, comp="XI Cup 2026")
        c = T.db()
        c.execute("INSERT INTO ext_match_detail(match_id,source,squad_json,squad_at) VALUES(?,?,?,?)", (mid, "cricketdata", json.dumps([squad("Xi Hawks"), squad("Xi Owls")]), iso_min(0)))
        c.commit(); c.close()
        g = lambda: T.call("/api/v1/matches/%d/insights?part=prediction_xi" % mid)[1]
        d = g()
        self.assertTrue(d["available"], d)
        P = d["players"]
        self.assertEqual(len(P), 11)
        cap = next(p for p in P if p["captain"])
        self.assertEqual(cap["name"], "Hawks P1")                                     # best recent form
        self.assertEqual(sum(p["vice_captain"] for p in P), 1)
        h, a = T.team_ids(mid)
        self.assertTrue(all(sum(p["team_id"] == t for p in P) <= d["rules"]["max_per_team"] for t in (h, a)))
        self.assertGreaterEqual(sum(p["role"] == "wicket_keeper" for p in P), 1)
        self.assertEqual((d["locked"], d["pool_status"]), (False, "playing_xi"))
        # toss: the XI is frozen, even if the source changes the squad afterwards
        c = T.db()
        c.execute("INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)", (mid, h, "bat", "test", iso_min(0)))
        c.commit(); c.close()
        before = [p["name"] for p in g()["players"]]
        c = T.db()
        c.execute("UPDATE ext_match_detail SET squad_json=? WHERE match_id=?", (json.dumps([squad("Xi Owls"), {"team": "Xi Hawks", "players": [{"name": "New Guy %d" % i, "role": roles[i]} for i in range(11)]}]), mid))
        c.commit(); c.close()
        after = g()
        self.assertEqual(([p["name"] for p in after["players"]], after["locked"]), (before, True))
        # play starts: actual points and the dream team appear
        c = T.db()
        c.execute("UPDATE matches SET status='completed' WHERE id=?", (mid,))
        c.execute("UPDATE ext_match_detail SET squad_json=?, scorecard_json=? WHERE match_id=?", (json.dumps([squad("Xi Hawks"), squad("Xi Owls")]), json.dumps(card), mid))
        c.commit(); c.close()
        done = g()
        self.assertIn("dream_team", done)
        self.assertEqual(len(done["dream_team"]["players"]), 11)
        self.assertGreaterEqual(done["dream_team"]["points"], done["actual_points"])        # nobody beats the best possible XI
        self.assertEqual(next(p for p in done["dream_team"]["players"] if p["captain"])["name"], "Hawks P1")
