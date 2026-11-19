"""Master Script V1.0 section 11 mandatory quality tests for /api/v1."""
import os, sys, json, time, sqlite3, tempfile, threading, unittest, urllib.request, urllib.error, datetime

D = tempfile.mkdtemp()
os.environ["SH_PREDICTION_DB"] = D + "/v1.sqlite3"
os.environ["SH_PREDICTION_ADMIN_TOKEN"] = "adm-test-token"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import importlib
import screen_login, main, api_v1, engine
# test_api.py may have imported these first with another DB path: rebind to ours
for mod in (screen_login, main):
    mod.DB = os.environ["SH_PREDICTION_DB"]
from http.server import ThreadingHTTPServer

main.H.log_message = lambda *a: None  # keep test output readable
srv = ThreadingHTTPServer(("127.0.0.1", 0), main.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % srv.server_port
A = {"X-Admin-Token": "adm-test-token"}
SOON, SOON_WAIT = 2.5 / 86400, 3.0  # a match starting 2.5 s from now

def call(path, data=None, h=None, method=None):
    r = urllib.request.Request(B + path, data=json.dumps(data).encode() if data is not None else None,
                               headers=dict({"Content-Type": "application/json"}, **(h or {})), method=method)
    try:
        x = urllib.request.urlopen(r)
        return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def login(phone):
    s, o = call("/auth/generate", {"phone": phone})
    s, t = call("/auth/verify", {"phone": phone, "otp": o["otp"]})
    return {"Authorization": "Bearer " + t["token"]}

def iso(days):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).replace(microsecond=0).isoformat()

def mk_match(home, away, days=3, comp="V1 Test Cup", **kw):
    d = dict(competition=comp, home=home, away=away, start_utc=iso(days), source="https://example.org/fixture", venue="Test Oval", format="T20")
    d.update(kw)
    s, r = call("/api/v1/admin/matches", d, A)
    assert s == 200, r
    return r["match_id"]

def team_ids(mid):
    s, m = call("/api/v1/matches/%d" % mid, h=A)
    return m["home"]["id"], m["away"]["id"]

def db():
    c = sqlite3.connect(os.environ["SH_PREDICTION_DB"], timeout=10)
    c.row_factory = sqlite3.Row
    return c

def expert(name="Tipster One", phone=None):
    s, r = call("/api/v1/admin/experts", {"display_name": name, "country": "India", "language_code": "te", "phone": phone}, A)
    assert s == 200, r
    call("/api/v1/admin/experts/%d/verify" % r["expert_id"], {"verified": True}, A)
    return r["expert_id"]

def predict(mid, kind, team, eid, conf=60):
    return call("/api/v1/predictions", {"match_id": mid, "prediction_type": kind, "predicted_team_id": team, "confidence": conf,
                                         "explanation": "test", "expert_id": eid}, A)

