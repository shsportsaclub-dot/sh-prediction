"""Master Script V1.0 section 11 mandatory quality tests for /api/v1."""
import os, sys, json, time, sqlite3, tempfile, threading, unittest, urllib.request, urllib.error, datetime

D = tempfile.mkdtemp()
os.environ["SH_PREDICTION_DB"] = D + "/v1.sqlite3"
os.environ["SH_PREDICTION_ADMIN_TOKEN"] = "adm-test-token"
os.environ["SH_DEV_EXPOSE_CODES"] = "1"   # tests read verification codes from the API; never set in production
os.environ["SH_MEDIA_DIR"] = D + "/media"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import importlib
import screen_login, main, api_v1, engine
# test_api.py may have imported these first with another DB path: rebind to ours
for mod in (screen_login, main):
    mod.DB = os.environ["SH_PREDICTION_DB"]
api_v1.DB_PATH = os.environ["SH_PREDICTION_DB"]
api_v1.RATE["capacity"] = 100000  # the suite makes thousands of calls from one IP; test_rate_limit checks the limiter itself
from http.server import ThreadingHTTPServer

main.H.log_message = lambda *a: None  # keep test output readable
srv = ThreadingHTTPServer(("127.0.0.1", 0), main.H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % srv.server_port
A = {"X-Admin-Token": "adm-test-token"}
PRE_MIGRATION = None
SOON, SOON_WAIT = 2.5 / 86400, 3.0  # a match starting 2.5 s from now

def _migrate_once():
    global PRE_MIGRATION
    if PRE_MIGRATION is None:
        PRE_MIGRATION = call("/api/v1/matches")
        s, r = call("/api/v1/admin/system/migrate", {"confirm": True}, A)
        assert s == 200 and r["status"] in ("migrated", "up_to_date"), r

def call(path, data=None, h=None, method=None):
    r = urllib.request.Request(B + path, data=json.dumps(data).encode() if data is not None else None,
                               headers=dict({"Content-Type": "application/json"}, **(h or {})), method=method)
    try:
        x = urllib.request.urlopen(r)
        return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def setUpModule():
    _migrate_once()

PASSWORD = "Test-Passw0rd-SH"

def account(username, verify=True):
    s, r = call("/api/v1/auth/register", {"username": username, "email": username + "@example.test", "password": PASSWORD, "display_name": username})
    assert s == 201, r
    if verify:
        s, v = call("/api/v1/auth/verify-email", {"login": username, "code": r["dev_code"]})
        assert s == 200, v
    s, t = call("/api/v1/auth/login", {"login": username, "password": PASSWORD})
    assert s == 200, t
    return {"Authorization": "Bearer " + t["token"]}

def login(phone):
    """Account session for a test user (the old phone-code login is disabled)."""
    uname = "u" + str(phone)
    s, t = call("/api/v1/auth/login", {"login": uname, "password": PASSWORD})
    if s == 200:
        return {"Authorization": "Bearer " + t["token"]}
    return account(uname)
    s, t = None, None
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
    def test_viewer_timezone_country_code_fallback(self):
        s,r=call('/api/viewer-timezone?phone_code=%2B880&device_timezone=Europe%2FParis')
        self.assertEqual(s,200)
        self.assertEqual(r['timezone'],'Asia/Dhaka')
        self.assertEqual(r['source'],'phone_country')
        self.assertNotIn('ip',r)
        self.assertEqual(r['attribution']['license'],'CC BY 4.0')
        s,r=call('/api/viewer-timezone?device_timezone=not-a-zone')
        self.assertEqual(s,200)
        self.assertIsNone(r['timezone'])

    def test_auth_required_and_structured_errors(self):
        s, r = call("/api/v1/me/preferences")
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
        u = login(phone)
        s, r = call("/api/v1/admin/experts", {"display_name": "Unverified Tipster", "username": "u" + phone}, A)
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
        self.assertTrue(any(x["action"] == "match.create" and x["entity_id"] == str(mid) and x["actor"].startswith("admin-token") for x in log["items"]))

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
        s, ml = call("/api/v1/admin/master-list?competition_id=%d" % db().execute("SELECT competition_id FROM matches WHERE id=?", (mid,)).fetchone()[0], h=A)
        row = [r for r in ml["items"] if r["match_id"] == mid][0]
        self.assertEqual((row["toss"], row["winner"]), (None, None))

class MasterList(unittest.TestCase):
    """Approved meaning: ACTUAL results master, admin only. Toss code green if the toss winner won the match, red if it lost."""
    def test_results_master_colours_and_admin_only(self):
        call("/api/v1/admin/teams", {"name": "Ultra Blasters", "short_code": "UB"}, A)
        call("/api/v1/admin/teams", {"name": "Eagle Eyes", "short_code": "EE"}, A)
        self.assertEqual(call("/api/v1/admin/teams", {"name": "Other XI", "short_code": "UB"}, A)[0], 409)
        comp = "Results Master Cup"
        m1 = mk_match("Ultra Blasters", "Eagle Eyes", comp=comp, days=-1, match_no="1")
        m2 = mk_match("Eagle Eyes", "Ultra Blasters", comp=comp, days=-0.5, match_no="2")
        m3 = mk_match("Ultra Blasters", "Eagle Eyes", comp=comp, days=-0.2, match_no="3")
        u1, e1 = team_ids(m1)
        call("/api/v1/admin/toss", {"match_id": m1, "winner_team_id": u1, "decision": "bat", "source": "s"}, A)
        call("/api/v1/admin/results", {"match_id": m1, "result_type": "win", "winner_team_id": u1, "source": "s"}, A)   # H-UB green, H-UB green
        e2, u2 = team_ids(m2)
        call("/api/v1/admin/toss", {"match_id": m2, "winner_team_id": e2, "decision": "bowl", "source": "s"}, A)
        call("/api/v1/admin/results", {"match_id": m2, "result_type": "win", "winner_team_id": u2, "source": "s"}, A)   # H-EE red, A-UB green
        u3, _ = team_ids(m3)
        call("/api/v1/admin/toss", {"match_id": m3, "winner_team_id": u3, "decision": "bat", "source": "s"}, A)         # no result yet
        cid = db().execute("SELECT competition_id FROM matches WHERE id=?", (m1,)).fetchone()[0]
        s, ml = call("/api/v1/admin/master-list?competition_id=%d" % cid, h=A)
        self.assertEqual(ml["columns"], ["Match", "Home", "Away", "Toss", "Winner"])
        cell = lambda x: x and (x["side"], x["code"], x["outcome"])
        r1, r2, r3 = ml["items"]
        self.assertEqual((r1["match"], cell(r1["toss"]), cell(r1["winner"])), ("01", ("H", "UB", "won"), ("H", "UB", "won")))
        self.assertEqual((r2["home"]["code"], cell(r2["toss"]), cell(r2["winner"])), ("EE", ("H", "EE", "lost"), ("A", "UB", "won")))
        self.assertEqual((cell(r3["toss"]), r3["winner"]), (("H", "UB", "unknown"), None))
        # viewers and logged-in users can never read it
        self.assertEqual(call("/api/v1/admin/master-list")[0], 403)
        self.assertEqual(call("/api/v1/admin/master-list", h=login("9100000030"))[0], 403)
        self.assertEqual(call("/api/v1/master-list")[0], 404)

    def test_no_result_and_super_over(self):
        comp = "NR Cup"
        m = mk_match("NrA", "NrB", comp=comp, days=-1)
        h, a = team_ids(m)
        call("/api/v1/admin/toss", {"match_id": m, "winner_team_id": h, "decision": "bat", "source": "s"}, A)
        call("/api/v1/admin/results", {"match_id": m, "result_type": "no_result", "source": "s"}, A)
        m2 = mk_match("NrA", "NrB", comp=comp, days=-0.5)
        call("/api/v1/admin/toss", {"match_id": m2, "winner_team_id": h, "decision": "bat", "source": "s"}, A)
        call("/api/v1/admin/results", {"match_id": m2, "result_type": "tie_super_over", "winner_team_id": a, "source": "s"}, A)
        cid = db().execute("SELECT competition_id FROM matches WHERE id=?", (m,)).fetchone()[0]
        r1, r2 = call("/api/v1/admin/master-list?competition_id=%d" % cid, h=A)[1]["items"]
        self.assertEqual((r1["toss"]["outcome"], r1["winner"]), ("unknown", None))
        self.assertEqual((r2["toss"]["outcome"], r2["winner"]["side"]), ("lost", "A"))

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
        s, b = call("/api/v1/i18n/ml")  # incomplete language falls back to English
        self.assertEqual(b["strings"]["col.toss"], "Toss")

    def test_demo_excluded_from_headline(self):
        before = call("/api/v1/analytics/accuracy", h=A)[1]["overall"]["settled"]
        s, r = call("/api/v1/admin/demo-seed", {}, A)
        self.assertEqual(s, 200, r)
        after = call("/api/v1/analytics/accuracy", h=A)[1]["overall"]["settled"]
        demo = call("/api/v1/analytics/accuracy?dataset=demo", h=A)[1]
        self.assertEqual(before, after)
        self.assertEqual(demo["dataset"], "demo")
        self.assertGreater(demo["overall"]["settled"], 0)
        verified = call("/api/v1/matches?limit=100")[1]["items"]
        demo_list = call("/api/v1/matches?limit=100&dataset=demo")[1]["items"]
        self.assertFalse(any(m["data_origin"] == "demo" for m in verified))
        self.assertTrue(demo_list and all(m["data_origin"] == "demo" for m in demo_list))

class Legacy(unittest.TestCase):
    def test_legacy_bridge(self):
        call("/admin/fixtures", {"competition": "Legacy Cup", "season": "2031", "home": "LgA", "away": "LgB", "start_utc": "2031-01-01T10:00:00Z", "source": "manual"}, A)
        fid = db().execute("SELECT id FROM fixtures WHERE home='LgA'").fetchone()[0]
        call("/admin/predictions", {"fixture_id": fid, "toss_pick": "LgA", "winner_pick": "LgB"}, A)
        pid = db().execute("SELECT id FROM legacy_predictions WHERE fixture_id=?", (fid,)).fetchone()[0]
        call("/admin/approve", {"prediction_id": pid}, A)
        s, reg = call("/api/v1/admin/predictions?limit=100", h=A)
        mine = {(x["prediction_type"], x["predicted_team"]) for x in reg["items"] if x["home"] == "LgA"}
        self.assertEqual(mine, {("toss", "LgA"), ("winner", "LgB")})

if __name__ == "__main__":
    unittest.main()

class Privacy(unittest.TestCase):
    """Owner rule: SH logic (factors, weights, model versions) is visible only to admin."""
    def test_users_see_outcomes_not_logic(self):
        mid = mk_match("PvA", "PvB", days=6)
        self.assertEqual(call("/api/v1/admin/matches/%d/model-prediction" % mid, {}, A)[0], 201)
        u = login("9100000020")
        s, sig = call("/api/v1/matches/%d/signals" % mid, h=u)
        self.assertEqual(s, 200)
        self.assertNotIn("factors", sig["pre_match"])
        self.assertNotIn("history_matches_used", sig["pre_match"])
        self.assertEqual(sig["pre_match"]["model"], "SH AI")
        self.assertIn("home_win_probability", sig["pre_match"])
        s, pr = call("/api/v1/matches/%d/predictions" % mid, h=u)
        self.assertEqual(pr["items"], [])  # locked but not published: invisible to viewers
        pid = call("/api/v1/admin/predictions?match_id=%d" % mid, h=A)[1]["items"][0]["id"]
        self.assertEqual(call("/api/v1/admin/predictions/%d/publish" % pid, {"public_note": "SH AI pick"}, A)[0], 200)
        self.assertEqual(call("/api/v1/admin/predictions/%d/publish" % pid, {}, A)[0], 409)
        self.assertEqual(sig["pre_match"]["public_factors"][0]["factor"], "Recent form")
        s, pr = call("/api/v1/matches/%d/predictions" % mid)  # anonymous viewer
        p = pr["items"][0]
        self.assertNotIn("factors", p)
        self.assertNotIn("model_version_id", p)
        self.assertEqual((p["model"], p["explanation"]), ("SH AI", "SH AI prediction"))
        raw = json.dumps([sig, pr])
        self.assertNotIn("sh-baseline", raw)
        self.assertNotIn("contribution", raw)
        # admin sees everything
        s, sig_a = call("/api/v1/matches/%d/signals" % mid, h=A)
        self.assertEqual(len(sig_a["pre_match"]["factors"]), 4)
        self.assertIn("factors", call("/api/v1/matches/%d/predictions" % mid, h=A)[1]["items"][0])
        acc = call("/api/v1/analytics/accuracy", h=u)[1]
        self.assertEqual(list(acc["by_model"]), ["SH AI"])
        self.assertEqual(call("/api/v1/admin/model-versions", h=u)[0], 403)

    def test_admin_model_versions_secret_weights(self):
        bad_ = call("/api/v1/admin/model-versions", {"version": "x1", "params": {"form_weight": 1}}, A)
        self.assertEqual(bad_[0], 400)
        params = {"form_window": 8, "form_weight": 2.0, "h2h_weight": 0.5, "home_weight": 0.9, "venue_weight": 0.4, "laplace": 1}
        s, r = call("/api/v1/admin/model-versions", {"version": "2.0.0-test", "description": "tuned", "params": params}, A)
        self.assertEqual(s, 201, r)
        self.assertEqual(call("/api/v1/admin/model-versions", {"version": "2.0.0-test", "params": params}, A)[0], 409)
        mid = mk_match("MvA", "MvB", days=6)
        sig = call("/api/v1/matches/%d/signals" % mid, h=A)[1]["pre_match"]
        self.assertEqual(sig["model"], "sh-baseline 2.0.0-test")
        home = [f for f in sig["factors"] if f["factor"] == "home_advantage"][0]
        self.assertEqual(home["contribution"], 0.9)
        log = call("/api/v1/admin/audit?limit=100", h=A)[1]["items"]
        self.assertFalse(any("form_weight" in (x["payload"] or "") for x in log if x["action"] == "model.version"))

    def test_admin_key_with_user_session_keeps_preferences(self):
        u = login("9100000021")
        h = dict(u, **A)
        self.assertEqual(call("/api/v1/me/preferences", {"theme": "light"}, h, "PUT")[0], 200)
        self.assertEqual(call("/api/v1/me/preferences", h=u)[1]["theme"], "light")

class OwnApk(unittest.TestCase):
    def test_redirect_without_token_and_stream_with_token(self):
        import apk, io
        self.assertEqual(apk.resolve(token=""), ("redirect", apk.PUBLIC_URL))
        seen = []
        class Resp(io.BytesIO):
            headers = {}
        def opener(req, follow=True):
            seen.append((req.full_url, req.headers.get("Authorization"), follow))
            if "releases/tags" in req.full_url:
                return Resp(json.dumps({"assets": [{"name": "sh-prediction.apk", "url": "https://api.github.com/assets/9"}]}).encode())
            if req.full_url.endswith("/assets/9"):
                raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://objects.example/apk?sig=1"}, None)
            return Resp(b"APKBYTES")
        kind, r = apk.resolve(token="t0k", opener=opener)
        self.assertEqual((kind, r.read()), ("stream", b"APKBYTES"))
        self.assertEqual(seen[-1][1], None)  # the token is never sent to the storage host
        self.assertEqual(seen[1][2], False)

class MigrationSafety(unittest.TestCase):
    def test_no_migration_on_page_load(self):
        self.assertEqual(PRE_MIGRATION[0], 503)
        self.assertEqual(PRE_MIGRATION[1]["error"]["code"], "MIGRATION_PENDING")

    def test_backup_verified_and_legacy_kept(self):
        import shutil, system, schema
        d = tempfile.mkdtemp()
        path = d + "/old.sqlite3"
        c = sqlite3.connect(path)
        c.executescript("""CREATE TABLE fixtures(id INTEGER PRIMARY KEY,competition TEXT,season TEXT,home TEXT,away TEXT,start_utc TEXT,source TEXT,venue TEXT,match_no TEXT);
        CREATE TABLE predictions(id INTEGER PRIMARY KEY,fixture_id INTEGER UNIQUE,toss_pick TEXT,winner_pick TEXT,created_at TEXT,status TEXT,approved_at TEXT);
        CREATE TABLE outcomes(fixture_id INTEGER PRIMARY KEY,toss_winner TEXT,match_winner TEXT,source TEXT,verified_at TEXT,status TEXT,toss_decision TEXT,remarks TEXT);
        INSERT INTO fixtures VALUES(1,'Old Cup','2026','OA','OB','2026-01-01T10:00:00+00:00','sheet',NULL,'1');
        INSERT INTO predictions VALUES(1,1,'OA','OB','2025-12-31T10:00:00+00:00','approved','2025-12-31T10:00:00+00:00');
        INSERT INTO outcomes VALUES(1,'OA','OA','sheet','2026-01-01T15:00:00+00:00','completed','Bat',NULL);""")
        c.commit(); c.close()
        old_db = main.DB
        main.DB = path
        try:
            conn = main.db()
            self.assertEqual(conn.lp, "predictions")                  # classic screens keep working un-migrated
            _, acc = main.compute(conn)
            self.assertEqual(acc["toss"]["percent"], 100.0)
            r = system.run(conn, path)
            conn.commit()
            self.assertEqual(r["status"], "migrated", r)
            self.assertTrue(os.path.exists(r["backup"]["path"]))
            self.assertTrue(r["checks"]["legacy_predictions_kept"])
            b = sqlite3.connect(r["backup"]["path"])
            self.assertEqual(b.execute("SELECT COUNT(*) FROM predictions WHERE fixture_id=1").fetchone()[0], 1)  # backup = pre-migration copy
            b.close()
            self.assertEqual(schema.pending(conn), [])
            self.assertEqual(system.run(conn, path)["status"], "up_to_date")
            conn.close()
            conn = main.db()
            self.assertEqual(main.compute(conn)[1]["toss"]["percent"], 100.0)   # classic accuracy unchanged after migration
            conn.close()
        finally:
            main.DB = old_db

class ViewerIsolation(unittest.TestCase):
    def test_viewer_cannot_see_private_things(self):
        eid = expert("Hidden Tipster")
        mid = mk_match("ViA", "ViB", days=4)
        h, _ = team_ids(mid)
        pid = predict(mid, "winner", h, eid)[1]["prediction_id"]
        draft = call("/api/v1/predictions", {"match_id": mid, "prediction_type": "toss", "predicted_team_id": h, "expert_id": eid, "lock": False}, A)[1]["prediction_id"]
        u = login("9100000040")
        for who in ({}, u):
            self.assertEqual(call("/api/v1/matches/%d/predictions" % mid, h=who)[1]["items"], [])
            hist = call("/api/v1/experts/%d/history" % eid, h=who)[1]
            self.assertEqual((hist["items"], hist["summary"]["total_predictions"]), ([], 0))
            for p in ("/api/v1/admin/master-list", "/api/v1/admin/predictions", "/api/v1/admin/audit", "/api/v1/admin/dashboard",
                      "/api/v1/admin/users", "/api/v1/admin/settings", "/api/v1/admin/providers", "/api/v1/admin/calibration"):
                self.assertEqual(call(p, h=who)[0], 403, p)
            self.assertEqual(call("/api/v1/admin/predictions/%d/publish" % pid, {}, who)[0], 403)
        self.assertEqual(call("/api/v1/admin/predictions/%d/publish" % draft, {}, A)[1]["error"]["code"], "NOT_LOCKED")
        call("/api/v1/admin/predictions/%d/publish" % pid, {}, A)
        self.assertEqual(len(call("/api/v1/matches/%d/predictions" % mid)[1]["items"]), 1)
        self.assertEqual(call("/api/v1/admin/predictions/%d/unpublish" % pid, {}, A)[0], 400)   # reason required
        self.assertEqual(call("/api/v1/admin/predictions/%d/unpublish" % pid, {"reason": "test"}, A)[0], 200)
        self.assertEqual(call("/api/v1/matches/%d/predictions" % mid)[1]["items"], [])

    def test_publication_cannot_bypass_lock_in_db(self):
        mid = mk_match("PbA", "PbB", days=4)
        h, _ = team_ids(mid)
        eid = expert("Db Tipster")
        draft = call("/api/v1/predictions", {"match_id": mid, "prediction_type": "toss", "predicted_team_id": h, "expert_id": eid, "lock": False}, A)[1]["prediction_id"]
        c = db()
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("INSERT INTO prediction_publications(prediction_id,published_at,published_by) VALUES(?,?,?)", (draft, "x", "x"))
        c.close()

class Engines(unittest.TestCase):
    def test_over_projection_and_phases(self):
        p = engine.over_projection("T20", 50, 1, 36, actual_overs={1: 8, 2: 9, 3: 10, 4: 7, 5: 8, 6: 8})
        self.assertEqual(len(p["overs"]), 20)
        self.assertEqual([x["status"] for x in p["phases"]], ["completed", "projected", "projected"])
        self.assertEqual(p["phases"][0]["runs"], 50)
        self.assertGreater(p["projected_total"], 50)
        self.assertLess(engine.wicket_impact("T20", 2, 120, 5, 96, 160)["next_wicket_swing"], 0)

    def test_calibration_backtest(self):
        comp = "Backtest Cup"
        for i in range(6):
            m = mk_match("BtA", "BtB", comp=comp, days=-30 + i)
            h, a = team_ids(m)
            call("/api/v1/admin/results", {"match_id": m, "result_type": "win", "winner_team_id": h if i % 3 else a, "source": "s"}, A)
        s, r = call("/api/v1/admin/calibration", h=A)
        self.assertEqual(s, 200)
        self.assertGreaterEqual(r["matches_evaluated"], 5)
        self.assertTrue(0 <= r["brier_score"] <= 1)
        self.assertIn("not evidence of skill", r["note"])

    def test_match_centre_sections(self):
        mid = mk_match("McA", "McB", days=-0.01, format="T10")
        h, a = team_ids(mid)
        seq = 0
        for x in (4, 1, "W", 6, 0, 2, "W", 1):
            seq += 1
            b = {"match_id": mid, "innings_no": 1, "batting_team_id": h, "seq": seq}
            b.update({"is_wicket": 1, "wicket_kind": "caught"} if x == "W" else {"runs_bat": x})
            call("/api/v1/admin/ball-events", b, A)
        g = call("/api/v1/matches/%d/graphs" % mid)[1]["innings"][0]
        self.assertEqual(g["worm"], [13, 14])  # over 1: 4+1+0+6+0+2, over 2: W then 1
        fow = call("/api/v1/matches/%d/fall-of-wickets" % mid)[1]["innings"][0]["fall_of_wickets"]
        self.assertEqual([(w["wicket"], w["score"]) for w in fow], [(1, 5), (2, 13)])
        parts = call("/api/v1/matches/%d/partnerships" % mid)[1]["innings"][0]["partnerships"]
        self.assertEqual([(p["runs"], p["wicket"]) for p in parts], [(5, 1), (8, 2), (1, 3)])
        sig = call("/api/v1/matches/%d/signals" % mid)[1]
        self.assertIn("over_by_over", sig)
        self.assertIn("next_wicket_swing", sig["wicket_impact"])
        self.assertFalse(call("/api/v1/matches/%d/result" % mid)[1]["available"])
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": h, "margin": "12 runs", "source": "s"}, A)
        self.assertEqual(call("/api/v1/matches/%d/result" % mid)[1]["summary"], "McA won")

class Fantasy(unittest.TestCase):
    def setUp(self):
        Fantasy.n = getattr(Fantasy, "n", 0) + 1
        self.mid = mk_match("FnA", "FnB", days=3, format="T20", comp="Fantasy Cup %d" % Fantasy.n)
        self.h, self.a = team_ids(self.mid)
        roles = ["wicket_keeper", "batter", "batter", "batter", "all_rounder", "all_rounder", "bowler", "bowler", "bowler", "bowler", "batter"]
        self.ids = {self.h: [], self.a: []}
        for t in (self.h, self.a):
            for i, r in enumerate(roles):
                pid = call("/api/v1/admin/players", {"name": "FP%d-%d" % (t, i), "role": r}, A)[1]["player_id"]
                self.ids[t].append(pid)
                if i < 6:
                    call("/api/v1/admin/player-stats", {"player_id": pid, "format": "T20", "matches": 20, "runs": 300 + 40 * i, "batting_avg": 25,
                                                        "strike_rate": 130, "wickets": 5 * (i % 3), "economy": 8.0, "source": "SH sample"}, A)

    def test_unavailable_until_squad_then_provisional_then_confirmed(self):
        self.assertFalse(call("/api/v1/matches/%d/fantasy" % self.mid)[1]["available"])
        for t in (self.h, self.a):
            call("/api/v1/admin/matches/%d/squad" % self.mid, {"team_id": t, "players": [{"player_id": p} for p in self.ids[t]]}, A)
        r = call("/api/v1/matches/%d/fantasy" % self.mid)[1]
        self.assertEqual((r["available"], r["availability"]), (True, "provisional"))
        for t in (self.h, self.a):
            call("/api/v1/admin/matches/%d/playing-xi" % self.mid, {"team_id": t, "players": [{"player_id": p} for p in self.ids[t]]}, A)
        r = call("/api/v1/matches/%d/fantasy" % self.mid)[1]
        self.assertEqual(r["availability"], "confirmed")
        for team in r["teams"]:
            ps = team["players"]
            self.assertEqual(len(ps), 11)
            self.assertLessEqual(max(sum(1 for p in ps if p["team_id"] == t) for t in (self.h, self.a)), 7)
            roles = [p["role"] for p in ps]
            self.assertTrue(1 <= roles.count("wicket_keeper") <= 4 and 3 <= roles.count("bowler") <= 6)
            self.assertNotEqual(team["captain"]["player_id"], team["vice_captain"]["player_id"])
            self.assertIn(team["risk"], ("low", "medium", "high"))
        labels = [t["label"] for t in r["teams"]]
        self.assertIn("Safe", labels)
        s, st = call("/api/v1/admin/matches/%d/fantasy" % self.mid, {}, A)
        self.assertEqual(s, 200)
        self.assertGreaterEqual(len(call("/api/v1/matches/%d/fantasy-history" % self.mid)[1]["items"]), 1)

    def test_configurable_rules(self):
        bad_rules = {"team_size": 11, "max_per_team": 7, "roles": {"batter": [1, 2]}, "captain_multiplier": 2, "vice_captain_multiplier": 1.5}
        self.assertEqual(call("/api/v1/admin/fantasy/rules", {"name": "Broken", "rules": bad_rules}, A)[0], 400)
        ok = {"team_size": 11, "max_per_team": 10, "roles": {"wicket_keeper": [1, 1], "batter": [4, 5], "all_rounder": [1, 3], "bowler": [3, 5]},
              "captain_multiplier": 2, "vice_captain_multiplier": 1.5}
        self.assertEqual(call("/api/v1/admin/fantasy/rules", {"name": "Strict Keeper", "rules": ok}, A)[0], 200)
        for t in (self.h, self.a):
            call("/api/v1/admin/matches/%d/playing-xi" % self.mid, {"team_id": t, "players": [{"player_id": p} for p in self.ids[t]]}, A)
        r = call("/api/v1/matches/%d/fantasy?rule_set=Strict%%20Keeper" % self.mid)[1]
        self.assertEqual(r["rule_set"], "Strict Keeper")
        self.assertTrue(all([p["role"] for p in t["players"]].count("wicket_keeper") == 1 for t in r["teams"]))

class Assistant(unittest.TestCase):
    def test_grounded_and_honest(self):
        r = call("/api/v1/assistant", {"question": "What is the LBW law?"})[1]
        self.assertTrue(r["grounded"])
        self.assertIn("Law 36", r["answer"])
        r = call("/api/v1/assistant", {"question": "Who is the best player on Mars?"})[1]
        self.assertFalse(r["grounded"])
        self.assertIn("don't have verified data", r["answer"])
        call("/api/v1/admin/teams", {"name": "Assist Lions", "short_code": "ASL"}, A)
        call("/api/v1/admin/teams", {"name": "Assist Tigers", "short_code": "AST"}, A)
        m = mk_match("Assist Lions", "Assist Tigers", days=-2, comp="Assist Cup")
        h, a = team_ids(m)
        call("/api/v1/admin/results", {"match_id": m, "result_type": "win", "winner_team_id": h, "source": "s"}, A)
        r = call("/api/v1/assistant", {"question": "ASL vs AST head to head"})[1]
        self.assertIn("Assist Lions (ASL) won 1", r["answer"])
        self.assertEqual(call("/api/v1/assistant", {"question": "x"})[0], 400)

class DataGateway(unittest.TestCase):
    def test_contract_and_provider_sync(self):
        import gateway
        for p in ("/api/v1/data/fixtures", "/api/v1/data/results", "/api/v1/data/live", "/api/v1/data/history"):
            s, r = call(p)
            self.assertEqual(s, 200, p)
            self.assertTrue(all(x["data_origin"] != "demo" for x in r["items"]))
        s, r = call("/api/v1/admin/providers/demo/sync", {}, A)
        self.assertEqual((s, r["status"], r["rejected"]), (200, "ok", 0))
        s, r2 = call("/api/v1/admin/providers/demo/sync", {}, A)
        self.assertEqual((r2["created"], r2["duplicates"]), (0, r["created"] + r["duplicates"]))
        demo = call("/api/v1/data/fixtures?dataset=demo")[1]["items"]
        self.assertTrue(any(x["match_no"] == "G1" for x in demo))
        self.assertEqual(call("/api/v1/admin/providers/licensed_feed/sync", {}, A)[1]["error"]["code"], "DISABLED")
        self.assertEqual(call("/api/v1/admin/providers/licensed_feed", {"enabled": True}, A)[1]["error"]["code"], "NOT_CONFIGURED")
        self.assertEqual(call("/api/v1/admin/providers/licensed_feed", {"config": {"api_key": "x"}}, A)[0], 400)
        self.assertEqual(gateway.validate({"provider_id": "1", "competition": "c", "home": "a", "away": "b", "start_utc": "2030-01-01T10:00:00", "source": "s"}),
                         "start_utc needs a timezone")

    def test_retry_then_fail_recorded(self):
        import gateway
        calls = []
        class Flaky(gateway.ProviderAdapter):
            name, kind = "manual", "manual"
            def fetch_fixtures(self):
                calls.append(1)
                raise RuntimeError("timeout")
        c = main.db()
        try:
            r = gateway.sync(c, "manual", lambda row: {"status": "created"}, adapter=Flaky(), retries=3, backoff=0)
            self.assertEqual((r["status"], r["attempts"], len(calls)), ("failed", 3, 3))
        finally:
            c.rollback(); c.close()

    def test_stats_endpoints(self):
        mid = mk_match("StA", "StB", days=-3)
        h, _ = team_ids(mid)
        call("/api/v1/admin/results", {"match_id": mid, "result_type": "win", "winner_team_id": h, "source": "s"}, A)
        self.assertEqual(call("/api/v1/data/teams/%d/stats" % h)[1]["won"], 1)
        vid = db().execute("SELECT venue_id FROM matches WHERE id=?", (mid,)).fetchone()[0]
        self.assertEqual(call("/api/v1/data/venues/%d/stats" % vid)[0], 200)
        self.assertEqual(call("/api/v1/data/players/999999/stats")[0], 404)

class AdminOps(unittest.TestCase):
    def test_csv_import_dry_run_then_commit(self):
        csv_text = ("competition,season,match_no,home,away,start_utc,venue,format,source,toss_winner,toss_decision,result_type,winner\n"
                    "Import Cup,2026,1,Imp A,Imp B,2026-03-01T10:00:00+00:00,Imp Ground,T20,manual scorer sheet,Imp A,bat,win,Imp B\n"
                    "Import Cup,2026,2,Imp B,Imp A,2026-03-02T10:00:00+00:00,Imp Ground,T20,manual scorer sheet,,,,\n"
                    "Import Cup,2026,3,Imp B,Imp B,2026-03-03T10:00:00+00:00,Imp Ground,T20,manual scorer sheet,,,,\n")
        s, dry = call("/api/v1/admin/import", {"csv": csv_text}, A)
        self.assertEqual((s, dry["committed"], dry["created"], dry["results"], len(dry["errors"])), (200, False, 2, 1, 1))
        self.assertEqual(db().execute("SELECT COUNT(*) FROM matches m JOIN competitions c ON c.id=m.competition_id WHERE c.name='Import Cup'").fetchone()[0], 0)
        s, real = call("/api/v1/admin/import", {"csv": csv_text, "commit": True}, A)
        self.assertEqual((real["created"], real["results"]), (2, 1))
        again = call("/api/v1/admin/import", {"csv": csv_text, "commit": True}, A)[1]
        self.assertEqual((again["created"], again["duplicates"]), (0, 2))
        cid = db().execute("SELECT id FROM competitions WHERE name='Import Cup'").fetchone()[0]
        r = call("/api/v1/admin/master-list?competition_id=%d" % cid, h=A)[1]["items"][0]
        self.assertEqual((r["toss"]["code"] or r["toss"]["name"], r["toss"]["outcome"], r["winner"]["side"]), ("Imp A", "lost", "A"))

    def test_edit_match_guarded(self):
        eid = expert("Edit Tipster")
        mid = mk_match("EdA", "EdB", days=4)
        h, _ = team_ids(mid)
        predict(mid, "winner", h, eid)
        self.assertEqual(call("/api/v1/admin/matches/%d" % mid, {"start_utc": iso(5)}, A)[1]["error"]["code"], "HAS_LOCKED_PREDICTIONS")
        self.assertEqual(call("/api/v1/admin/matches/%d" % mid, {"weather": "Clear, 31°C", "pitch_report": "Dry, good for spin"}, A)[0], 200)
        self.assertEqual(call("/api/v1/matches/%d" % mid)[1]["weather"], "Clear, 31°C")
        self.assertEqual(call("/api/v1/admin/matches/%d" % mid, {"status": "completed"}, A)[0], 400)

    def test_roles_settings_dashboard(self):
        call("/api/v1/me/preferences", h=login("9100000050"))
        users = call("/api/v1/admin/users?limit=100", h=A)[1]["items"]
        uid = users[0]["id"]
        self.assertNotIn("9100000050", json.dumps(users))  # phone numbers masked
        self.assertEqual(call("/api/v1/admin/users/%d/role" % uid, {"role": "admin"}, A)[0], 400)
        self.assertEqual(call("/api/v1/admin/users/%d/role" % uid, {"role": "expert"}, A)[1]["role"], "expert")
        self.assertEqual(call("/api/v1/admin/settings", {"default_language": "te"}, A)[0], 200)
        self.assertEqual(call("/api/v1/admin/settings", {"default_language": "zz"}, A)[0], 400)
        d = call("/api/v1/admin/dashboard", h=A)[1]
        self.assertIn("locked_unpublished", d["predictions"])
        self.assertEqual(d["pending_migrations"], [])

class Languages(unittest.TestCase):
    def test_coverage_is_honest(self):
        langs = {l["code"]: l for l in call("/api/v1/languages")[1]["items"]}
        self.assertEqual(langs["en"]["coverage_percent"], 100)
        for code in ("te", "hi"):
            self.assertEqual(langs[code]["coverage_percent"], 100, code)
        for code, l in langs.items():
            b = call("/api/v1/i18n/" + code)[1]
            self.assertEqual(b["ui_complete"], l["coverage_percent"] == 100)
            if not b["ui_complete"]:
                self.assertIsNotNone(b["fallback_note"])
        self.assertGreaterEqual(sum(1 for l in langs.values() if l["coverage_percent"] == 100), 6)

# ---------------------------------------------------------------- Cricsheet importer
def _cs_doc(teams, winner=None, by=None, result=None, eliminator=None, method=None, toss=("A", "field"), event="SH Test League", season="2025",
            overs=20, deliveries=None, second=None, mtype="T20", date="2025-04-01"):
    """A small synthetic document in the Cricsheet JSON layout (test data, not real matches)."""
    a, b = teams
    people = {n: "%08x" % (abs(hash(n)) % 0xFFFFFFFF) for n in ("%s1" % a, "%s2" % a, "%s3" % a, "%s1" % b, "%s2" % b)}
    outcome = {}
    if winner: outcome.update(winner=winner, by=by or {"runs": 10})
    if result: outcome["result"] = result
    if eliminator: outcome["eliminator"] = eliminator
    if method: outcome["method"] = method
    def inn(team, bat1, bat2, bowler, balls, target=None):
        overs_l, cur = [], []
        for i, x in enumerate(balls):
            d = {"batter": bat1, "bowler": bowler, "non_striker": bat2, "runs": {"batter": 0, "extras": 0, "total": 0}}
            if x == "W":
                d["wickets"] = [{"player_out": bat1, "kind": "bowled"}]
            elif x == "wd":
                d["runs"] = {"batter": 0, "extras": 1, "total": 1}; d["extras"] = {"wides": 1}
            elif x == "lb":
                d["runs"] = {"batter": 0, "extras": 1, "total": 1}; d["extras"] = {"legbyes": 1}
            else:
                d["runs"] = {"batter": x, "extras": 0, "total": x}
            cur.append(d)
            if sum(1 for y in cur if "extras" not in y or "wides" not in y["extras"]) == 6:
                overs_l.append({"over": len(overs_l), "deliveries": cur}); cur = []
        if cur:
            overs_l.append({"over": len(overs_l), "deliveries": cur})
        r = {"team": team, "overs": overs_l}
        if target: r["target"] = {"runs": target, "overs": overs}
        return r
    innings = [inn(a, "%s1" % a, "%s2" % a, "%s1" % b, deliveries or [4, 6, "wd", 1, "W", 0, 2, "lb"])]
    if second is not None:
        innings.append(inn(b, "%s1" % b, "%s2" % b, "%s1" % a, second, target=sum(x for x in (deliveries or [4, 6, 1, 0, 2]) if isinstance(x, int)) + 3))
    return {"meta": {"data_version": "1.1.0"}, "info": {"balls_per_over": 6, "city": "Testville", "dates": [date], "event": {"name": event, "match_number": 1},
            "gender": "male", "match_type": mtype, "outcome": outcome, "overs": overs, "players": {a: ["%s1" % a, "%s2" % a, "%s3" % a], b: ["%s1" % b, "%s2" % b]},
            "registry": {"people": people}, "season": season, "teams": [a, b], "toss": {"winner": toss[0] if toss[0] in teams else a, "decision": toss[1]},
            "venue": "Synthetic Oval"}, "innings": innings}

def _cs_zip(docs):
    import zipfile, io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, d in docs.items():
            z.writestr(k + ".json", json.dumps(d))
        z.writestr("README.txt", "synthetic")
    return buf.getvalue()

class CricsheetImport(unittest.TestCase):
    def setUp(self):
        import cricsheet
        self.cs = cricsheet
        self.docs = {
            "900001": _cs_doc(("CsLions", "CsTigers"), winner="CsLions", by={"runs": 7}, toss=("CsLions", "bat"), second=[1, 0, "W", 2]),
            "900002": _cs_doc(("CsTigers", "CsLions"), result="tie", eliminator="CsLions", toss=("CsTigers", "field"), date="2025-04-03"),
            "900003": _cs_doc(("CsLions", "CsTigers"), result="no result", toss=("CsTigers", "field"), date="2025-04-05"),
            "900004": _cs_doc(("CsLions", "CsTigers"), winner="CsTigers", by={"wickets": 4}, method="D/L", date="2025-04-07"),
            "900005": _cs_doc(("CsLions", "CsTigers"), winner="CsLions", mtype="Test", date="2025-04-09"),
        }
        data = _cs_zip(self.docs)
        import io as _io
        api_v1.CRICSHEET_OPENER = lambda req, timeout=None: _io.BytesIO(data)

    def tearDown(self):
        api_v1.CRICSHEET_OPENER = None

    def _run(self, body):
        s, r = call("/api/v1/admin/cricsheet/import", body, A)
        self.assertEqual(s, 202, r)
        for _ in range(100):
            runs = call("/api/v1/admin/cricsheet", h=A)[1]["runs"]
            run = [x for x in runs if x["id"] == r["run_id"]][0]
            if run["status"] != "running":
                return run
            time.sleep(0.05)
        self.fail("import did not finish")

    def test_import_results_scorecards_dedupe_and_attribution(self):
        self.assertEqual(call("/api/v1/admin/cricsheet/import", {"file": "https://evil.example/x.zip"}, A)[0], 400)  # fixed allow-list only
        self.assertEqual(call("/api/v1/admin/cricsheet/import", {"file": "ipl"})[0], 403)
        run = self._run({"file": "ipl"})
        self.assertEqual((run["status"], run["created"], run["rejected"]), ("ok", 5, 0), run)   # Test matches are imported too
        again = self._run({"file": "ipl"})
        self.assertEqual((again["created"], again["duplicates"]), (0, 5))
        c = db()
        mid = lambda k: c.execute("SELECT local_id FROM data_provider_syncs WHERE provider='cricsheet' AND provider_entity='match' AND provider_id=?", (k,)).fetchone()[0]
        res = lambda k: tuple(c.execute("SELECT r.result_type, t.name, r.margin, r.method FROM match_results r LEFT JOIN teams t ON t.id=r.winner_team_id WHERE r.match_id=?", (mid(k),)).fetchone())
        self.assertEqual(res("900001"), ("win", "CsLions", "7 runs", None))
        self.assertEqual(res("900002"), ("tie_super_over", "CsLions", None, "Super Over"))
        self.assertEqual(res("900003"), ("no_result", None, None, None))
        self.assertEqual(res("900004"), ("win", "CsTigers", "4 wickets", "D/L"))
        toss = c.execute("SELECT t.name, tr.decision FROM toss_results tr JOIN teams t ON t.id=tr.winner_team_id WHERE tr.match_id=?", (mid("900002"),)).fetchone()
        self.assertEqual(tuple(toss), ("CsTigers", "bowl"))   # Cricsheet "field" is stored as bowl
        # innings 1 of 900001: 4,6,wd,1,W,0,2,lb -> 15 runs, 1 wicket, 7 legal balls
        sc = call("/api/v1/matches/%d/scorecard" % mid("900001"))[1]["innings"][0]
        self.assertEqual((sc["runs"], sc["wickets"], sc["overs"]), (15, 1, "1.1"))
        bat = {p["name"]: p for p in sc["players"]}
        self.assertEqual((bat["CsLions1"]["runs"], bat["CsLions1"]["balls"], bat["CsLions1"]["fours"], bat["CsLions1"]["sixes"]), (13, 7, 1, 1))  # synthetic data keeps the same striker; wide not a ball faced
        self.assertTrue(bat["CsLions1"]["dismissal"].startswith("bowled"))
        self.assertEqual((bat["CsTigers1"]["runs_conceded"], bat["CsTigers1"]["wickets"]), (14, 1))  # leg-bye not charged to the bowler
        m = call("/api/v1/matches/%d" % mid("900001"))[1]
        self.assertIn("Open Data Commons Attribution License", m["attribution"]["text"])
        self.assertEqual(m["data_origin"], "imported")
        self.assertEqual((m["home_away_verified"], m["data_status"]), (0, "historical_ball_by_ball"))   # listed order is not a verified home side
        self.assertIn("not verified", m["home_away_note"])
        self.assertEqual(call("/api/v1/matches/%d" % mid("900005"))[1]["format"], "Test")
        self.assertEqual(len(m["playing_xi"]), 5)
        src = call("/api/v1/sources")[1]["items"][0]
        self.assertEqual((src["name"], src["matches_imported"] >= 4), ("Cricsheet", True))
        # results master and statistics use the imported data; it is never treated as demo
        cid = c.execute("SELECT competition_id FROM matches WHERE id=?", (mid("900001"),)).fetchone()[0]
        ml = call("/api/v1/admin/master-list?competition_id=%d" % cid, h=A)[1]["items"]
        self.assertEqual([(r["toss"]["outcome"] if r["toss"] else None) for r in ml], ["won", "lost", "unknown", "lost", "won"])  # 5th: the Test match, now imported  # 900004: CsLions won the toss, CsTigers won (D/L)
        st = c.execute("SELECT matches, runs FROM player_statistics ps JOIN players p ON p.id=ps.player_id WHERE p.name='CsLions1' AND format='T20'").fetchone()
        self.assertEqual(st[0], 4)
        # same Cricsheet person id -> one player row across matches
        self.assertEqual(c.execute("SELECT COUNT(*) FROM players WHERE name='CsLions1'").fetchone()[0], 1)
        c.close()

    def test_download_retries_then_fails_cleanly(self):
        calls = []
        def boom(req, timeout=None):
            calls.append(req.full_url); raise OSError("network down")
        old = time.sleep
        try:
            import cricsheet as cs
            cs.time.sleep = lambda s: None
            with self.assertRaises(RuntimeError):
                cs.download("recent_2", opener=boom)
        finally:
            cs.time.sleep = old
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(u == "https://cricsheet.org/downloads/recently_added_2_json.zip" for u in calls))
