"""SH Universal Cricket Data Bridge: owner Google Sheets, League Index registry, CricketData API, Cricsheet
corrections/draws/catalogue, scheduler, APIs, data-status labels and restart persistence.

External services are replaced by local fakes that return the exact formats the real services return
(xlsx export, CricketData JSON, Cricsheet zip + downloads page). These are MOCKED INTEGRATION tests:
the real Google, CricketData and Cricsheet calls run only on the server (see docs/qa/QA-REPORT.md).
"""
import datetime, io, json, os, sqlite3, subprocess, sys, time, unittest, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(__file__))
import test_v1 as T

import openpyxl
import api_v1, cricketdata, cricsheet, gsheets, registry, scheduler


def xlsx(tabs):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in tabs.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    b = io.BytesIO(); wb.save(b)
    return b.getvalue()


class Fake:
    """Serves fixed responses by URL substring; records every URL requested."""
    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        for k, v in self.routes.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return io.BytesIO(v() if callable(v) else v)
        raise urllib.error.URLError("no route for " + url)


def set_sheets(leagues):
    c = T.db()
    c.execute("UPDATE system_settings SET value=? WHERE key='owner_sheets'", (json.dumps(leagues),))
    c.commit(); c.close()


def run(name, opener):
    return scheduler.run_job(T.db, name, opener=opener)


def match_by(provider, pid):
    c = T.db()
    try:
        r = c.execute("SELECT local_id FROM data_provider_syncs WHERE provider=? AND provider_entity='match' AND provider_id=?", (provider, pid)).fetchone()
        return r[0] if r else None
    finally:
        c.close()


def free_plan():
    c = T.db()
    c.execute("DELETE FROM system_settings WHERE key IN ('cricketdata_plan_override','cricketdata_plan')")
    c.commit(); c.close()


class OwnerSheets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_sync_codes_corrections_blanks_and_unshared(self):
        lg = {"league": "SH Sheet T10 Test", "sheet_id": "SHEETT10", "format": "T10", "gender": "men", "tz": "+04:00"}
        rows = [["SH Sheet T10 Test 2026"], [],
                ["Match", "Date", "Time", "Home", "Away", "Venue", "Toss", "Decision", "Winner", "Margin"],
                ["01", "2026-11-18", "18:00", "QXUB", "QXYL", "Zayed Cricket Stadium", "H-QXUB", "Bat", "H-QXUB", "8 runs"],
                ["02", "18/11/2026", "", "QXRD", "QXEE", None, "H-QXRD", None, "A-QXEE", None],
                ["03", "2026-11-19", "20:15", "QXUT", "QXAA", None, None, None, None, None],
                ["04", "", "", "QXYL", "QXEE", None, None, None, None, None]]
        book = {"v": xlsx({"2026": rows, "Notes": [["anything"]]})}
        fake = Fake({"SHEETT10": lambda: book["v"], "NOTSHARED": b"<!DOCTYPE html><html>Sign in</html>"})
        set_sheets([lg, {"league": "Private league", "sheet_id": "NOTSHARED", "format": "T20", "gender": "men"}])
        r = run("owner_sheets_sync", fake)
        self.assertEqual(r["status"], "ok", r)
        k = r["summary"]["leagues"]["SH Sheet T10 Test"]
        self.assertEqual((k["created"], k["skipped"], k["toss"], k["results"]), (3, 1, 2, 2), k)   # row 04 has no date: skipped, reported
        self.assertTrue(any("not shared publicly" in e for e in r["summary"]["errors"]))           # unshared sheet: clear error, others still sync
        m1 = T.call("/api/v1/matches/%d" % match_by("owner_sheets", "SHEETT10:2026:01"))[1]
        self.assertEqual((m1["start_utc"], m1["toss_decision"], m1["result_type"], m1["margin"]), ("2026-11-18T14:00:00+00:00", "bat", "win", "8 runs"))   # 18:00 at +04:00, stored in UTC
        self.assertEqual(m1["home"]["name"], "QXUB")
        m2 = T.call("/api/v1/matches/%d" % match_by("owner_sheets", "SHEETT10:2026:02"))[1]
        self.assertTrue(m2["start_utc"].startswith("2026-11-18T00:00:00"))                         # no time in the sheet: date only, said so
        self.assertIn("Start time not supplied", m2["source"])
        self.assertIsNone(m2["toss_decision"])                                                     # blank decision stays unknown
        m3 = T.call("/api/v1/matches/%d" % match_by("owner_sheets", "SHEETT10:2026:03"))[1]
        self.assertEqual((m3["status"], m3["result_type"], m3["data_status"]), ("scheduled", None, "upcoming"))
        # second run: nothing changed -> no duplicates, nothing rewritten
        again = run("owner_sheets_sync", fake)["summary"]["leagues"]["SH Sheet T10 Test"]
        self.assertEqual((again["created"], again["unchanged"]), (0, 3))
        # owner corrects match 02's winner and fills match 03's result
        rows[4][8] = "H-QXRD"; rows[5][6] = "A-QXAA"; rows[5][8] = "A-QXAA"
        book["v"] = xlsx({"2026": rows})
        fix = run("owner_sheets_sync", fake)["summary"]["leagues"]["SH Sheet T10 Test"]
        self.assertEqual((fix["created"], fix["updated"], fix["results"]), (0, 2, 2))
        self.assertEqual(T.call("/api/v1/matches/%d" % m2["id"])[1]["winner_team_id"], m2["home"]["id"])
        c = T.db()
        n = c.execute("SELECT COUNT(*) FROM matches m JOIN competitions cp ON cp.id=m.competition_id WHERE cp.name='SH Sheet T10 Test'").fetchone()[0]
        audit = c.execute("SELECT COUNT(*) FROM audit_logs WHERE action='result.revise' AND entity_id=?", (str(m2["id"]),)).fetchone()[0]
        c.close()
        self.assertEqual((n, audit), (3, 1))                                                       # still 3 matches; the correction is audited

    def test_builtin_xlsx_reader_matches_openpyxl(self):
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "2026"
        ws.append(["Match", "Date", "Time", "Home", "Away", "Toss", "Winner"])
        ws.append(["01", datetime.date(2026, 11, 18), datetime.time(18, 0), "UB", "YL", "H-UB", "H-UB"])
        ws.append([2, "18/11/2026", "20:15", "RDC", "EE", None, "A-EE"])
        b = io.BytesIO(); wb.save(b)
        pick = lambda tabs: [(gsheets.parse_date(x["date"]), gsheets.parse_time(x["time"]), x["match_no"], x["home"], x["toss"], x["winner"])
                             for x in gsheets.parse_rows(tabs["2026"])[1]]
        self.assertEqual(pick(gsheets.read_tabs(b.getvalue())), pick(gsheets.read_tabs_stdlib(b.getvalue())))
        self.assertEqual(pick(gsheets.read_tabs_stdlib(b.getvalue()))[0][:2], (datetime.date(2026, 11, 18), datetime.time(18, 0)))

    def test_header_detection_and_side_resolution(self):
        hm, data = gsheets.parse_rows([["Team 1", "Team 2", "Match Date", "Toss Winner", "Match Winner"], ["Lions", "Tigers", "2026-01-02", "Tigers", "A-Tigers"]])
        self.assertEqual((data[0]["home"], data[0]["away"], data[0]["toss"]), ("Lions", "Tigers", "Tigers"))
        self.assertEqual([gsheets.side(v, "Lions", "Tigers") for v in ("H-Lions", "A", "Tigers", "lions", "Somebody", None)], ["H", "A", "A", "H", None, None])


class IndexRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_index_tabs_load_as_unverified(self):
        # rows exactly as they appear in the owner's "SH Predictor - Global League Index" (read on 19 Nov 2026)
        book = xlsx({
            "Country League Directory": [["Country / Region", "Division", "Category", "Competition", "Historical Seasons", "2026 Status", "Source Verification"],
                                         ["Afghanistan", "Men", "League", "Shpageeza Cricket League", "To research", "Verify", "Pending"],
                                         ["Bangladesh", "Men", "Domestic", "Dhaka Premier Division Cricket League", "To research", "Verify", "Pending"]],
            "Research Push 01": [["Country/Region", "Category", "Division", "Competition Season", "Start Date", "End Date", "Reference", "Source URL", "Historical First Edition", "History Status"],
                                 ["Pakistan", "Domestic", "Men", "Quaid-e-Azam Trophy Gold 2026", "2026-11-03", "2026-12-19", "CREX", "https://crex.com/series", "Not yet verified", "Research pending"]],
            "World Competition Catalogue": [["Competition", "Category", "Division", "Scope", "History", "Verification"],
                                            ["ICC T20 World Cup", "International", "Men", "Global", "To research", "Pending source/season verification"]]})
        r = run("registry_index_sync", Fake({registry.INDEX_SHEET: book}))
        self.assertEqual(r["status"], "ok", r)
        items = {}
        for q in ("Shpageeza", "ICC T20 World Cup", "Quaid"):
            items.update({x["name"]: x for x in T.call("/api/v1/admin/registry/competitions?q=" + q.replace(" ", "%20"), h=T.A)[1]["items"]})
        self.assertEqual((items["Shpageeza Cricket League"]["country"], items["Shpageeza Cricket League"]["verification"]), ("Afghanistan", "unverified"))
        self.assertEqual(items["ICC T20 World Cup"]["verification"], "unverified")
        countries = {x["name"]: x for x in T.call("/api/v1/admin/registry/countries?limit=100", h=T.A)[1]["items"]}
        self.assertEqual((countries["India"]["icc_status"], countries["India"]["board_name"]), ("full", "Board of Control for Cricket in India"))
        self.assertEqual(countries["Pakistan"]["competitions"] >= 1, True)
        self.assertEqual(countries["Nepal"]["research_status"], "Not Researched")
        self.assertIn(T.call("/api/v1/admin/registry/countries")[0], (401, 403))                    # admin only
        srcs = {s["key"]: s for s in T.call("/api/v1/admin/registry/sources", h=T.A)[1]["items"]}
        self.assertEqual((srcs["cricsheet"]["permission"], srcs["crex"]["permission"], srcs["crex"]["adapter"]), ("verified", "not_permitted", "none"))