class Security(unittest.TestCase):
    def test_auth_required_and_structured_errors(self):
        s, r = call("/api/v1/matches")
        self.assertEqual(s, 401)
        self.assertEqual(r["error"]["code"], "UNAUTHENTICATED")

    def test_user_cannot_use_admin_or_post_predictions(self):
        u = login("9100000001")
        self.assertEqual(call("/api/v1/admin/audit", h=u)[0], 403)
        mid = mk_match("SecA", "SecB")
        h, _ = team_ids(mid)
        self.assertEqual(call("/api/v1/predictions", {"match_id": mid, "prediction_type": "winner", "predicted_team_id": h}, u)[0], 403)

    def test_unverified_expert_blocked_verified_allowed(self):
        phone = "9100000002"
        s, r = call("/api/v1/admin/experts", {"display_name": "Unverified Tipster", "phone": phone}, A)
        u = login(phone)
        mid = mk_match("ExA", "ExB")
        h, _ = team_ids(mid)
        body = {"match_id": mid, "prediction_type": "winner", "predicted_team_id": h, "confidence": 70, "explanation": "form"}
        self.assertEqual(call("/api/v1/predictions", body, u)[0], 403)
        call("/api/v1/admin/experts/%d/verify" % r["expert_id"], {}, A)
        s, p = call("/api/v1/predictions", body, u)
        self.assertEqual(s, 201, p)

    def test_audit_logged(self):
        mid = mk_match("AudA", "AudB")
        s, log = call("/api/v1/admin/audit?limit=100", h=A)
        self.assertTrue(any(x["action"] == "match.create" and x["entity_id"] == str(mid) and x["actor"] == "admin-token" for x in log["items"]))

    def test_validation_and_pagination(self):
        self.assertEqual(call("/api/v1/matches?limit=500", h=A)[0], 400)
        self.assertEqual(call("/api/v1/admin/matches", {"competition": "x", "home": "A", "away": "A", "start_utc": iso(1), "source": "s"}, A)[0], 400)
        self.assertEqual(call("/api/v1/admin/matches", {"competition": "x", "home": "A", "away": "B", "start_utc": "2030-01-01T10:00:00", "source": "s"}, A)[0], 400)
        s, r = call("/api/v1/matches?limit=1&offset=0", h=A)
        self.assertEqual((s, r["limit"], len(r["items"]) <= 1), (200, 1, True))

    def test_rate_limit(self):
        old = dict(api_v1.RATE)
        api_v1.RATE.update(capacity=3, per_seconds=3600)
        api_v1._buckets.clear()
        try:
            codes = [call("/api/v1/languages")[0] for _ in range(5)]
            self.assertIn(429, codes)
        finally:
            api_v1.RATE.update(old)
            api_v1._buckets.clear()

class Integrity(unittest.TestCase):
    def test_duplicate_match_prevention(self):
        st = iso(9)
        a = call("/api/v1/admin/matches", dict(competition="Dup Cup", home="D1", away="D2", start_utc=st, source="s", provider="cricketdata", provider_id="abc-1"), A)[1]
        b = call("/api/v1/admin/matches", dict(competition="Dup Cup", home="D1", away="D2", start_utc=st, source="s"), A)[1]
        c = call("/api/v1/admin/matches", dict(competition="Dup Cup", home="D1", away="D2", start_utc=iso(10), source="s", provider="cricketdata", provider_id="abc-1"), A)[1]
        self.assertEqual(b, {"match_id": a["match_id"], "status": "duplicate"})
        self.assertEqual(c, {"match_id": a["match_id"], "status": "duplicate_provider_id"})
        self.assertEqual(db().execute("SELECT COUNT(*) FROM matches m JOIN competitions c ON c.id=m.competition_id WHERE c.name='Dup Cup'").fetchone()[0], 1)

    def test_prediction_locking_and_immutability(self):
        eid = expert("Lock Tester")
        mid = mk_match("LkA", "LkB")
        h, a = team_ids(mid)
        s, p = predict(mid, "winner", h, eid)
        self.assertEqual((s, p["status"]), (201, "locked"))
        c = db()
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("UPDATE predictions SET predicted_team_id=? WHERE id=?", (a, p["prediction_id"]))
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("DELETE FROM predictions WHERE id=?", (p["prediction_id"],))
        c.close()
        # recording the actual result never changes the original prediction row
        before = dict(db().execute("SELECT * FROM predictions WHERE id=?", (p["prediction_id"],)).fetchone())
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": a, "source": "s"}, A)
        after = dict(db().execute("SELECT * FROM predictions WHERE id=?", (p["prediction_id"],)).fetchone())
        self.assertEqual(before, after)

    def test_pre_match_closed_after_start(self):
        eid = expert("Late Tester")
        mid = mk_match("LtA", "LtB", days=-1)
        h, _ = team_ids(mid)
        s, r = predict(mid, "toss", h, eid)
        self.assertEqual((s, r["error"]["code"]), (409, "MATCH_STARTED"))

    def test_draft_lock_flow(self):
        eid = expert("Draft Tester")
        mid = mk_match("DrA", "DrB")
        h, _ = team_ids(mid)
        s, p = call("/api/v1/predictions", {"match_id": mid, "prediction_type": "toss", "predicted_team_id": h, "expert_id": eid, "lock": False}, A)
        self.assertEqual(p["status"], "draft")
        self.assertEqual(call("/api/v1/predictions/%d/lock" % p["prediction_id"], {}, A)[1]["status"], "locked")
        self.assertEqual(call("/api/v1/predictions/%d/lock" % p["prediction_id"], {}, A)[0], 409)

    def test_live_versions_append_only(self):
        mid = mk_match("LvA", "LvB", days=-0.01, format="T10")
        h, a = team_ids(mid)
        for i in range(1, 4):
            s, r = call("/api/v1/admin/ball-events", {"match_id": mid, "innings_no": 1, "batting_team_id": h, "seq": i, "runs_bat": 4}, A)
            self.assertEqual(s, 200, r)
        s, sig = call("/api/v1/matches/%d/signals" % mid, h=A)
        self.assertEqual([v["version_no"] for v in sig["live_history"]], [1, 2, 3])
        c = db()
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("UPDATE prediction_versions SET confidence=1")
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("DELETE FROM prediction_versions")
        c.close()

