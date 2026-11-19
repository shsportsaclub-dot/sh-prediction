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