CD_MATCHES = {"apikey": "x", "status": "success", "info": {"hitsToday": 7, "hitsLimit": 100}, "data": [
    {"id": "cd-111", "name": "QY Lions vs QY Tigers, 3rd T20I, QY Tour of Testland, 2026", "matchType": "t20", "status": "QY Lions won by 6 wkts",
     "venue": "Test Oval", "date": "2026-11-15", "dateTimeGMT": "2026-11-15T13:30:00", "teams": ["QY Lions", "QY Tigers"],
     "teamInfo": [{"name": "QY Lions", "shortname": "QYL"}, {"name": "QY Tigers", "shortname": "QYT"}],
     "score": [{"r": 150, "w": 7, "o": 20, "inning": "QY Tigers Inning 1"}, {"r": 151, "w": 4, "o": 18.2, "inning": "QY Lions Inning 1"}],
     "tossWinner": "QY Tigers", "tossChoice": "bat", "matchWinner": "QY Lions", "matchStarted": True, "matchEnded": True},
    {"id": "cd-222", "name": "QY Lions vs QY Tigers, 4th T20I, QY Tour of Testland, 2026", "matchType": "t20", "status": "QY Tigers opt to bowl",
     "venue": "Test Oval", "date": "2026-11-19", "dateTimeGMT": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
     "teams": ["QY Lions", "QY Tigers"], "score": [{"r": 41, "w": 1, "o": 5.0, "inning": "QY Lions Inning 1"}],
     "tossWinner": "QY Tigers", "tossChoice": "bowl", "matchStarted": True, "matchEnded": False},
    {"id": "cd-333", "name": "QY Lions vs QY Tigers, 5th T20I, QY Tour of Testland, 2026", "matchType": "t20", "status": "Match not started",
     "venue": "Test Oval", "date": "2026-12-01", "dateTimeGMT": "2026-12-01T13:30:00", "teams": ["QY Lions", "QY Tigers"], "matchStarted": False, "matchEnded": False}]}


class CricketDataAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def setUp(self):
        os.environ["CRICKETDATA_API_KEY"] = "test-key-123"
        free_plan()

    def tearDown(self):
        os.environ.pop("CRICKETDATA_API_KEY", None)

    def test_matches_live_score_budget_and_no_key(self):
        os.environ.pop("CRICKETDATA_API_KEY")
        self.assertEqual(run("cricketdata_matches", Fake({}))["status"], "skipped")                 # no key: nothing called
        os.environ["CRICKETDATA_API_KEY"] = "test-key-123"
        fake = Fake({"/v1/matches": json.dumps(CD_MATCHES).encode(), "/v1/currentMatches": json.dumps(CD_MATCHES).encode()})
        r = run("cricketdata_matches", fake)
        self.assertEqual((r["status"], r["summary"]["created"]), ("ok", 3), r)
        self.assertNotIn("test-key-123", json.dumps(r))                                             # key never logged
        done = T.call("/api/v1/matches/%d" % match_by("cricketdata", "cd-111"))[1]
        self.assertEqual((done["competition"], done["result_type"], done["margin"], done["toss_decision"]), ("QY Tour of Testland, 2026", "win", "6 wkts", "bat"))
        self.assertEqual((done["data_status"], done["home_away_verified"]), ("result_only", 0))      # score-only source: no ball-by-ball claimed
        live = T.call("/api/v1/matches/%d" % match_by("cricketdata", "cd-222"))[1]
        self.assertEqual((live["status"], live["data_status"], live["live_score"]["innings"][0]["r"]), ("live", "live_score_only", 41))
        self.assertFalse(live["live_score"]["ball_by_ball"])
        # the live job spends a hit only when a CricketData match is live/starting
        self.assertEqual(run("cricketdata_live", fake)["status"], "ok")
        # stale live score -> "Delayed", never a made-up update
        c = T.db(); c.execute("UPDATE live_scores SET fetched_at='2026-01-01T00:00:00+00:00' WHERE match_id=?", (live["id"],)); c.commit(); c.close()
        self.assertEqual(T.call("/api/v1/matches/%d" % live["id"])[1]["data_status"], "delayed")
        # budget: SH PREDICTION never spends more than its daily share
        c = T.db(); c.execute("UPDATE api_budget SET hits=60 WHERE provider='cricketdata'"); c.commit(); c.close()
        r = run("cricketdata_matches", fake)
        self.assertEqual(r["status"], "failed")
        self.assertIn("daily limit reached", r["error"])
        b = T.call("/api/v1/admin/bridge", h=T.A)[1]
        self.assertEqual((b["cricketdata"]["key_configured"], b["cricketdata"]["hits_used_today"]), (True, 60))
        c = T.db()
        raw = c.execute("SELECT COUNT(*) FROM source_records WHERE provider='cricketdata'").fetchone()[0]
        c.close()
        self.assertGreaterEqual(raw, 3)                                                              # original source records kept

    def test_bot_key_name_also_accepted(self):
        os.environ.pop("CRICKETDATA_API_KEY", None); os.environ["CRIC_API_KEY"] = "bot-name-key"
        try:
            self.assertEqual(cricketdata.key(), "bot-name-key")
        finally:
            os.environ.pop("CRIC_API_KEY", None)

    def test_any_cric_key_variable_is_found(self):
        os.environ.pop("CRICKETDATA_API_KEY", None); os.environ["CRICDATA_APIKEY"] = "odd-name-key"
        try:
            self.assertEqual((cricketdata.key(), cricketdata.key_name()), ("odd-name-key", "CRICDATA_APIKEY"))
            b = T.call("/api/v1/admin/bridge", h=T.A)[1]["cricketdata"]
            self.assertEqual((b["key_configured"], b["key_variable"]), (True, "CRICDATA_APIKEY"))
            self.assertNotIn("odd-name-key", json.dumps(b))                                          # value never shown
        finally:
            os.environ.pop("CRICDATA_APIKEY", None)

    def test_reserve_protects_shared_key(self):
        near = dict(CD_MATCHES, info={"hitsToday": 90, "hitsLimit": 100})
        c = T.db()
        c.execute("DELETE FROM api_budget"); c.commit()
        cricketdata.call(c, "matches", {"offset": 0}, 60, Fake({"/v1/matches": json.dumps(near).encode()}))
        self.assertEqual(cricketdata.hits_used(c), 60)                                               # provider says <15 left: stop for today
        c.close()


class CricsheetBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_draw_correction_catalogue_and_backfill(self):
        test = T._cs_doc(("QZ Lions", "QZ Tigers"), result="draw", mtype="Test", date="2024-01-02", event="QZ Test Series")
        t20 = T._cs_doc(("QZ Lions", "QZ Tigers"), winner="QZ Lions", date="2024-02-02", event="QZ League")
        page = b'<a href="/downloads/qzl_json.zip">QZ League</a> <a href="/downloads/recently_added_7_json.zip">r</a> <a href="/downloads/all_json.zip">all</a>'
        z1 = T._cs_zip({"990001": test, "990002": t20})
        fake = Fake({"/downloads/qzl_json.zip": z1, "/downloads/": page})
        c = T.db()
        c.execute("UPDATE collector_jobs SET config_json=? WHERE name='cricsheet_backfill'", (json.dumps({"priority": ["qzl_json.zip"], "skip": ["all_json.zip"], "done": []}),))
        c.commit(); c.close()
        r = run("cricsheet_backfill", fake)
        self.assertEqual((r["status"], r["summary"]["created"], r["summary"]["remaining_files"]), ("ok", 2, 0), r)
        dm = T.call("/api/v1/matches/%d" % match_by("cricsheet", "990001"))[1]
        self.assertEqual((dm["format"], dm["result_type"], dm["status"]), ("Test", "draw", "completed"))
        self.assertEqual(run("cricsheet_backfill", fake)["summary"]["status"][:3], "all")            # catalogue done; recent files keep it current
        # Cricsheet publishes a corrected file for 990002 (winner changed): records replaced, no duplicates
        t20b = T._cs_doc(("QZ Lions", "QZ Tigers"), winner="QZ Tigers", date="2024-02-02", event="QZ League")
        z2 = T._cs_zip({"990002": t20b})
        mid = match_by("cricsheet", "990002")
        c = T.db(); before = c.execute("SELECT COUNT(*) FROM ball_events WHERE match_id=?", (mid,)).fetchone()[0]; c.close()
        out = run("cricsheet_recent", Fake({"recently_added_7_json.zip": z2}))
        self.assertEqual(out["status"], "ok", out)
        c = T.db()
        after = c.execute("SELECT COUNT(*) FROM ball_events WHERE match_id=?", (mid,)).fetchone()[0]
        w = c.execute("SELECT t.name FROM match_results r JOIN teams t ON t.id=r.winner_team_id WHERE r.match_id=?", (mid,)).fetchone()[0]
        n = c.execute("SELECT COUNT(*) FROM data_provider_syncs WHERE provider='cricsheet' AND provider_id='990002'").fetchone()[0]
        c.close()
        self.assertEqual((before, after, w, n), (before, before, "QZ Tigers", 1))
        # public cricket API: deliveries and statistics, with the scorecard cross-check
        st = T.call("/api/v1/cricket/matches/%d/statistics" % mid)[1]["innings"][0]
        self.assertTrue(st["deliveries_match_total"])
        self.assertEqual(T.call("/api/v1/cricket/matches/%d/deliveries" % mid)[1]["total"], after)
        self.assertEqual(T.call("/api/v1/cricket/matches/%d/playing-xi" % mid)[0], 200)

    def test_players_not_merged_by_name(self):
        a = T._cs_doc(("QW A", "QW B"), winner="QW A", date="2024-03-01", event="QW Cup")
        b = T._cs_doc(("QW A", "QW B"), winner="QW B", date="2024-03-05", event="QW Cup")
        a["info"]["registry"] = {"people": {}}; b["info"]["registry"] = {"people": {}}               # no reliable IDs in either file
        r = run("cricsheet_recent", Fake({"recently_added_7_json.zip": T._cs_zip({"990101": a, "990102": b})}))
        self.assertEqual(r["status"], "ok", r)
        c = T.db()
        n = c.execute("SELECT COUNT(*), MIN(identity_status) FROM players WHERE name='QW A1'").fetchone()
        c.close()
        self.assertEqual(tuple(n), (2, "unverified"))                                                # same name, two records kept for review


class SchedulerAndApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_backoff_log_admin_controls_and_public_status(self):
        c = T.db(); c.execute("UPDATE collector_jobs SET consecutive_failures=0 WHERE name='registry_index_sync'"); c.commit(); c.close()
        r = run("registry_index_sync", Fake({"docs.google.com": urllib.error.URLError("offline")}))
        self.assertEqual(r["status"], "failed")
        c = T.db()
        j = c.execute("SELECT * FROM collector_jobs WHERE name='registry_index_sync'").fetchone()
        nxt = datetime.datetime.fromisoformat(j["next_run_at"]); gap = (nxt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        logs = c.execute("SELECT COUNT(*) FROM collector_log WHERE job='registry_index_sync' AND status='failed'").fetchone()[0]
        c.close()
        self.assertTrue(200 < gap < 330, gap)                                                       # retry after 5 min, not the 24 h interval
        self.assertGreaterEqual(logs, 1)
        self.assertIn(T.call("/api/v1/admin/bridge")[0], (401, 403))
        self.assertIn(T.call("/api/v1/admin/bridge/jobs/cricketdata_live/disable", {})[0], (401, 403))
        self.assertEqual(T.call("/api/v1/admin/bridge/jobs/cricketdata_live/config", {"daily_budget": 40, "interval_minutes": 20}, T.A)[0], 200)
        self.assertEqual(T.call("/api/v1/admin/bridge/jobs/cricketdata_live/config", {"interval_minutes": 1}, T.A)[0], 400)
        self.assertEqual(T.call("/api/v1/admin/bridge/jobs/nope/run", {}, T.A)[0], 404)
        b = T.call("/api/v1/admin/bridge", h=T.A)[1]
        jl = {j["name"]: j for j in b["jobs"]}
        self.assertEqual((jl["cricketdata_live"]["interval_minutes"], jl["cricketdata_live"]["config"]["daily_budget"]), (20, 40))
        pub = T.call("/api/v1/cricket/sources/status")[1]
        self.assertIn("not claimed", pub["coverage_note"])
        self.assertEqual({x["key"] for x in pub["items"]}, {"cricsheet", "cricketdata", "owner_sheets", "sh_scoring"})
        self.assertTrue(all("apikey" not in json.dumps(x) for x in pub["items"]))


class RestartPersistence(unittest.TestCase):
    def test_imported_matches_survive_a_real_server_restart(self):
        import socket, tempfile, shutil
        T._migrate_once()
        tmp = tempfile.mkdtemp()
        dbf = os.path.join(tmp, "copy.sqlite3")
        src = sqlite3.connect(os.environ["SH_PREDICTION_DB"]); dst = sqlite3.connect(dbf); src.backup(dst); src.close(); dst.close()
        expect = sqlite3.connect(dbf).execute("SELECT COUNT(*) FROM data_provider_syncs WHERE provider_entity='match' AND provider IN ('cricsheet','owner_sheets','cricketdata')").fetchone()[0]
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        env = dict(os.environ, SH_PREDICTION_DB=dbf, PORT=str(port), HOST="127.0.0.1", SH_COLLECTORS="0", SH_MEDIA_DIR=os.path.join(tmp, "m"))
        app = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
        for _ in range(2):                                                                          # start, stop, start again
            p = subprocess.Popen([sys.executable, app], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    try:
                        j = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/v1/matches?limit=100&status=completed" % port).read()); break
                    except Exception:
                        time.sleep(0.1)
                b = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/v1/admin/bridge" % port,
                                                                             headers={"X-Admin-Token": os.environ["SH_PREDICTION_ADMIN_TOKEN"]})).read())
            finally:
                p.terminate(); p.wait(10)
        self.assertGreater(expect, 0)
        self.assertEqual(sum(b["matches_by_source"].values()), expect)
        self.assertGreater(j["total"], 0)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