class Evaluation(unittest.TestCase):
    def test_correct_wrong_void_pending_and_formula(self):
        eid = expert("Eval Tipster")
        comp = "Eval League"
        m1, m2, m3, m4, m5 = (mk_match("E%dA" % i, "E%dB" % i, comp=comp, days=SOON) for i in range(1, 6))
        t = {m: team_ids(m) for m in (m1, m2, m3, m4, m5)}
        for m in (m1, m2, m3, m4, m5):
            predict(m, "winner", t[m][0], eid)
            predict(m, "toss", t[m][0], eid)
        time.sleep(SOON_WAIT)  # predictions were locked before the start; now the matches are under way
        R = lambda m, **k: call("/api/v1/admin/results", dict(match_id=m, source="https://example.org/r", **k), A)
        T = lambda m, w: call("/api/v1/admin/toss", dict(match_id=m, winner_team_id=w, decision="bat", source="https://example.org/t"), A)
        R(m1, result_type="win", winner_team_id=t[m1][0]); T(m1, t[m1][0])            # correct / correct
        R(m2, result_type="win", winner_team_id=t[m2][1]); T(m2, t[m2][1])            # incorrect / incorrect
        R(m3, result_type="tie_super_over", winner_team_id=t[m3][0]); T(m3, t[m3][1])  # super over winner counts; toss incorrect
        R(m4, result_type="no_result"); T(m4, t[m4][0])                               # winner void; toss still settles (correct)
        # m5 pending
        s, acc = call("/api/v1/analytics/accuracy", h=A)
        w = acc["by_league"][comp]
        lg = {k: w[k] for k in ("correct", "incorrect", "pending", "void", "settled")}
        self.assertEqual(lg, {"correct": 4, "incorrect": 3, "pending": 2, "void": 1, "settled": 7})
        self.assertEqual(w["accuracy"], 57.1)  # 4 / (4+3) * 100
        winner = [x for x in call("/api/v1/matches/%d/predictions" % m3, h=A)[1]["items"] if x["prediction_type"] == "winner"][0]
        self.assertEqual((winner["evaluation"], "Super Over" in winner["rule"]), ("correct", True))

    def test_tie_without_super_over_is_void_and_revision_supersedes(self):
        eid = expert("Tie Tipster")
        mid = mk_match("TiA", "TiB")
        h, a = team_ids(mid)
        p = predict(mid, "winner", h, eid)[1]["prediction_id"]
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "tie", "source": "s"}, A)
        self.assertEqual(call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": a, "source": "s"}, A)[0], 409)
        self.assertEqual(call("/api/v1/admin/results", {"match_id": mid, "result_type": "tie", "winner_team_id": a, "source": "s", "reason": "x"}, A)[0], 400)
        ev = lambda: [r["result"] for r in db().execute("SELECT result FROM prediction_evaluations WHERE prediction_id=? ORDER BY id", (p,))]
        self.assertEqual(ev()[-1], "void")
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": h, "source": "s", "reason": "scorer correction"}, A)
        self.assertEqual(ev()[-2:], ["void", "correct"])  # history kept
        self.assertEqual(db().execute("SELECT COUNT(*) FROM prediction_evaluations WHERE prediction_id=? AND superseded_at IS NULL", (p,)).fetchone()[0], 1)

    def test_missing_result_handling(self):
        mid = mk_match("MrA", "MrB")
        s, ml = call("/api/v1/master-list?competition_id=%d" % db().execute("SELECT competition_id FROM matches WHERE id=?", (mid,)).fetchone()[0], h=A)
        row = [r for r in ml["items"] if r["match_id"] == mid][0]
        self.assertEqual((row["toss_actual"], row["winner_actual"], row["winner_prediction"]), (None, None, None))

class MasterList(unittest.TestCase):
    def test_toss_winner_mapping_and_codes(self):
        call("/api/v1/admin/teams", {"name": "Ultra Blasters", "short_code": "UB"}, A)
        call("/api/v1/admin/teams", {"name": "Eagle Eyes", "short_code": "EE"}, A)
        self.assertEqual(call("/api/v1/admin/teams", {"name": "Other XI", "short_code": "UB"}, A)[0], 409)
        eid = expert("Map Tipster")
        mid = mk_match("Ultra Blasters", "Eagle Eyes", comp="Map Cup", days=SOON)
        h, a = team_ids(mid)
        predict(mid, "toss", h, eid)
        predict(mid, "winner", a, eid)
        time.sleep(SOON_WAIT)
        call("/api/v1/admin/toss", {"match_id": mid, "winner_team_id": h, "decision": "bowl", "source": "s"}, A)
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": h, "source": "s"}, A)
        cid = db().execute("SELECT competition_id FROM matches WHERE id=?", (mid,)).fetchone()[0]
        s, ml = call("/api/v1/master-list?competition_id=%d" % cid, h=A)
        self.assertEqual(ml["columns"], ["Match", "Home", "Away", "Toss", "Winner"])
        r = ml["items"][0]
        self.assertEqual((r["home"]["side"], r["home"]["code"], r["away"]["side"], r["away"]["code"]), ("H", "UB", "A", "EE"))
        self.assertEqual((r["toss_prediction"]["side"], r["toss_prediction"]["code"], r["toss_prediction"]["outcome"]), ("H", "UB", "won"))
        self.assertEqual((r["winner_prediction"]["side"], r["winner_prediction"]["code"], r["winner_prediction"]["outcome"]), ("A", "EE", "lost"))
        self.assertEqual((r["winner_actual"]["side"], r["winner_actual"]["code"]), ("H", "UB"))

    def test_unapproved_code_not_shown(self):
        mid = mk_match("No Code Club", "Other Club", comp="Code Cup")
        s, m = call("/api/v1/matches/%d" % mid, h=A)
        self.assertIsNone(m["home"]["short_code"])

class LiveAndModel(unittest.TestCase):
    def test_score_update_sync(self):
        mid = mk_match("SyA", "SyB", days=-0.01, format="T10")
        h, a = team_ids(mid)
        balls = [dict(runs_bat=1), dict(runs_bat=0, extras=1, extra_type="wide"), dict(runs_bat=6), dict(is_wicket=1, wicket_kind="bowled"),
                 dict(runs_bat=0, extras=1, extra_type="no_ball"), dict(runs_bat=2)]
        for i, b in enumerate(balls, 1):
            s, r = call("/api/v1/admin/ball-events", dict(match_id=mid, innings_no=1, batting_team_id=h, seq=i, **b), A)
            self.assertEqual(s, 200, r)
        self.assertEqual(call("/api/v1/admin/ball-events", dict(match_id=mid, innings_no=1, seq=3, runs_bat=1), A)[0], 409)
        s, sc = call("/api/v1/matches/%d/scorecard" % mid, h=A)
        i1 = sc["innings"][0]
        self.assertEqual((i1["runs"], i1["wickets"], i1["overs"]), (11, 1, "0.4"))
        s, cm = call("/api/v1/matches/%d/commentary?limit=2" % mid, h=A)
        self.assertEqual((cm["total"], len(cm["items"]), cm["items"][0]["seq"]), (6, 2, 6))
        s, m = call("/api/v1/matches/%d" % mid, h=A)
        self.assertEqual(m["status"], "live")

    def test_live_probability_sane(self):
        self.assertEqual(engine.live_probability("T20", 2, 150, 3, 100, target=150)["batting_team_win_probability"], 100.0)
        easy = engine.live_probability("T20", 2, 100, 2, 90, target=130)["batting_team_win_probability"]
        hard = engine.live_probability("T20", 2, 100, 8, 110, target=160)["batting_team_win_probability"]
        self.assertGreater(easy, 70)
        self.assertLess(hard, 10)

    def test_model_prediction_explainable(self):
        mid = mk_match("MoA", "MoB", days=5)
        s, r = call("/api/v1/admin/matches/%d/model-prediction" % mid, {}, A)
        self.assertEqual(s, 201, r)
        self.assertAlmostEqual(r["model"]["home_win_probability"] + r["model"]["away_win_probability"], 100.0, places=1)
        self.assertEqual({f["factor"] for f in r["model"]["factors"]}, {"recent_form", "head_to_head", "home_advantage", "venue_toss_bias"})
        self.assertEqual(call("/api/v1/admin/matches/%d/model-prediction" % mid, {}, A)[0], 409)

class LanguageAndDemo(unittest.TestCase):
    def test_language_persistence(self):
        u = login("9100000009")
        self.assertEqual(call("/api/v1/me/preferences", {"language_code": "te", "theme": "light"}, u, "PUT")[0], 200)
        u2 = login("9100000009")  # a second device / new session
        s, p = call("/api/v1/me/preferences", h=u2)
        self.assertEqual((p["language_code"], p["theme"]), ("te", "light"))
        self.assertEqual(call("/api/v1/me/preferences", {"language_code": "xx"}, u, "PUT")[0], 400)
        s, b = call("/api/v1/i18n/te")
        self.assertEqual(b["strings"]["col.toss"], "టాస్")
        s, b = call("/api/v1/i18n/ta")  # incomplete language falls back to English
        self.assertEqual(b["strings"]["col.toss"], "Toss")

    def test_demo_excluded_from_headline(self):
        before = call("/api/v1/analytics/accuracy", h=A)[1]["overall"]["settled"]
        s, r = call("/api/v1/admin/demo-seed", {}, A)
        self.assertEqual(s, 200, r)
        after = call("/api/v1/analytics/accuracy", h=A)[1]["overall"]["settled"]
        with_demo = call("/api/v1/analytics/accuracy?include_demo=1", h=A)[1]
        self.assertEqual(before, after)
        self.assertTrue(with_demo["includes_demo"])
        self.assertGreater(with_demo["overall"]["settled"], after)
        ml = call("/api/v1/master-list?include_demo=1", h=A)[1]
        self.assertTrue(any(r["data_origin"] == "demo" for r in ml["items"]))

class Legacy(unittest.TestCase):
    def test_legacy_bridge(self):
        call("/admin/fixtures", {"competition": "Legacy Cup", "season": "2031", "home": "LgA", "away": "LgB", "start_utc": "2031-01-01T10:00:00Z", "source": "manual"}, A)
        fid = db().execute("SELECT id FROM fixtures WHERE home='LgA'").fetchone()[0]
        call("/admin/predictions", {"fixture_id": fid, "toss_pick": "LgA", "winner_pick": "LgB"}, A)
        pid = db().execute("SELECT id FROM legacy_predictions WHERE fixture_id=?", (fid,)).fetchone()[0]
        call("/admin/approve", {"prediction_id": pid}, A)
        s, ml = call("/api/v1/master-list", h=A)
        r = [x for x in ml["items"] if x["competition"] == "Legacy Cup"][0]
        self.assertEqual((r["toss_prediction"]["side"], r["winner_prediction"]["side"]), ("H", "A"))

if __name__ == "__main__":
    unittest.main()