SC = {"status": "success", "info": {"hitsToday": 20, "hitsLimit": 100}, "data": {"scorecard": [{"inning": "QY Lions Inning 1",
      "batting": [{"batsman": {"id": "p1", "name": "GM Harris"}, "r": 20, "b": 13, "4s": 1, "6s": 2, "sr": 153.85, "dismissal-text": "not out"},
                  {"batsman": {"id": "p2", "name": "C Knott"}, "r": 16, "b": 12, "4s": 2, "6s": 1, "sr": 133.33, "dismissal-text": "not out"}],
      "bowling": [{"bowler": {"id": "p9", "name": "S Bates"}, "o": 2, "m": 0, "r": 16, "w": 0, "nb": 0, "wd": 1, "eco": 8}],
      "extras": {"b": 0, "lb": 0, "w": 2, "nb": 1, "p": 0}, "totals": {"R": 39, "W": 0, "O": 4}}]}}
SQ = {"status": "success", "info": {}, "data": [{"teamName": "QY Lions", "players": [{"id": "p1", "name": "GM Harris", "role": "Batting Allrounder"}]},
                                              {"teamName": "QY Tigers", "players": [{"id": "p9", "name": "S Bates", "role": "Bowler"}]}]}
INFO = {"status": "success", "info": {}, "data": {"name": "x", "bbbEnabled": True, "tossWinner": "QY Tigers", "tossChoice": "bowl", "secret": "drop"}}
BBB = {"status": "success", "info": {}, "data": {"bbb": [{"n": 1, "inning": 0, "over": 0, "ball": 1, "runs": 4, "batsman": {"name": "GM Harris"}, "bowler": {"name": "S Bates"}},
                                                      {"n": 2, "inning": 0, "over": 0, "ball": 2, "runs": 0, "batsman": {"name": "GM Harris"}, "bowler": {"name": "S Bates"}},
                                                      {"n": 7, "inning": 0, "over": 1, "ball": 1, "runs": 6, "batsman": {"name": "C Knott"}, "bowler": {"name": "X"}}]}}


class FeaturedDetail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def setUp(self):
        os.environ["CRICKETDATA_API_KEY"] = "test-key-123"
        free_plan()
        c = T.db(); c.execute("DELETE FROM api_budget"); c.commit(); c.close()

    def tearDown(self):
        os.environ.pop("CRICKETDATA_API_KEY", None)

    def test_featured_live_match_gets_scorecard_squads_balls(self):
        fake = Fake({"/v1/matches": json.dumps(CD_MATCHES).encode(), "match_scorecard": json.dumps(SC).encode(), "match_squad": json.dumps(SQ).encode(),
                     "match_info": json.dumps(INFO).encode(), "match_bbb": json.dumps(BBB).encode()})
        run("cricketdata_matches", fake)
        r = run("cricketdata_detail", fake)
        self.assertEqual(r["status"], "ok", r)
        live = match_by("cricketdata", "cd-222")
        self.assertEqual([x["match_id"] for x in r["summary"]["featured"]], [live])          # only the live match, max 1 on the free plan
        pd = T.call("/api/v1/matches/%d" % live)[1]["provider_detail"]
        inn = pd["scorecard"][0]
        self.assertEqual((inn["batting"][0]["name"], inn["batting"][0]["fours"], inn["batting"][0]["sixes"], inn["total"]["r"]), ("GM Harris", 1, 2, 39))
        self.assertEqual((inn["bowling"][0]["name"], inn["bowling"][0]["eco"], inn["extras"]["nb"]), ("S Bates", 8, 1))
        self.assertEqual([s["team"] for s in pd["squads"]], ["QY Lions", "QY Tigers"])
        self.assertEqual(pd["runs_per_over"], [{"inning": "0", "over": 1, "runs": 4}, {"inning": "0", "over": 2, "runs": 6}])
        self.assertNotIn("secret", pd["info"])
        self.assertEqual(T.call("/api/v1/matches/%d" % live)[1]["data_status"], "live_scorecard")
        hits = sum(1 for u in fake.urls if "match_" in u)
        self.assertEqual(hits, 4)
        # free plan: an immediate re-run spends nothing; 6 min later 1 hit (scorecard); squad/info every 2 h, balls every 12 min
        run("cricketdata_detail", fake)
        self.assertEqual(sum(1 for u in fake.urls if "match_" in u) - hits, 0)
        c = T.db(); c.execute("UPDATE ext_match_detail SET scorecard_at=? WHERE match_id=?",
                              ((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=6)).isoformat(), live)); c.commit(); c.close()
        run("cricketdata_detail", fake)
        self.assertEqual(sum(1 for u in fake.urls if "match_" in u) - hits, 1)
        c = T.db(); c.execute("UPDATE ext_match_detail SET scorecard_at='2000-01-01T00:00:00+00:00' WHERE match_id=?", (live,)); c.commit(); c.close()
        # provider refuses the scorecard (plan): note shown, nothing invented
        fake.routes["match_scorecard"] = json.dumps({"status": "failure", "reason": "Not on your plan"}).encode()
        r3 = run("cricketdata_detail", fake)
        self.assertIn("Not on your plan", json.dumps(r3["summary"]))
        self.assertTrue(any("Not on your plan" in n for n in T.call("/api/v1/matches/%d" % live)[1]["provider_detail"]["notes"]))

    def test_history_venue_form_h2h(self):
        mid = match_by("cricsheet", "990002")
        if not mid:
            self.skipTest("depends on CricsheetBridge import")
        h = T.call("/api/v1/matches/%d" % mid)[1]["history"]
        self.assertIn("head_to_head", h)
        self.assertIn("SH database", h["note"])


class TipsterRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_overall_world_rank_and_pinned_me(self):
        H = T.account("rank_tipster_a")
        c = T.db()
        uid = c.execute("SELECT user_id FROM accounts WHERE username='rank_tipster_a'").fetchone()[0]
        c.close()
        T.call("/api/v1/me/tipster-application", {}, H)
        T.call("/api/v1/admin/social/moderate", {"action": "approve_tipster", "target_type": "user", "target_id": uid, "reason": "test"}, T.A)
        j = T.call("/api/v1/social/leaderboard", h=H)[1]
        self.assertEqual(j["board"], "overall")
        self.assertEqual((j["me"]["username"], j["me"]["rank"] >= 1, j["me"]["out_of"]), ("rank_tipster_a", True, j["total_ranked"]))
        self.assertIn("Shrunk accuracy", j["rule"])
        self.assertTrue(all("user_id" not in x for x in j["items"]))
        acc = T.call("/api/v1/social/leaderboard?board=accuracy", h=H)[1]["me"]          # no settled picks yet: not ranked, told why
        self.assertIsNone(acc["rank"]); self.assertIn("settled picks", acc["reason"])
        viewer = T.account("rank_viewer_b")
        self.assertIn("only tipsters", T.call("/api/v1/social/leaderboard", h=viewer)[1]["me"]["reason"])
        self.assertIsNone(T.call("/api/v1/social/leaderboard")[1]["me"])                  # anonymous: no pinned row


class PlanModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def setUp(self):
        os.environ["CRICKETDATA_API_KEY"] = "test-key-123"

    def tearDown(self):
        os.environ.pop("CRICKETDATA_API_KEY", None)
        T.call("/api/v1/admin/bridge/plan", {"mode": "unlimited", "until": "2026-11-29"}, T.A)

    def test_owner_unlimited_plan_until_date_then_auto(self):
        b = T.call("/api/v1/admin/bridge", h=T.A)[1]["cricketdata"]
        self.assertEqual(b["plan_override"], {"mode": "unlimited", "until": "2026-11-29"})          # seeded from the owner's note
        self.assertEqual((b["effective"]["budget"], b["live_refresh_seconds"]), ("unlimited", 10))
        self.assertEqual(T.call("/api/v1/admin/bridge/plan", {"mode": "unlimited", "until": "2020-01-01"}, T.A)[0], 200)
        b = T.call("/api/v1/admin/bridge", h=T.A)[1]["cricketdata"]
        self.assertIsNone(b["plan_override"])                                                       # expired: back to the reported limit
        self.assertEqual(T.call("/api/v1/admin/bridge/plan", {"mode": "unlimited"}, T.A)[0], 400)
        self.assertIn(T.call("/api/v1/admin/bridge/plan", {"mode": "auto"})[0], (401, 403))
        c = T.db()
        c.execute("INSERT INTO system_settings(key,value,updated_at,updated_by) VALUES('cricketdata_plan','{\"hitsLimit\": 2000}','x','t') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        c.commit()
        A = cricketdata.auto(c, {})
        c.close()
        self.assertEqual((A["budget"], A["max_featured"], A["scorecard_every_min"]), (1985, 4, 2))     # paid 2,000/day plan

    def test_fast_live_loop_refreshes_and_pushes_live_events(self):
        import threading
        T.call("/api/v1/admin/bridge/plan", {"mode": "unlimited", "until": "2099-01-01"}, T.A)
        sc = json.loads(json.dumps(SC))
        fake = Fake({"/v1/matches": json.dumps(CD_MATCHES).encode(), "currentMatches": json.dumps(CD_MATCHES).encode(),
                     "match_scorecard": lambda: json.dumps(sc).encode(), "match_squad": json.dumps(SQ).encode(),
                     "match_info": json.dumps(INFO).encode(), "match_bbb": json.dumps(BBB).encode()})
        run("cricketdata_matches", fake)
        live = match_by("cricketdata", "cd-222")
        c = T.db(); before = c.execute("SELECT COUNT(*) FROM live_events WHERE match_id=?", (live,)).fetchone()[0]; c.close()
        stop = threading.Event()
        th = threading.Thread(target=scheduler.live_loop, args=(T.db, fake, stop), daemon=True); th.start()
        time.sleep(1.5)
        sc["data"]["scorecard"][0]["totals"] = {"R": 45, "W": 1, "O": 4.3}                          # next ball: provider score moves
        c = T.db(); c.execute("UPDATE ext_match_detail SET scorecard_at='2000-01-01T00:00:00+00:00' WHERE match_id=?", (live,)); c.commit(); c.close()
        stop.set(); th.join(5)
        stop2 = threading.Event(); th2 = threading.Thread(target=scheduler.live_loop, args=(T.db, fake, stop2), daemon=True); th2.start()
        time.sleep(1.5); stop2.set(); th2.join(5)
        c = T.db()
        ev = [json.loads(r[0]) for r in c.execute("SELECT payload FROM live_events WHERE match_id=? AND kind='ball' ORDER BY id", (live,))]
        c.close()
        self.assertGreaterEqual(len(ev), before + 1)
        self.assertEqual(ev[-1]["score"], "45-1")                                                   # the app gets the new score pushed
        hdr = T.call("/api/v1/matches/%d" % live)[1]["provider_detail"]["scorecard"][0]["total"]
        self.assertEqual((hdr["r"], hdr["w"]), (45, 1))


class LiveDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def setUp(self):
        os.environ["CRICKETDATA_API_KEY"] = "test-key-123"
        free_plan()

    def tearDown(self):
        os.environ.pop("CRICKETDATA_API_KEY", None)

    def test_live_job_finds_live_matches_it_did_not_know(self):
        cur = {"status": "success", "info": {"hitsToday": 3, "hitsLimit": 100}, "data": [
            {"id": "cd-new-live", "name": "QV Hawks vs QV Owls, 9th Match, QV Cup, 2026", "matchType": "t20", "status": "QV Owls opt to bowl",
             "venue": "QV Park", "dateTimeGMT": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%S"),
             "teams": ["QV Hawks", "QV Owls"], "score": [{"r": 52, "w": 2, "o": 6.1, "inning": "QV Hawks Inning 1"}], "matchStarted": True, "matchEnded": False}]}
        c = T.db(); c.execute("UPDATE collector_jobs SET config_json='{\"daily_budget\": \"auto\"}' WHERE name='cricketdata_live'"); c.commit(); c.close()
        r = run("cricketdata_live", Fake({"currentMatches": json.dumps(cur).encode()}))
        self.assertEqual(r["status"], "ok", r)
        self.assertGreaterEqual(r["summary"]["live_now"], 1)
        m = T.call("/api/v1/matches/%d" % match_by("cricketdata", "cd-new-live"))[1]
        self.assertEqual((m["status"], m["live_score"]["innings"][0]["r"]), ("live", 52))
        self.assertIn(m["id"], [x["id"] for x in T.call("/api/v1/matches?status=live&limit=100")[1]["items"]])   # shows on Home -> Live
        again = run("cricketdata_live", Fake({"currentMatches": json.dumps(cur).encode()}))
        self.assertEqual(again["status"], "ok")   # a live match is now known, so it keeps refreshing it


class AutoPrepare(unittest.TestCase):
    def test_empty_db_prepared_at_startup_but_never_a_db_with_data(self):
        import tempfile, main, schema
        old = main.DB
        try:
            main.DB = os.path.join(tempfile.mkdtemp(), "fresh.sqlite3")
            self.assertEqual(main.auto_prepare_empty_db(), "prepared")
            c = main.db(); self.assertEqual(schema.pending(c), []); c.close()
            self.assertEqual(main.auto_prepare_empty_db(), "up_to_date")
            main.DB = os.path.join(tempfile.mkdtemp(), "old.sqlite3")
            c = main.db(); c.execute("INSERT INTO fixtures(competition,season,home,away,start_utc,source) VALUES('x','1','A','B','2030-01-01T00:00:00Z','s')"); c.commit(); c.close()
            self.assertEqual(main.auto_prepare_empty_db(), "has_data")                  # real data: waits for the admin's backup + migrate
            c = main.db(); self.assertTrue(schema.pending(c)); c.close()
        finally:
            main.DB = old
