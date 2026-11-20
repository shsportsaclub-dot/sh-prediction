"""SH live pipeline: commentary extras/dismissals, persistent event identity (restart-safe), per-ball live events."""
import json, os, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import sh_commentary_agent as A
import live_bridge as LB


def ball(**k):
    d = {"match_id": "SYNTHETIC-1", "over": 3, "ball": 2, "batter": "Batter One", "bowler": "Bowler Two", "runs_bat": 0, "extras": {}}
    d.update(k)
    return d


class Commentary(unittest.TestCase):
    """Synthetic structured balls (test only)."""
    def test_byes_and_legbyes_are_not_dot_balls(self):
        for lang in ("en", "te"):
            t = A.commentary(ball(extras={"byes": 2}), lang)["text"]
            self.assertNotIn("Dot", t); self.assertNotIn("డాట్", t)
            self.assertIn("2", t)
            t = A.commentary(ball(extras={"legbyes": 1}), lang)["text"]
            self.assertNotIn("Dot", t); self.assertNotIn("డాట్", t)
        self.assertIn("leg bye", A.commentary(ball(extras={"legbyes": 1}))["text"])
        self.assertIn("Dot ball", A.commentary(ball())["text"])

    def test_dismissal_kinds_and_no_ball_runs(self):
        self.assertIn("leg before wicket", A.commentary(ball(wicket=True, wicket_kind="lbw"))["text"])
        self.assertIn("run out", A.commentary(ball(wicket=True, wicket_kind="run out", extras={"byes": 1}))["text"])
        self.assertIn("stumped", A.commentary(ball(wicket=True, wicket_kind="stumped"))["text"])
        t = A.commentary(ball(runs_bat=4, extras={"noball": 1}))["text"]
        self.assertIn("No-ball", t); self.assertIn("4 off the bat", t)
        # never invents shots, fielders or speeds
        for b in (ball(runs_bat=6), ball(wicket=True, wicket_kind="caught")):
            t = A.commentary(b)["text"].lower()
            for word in ("cover", "slip", "km/h", "pull", "drive", "yorker"):
                self.assertNotIn(word, t)


class PersistentDedup(unittest.TestCase):
    def test_restart_does_not_republish(self):
        path = os.path.join(tempfile.mkdtemp(), "keys.sqlite3")
        db = lambda: sqlite3.connect(path)
        events = [{"provider": "synthetic", "match_id": "9", "innings": 1, "over": 0, "ball": i} for i in range(1, 4)]
        sent = []
        b1 = LB.LiveBridge(lambda: events, lambda k, e: sent.append(k), seen=LB.SqliteSeen(db))
        self.assertEqual(b1.poll_once(), 3)
        b2 = LB.LiveBridge(lambda: events + [{"provider": "synthetic", "match_id": "9", "innings": 1, "over": 0, "ball": 4}],
                           lambda k, e: sent.append(k), seen=LB.SqliteSeen(db))       # a new process after a restart
        self.assertEqual(b2.poll_once(), 1)
        self.assertEqual(len(sent), len(set(sent)), 4)

    def test_failed_publish_is_retried(self):
        path = os.path.join(tempfile.mkdtemp(), "keys.sqlite3")
        db = lambda: sqlite3.connect(path)
        calls = []
        def pub(k, e):
            calls.append(k)
            if len(calls) == 1:
                raise RuntimeError("store down")
        b = LB.LiveBridge(lambda: [{"match_id": "1", "event_id": "x"}], pub, seen=LB.SqliteSeen(db))
        with self.assertRaises(RuntimeError):
            b.poll_once()
        self.assertEqual(b.poll_once(), 1)          # the key was not marked seen when publishing failed


if __name__ == "__main__":
    unittest.main()


class ProviderBalls(unittest.TestCase):
    """CricketData ball rows -> one 'delivery' live event each, with SH commentary; never twice (synthetic rows, test DB only)."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_v1 as T
        cls.T = T
        T._migrate_once()

    def test_new_balls_published_once(self):
        import cricketdata
        T = self.T
        mid = T.mk_match("Lp Owls", "Lp Hawks", days=0)
        c = T.db()
        b = lambda n, over, ball, **k: dict({"n": n, "inning": 0, "over": over, "ball": ball, "runs": 0, "batter": "Bat A", "bowler": "Bowl B"}, **k)
        backlog = [b(1, 0, 1), b(2, 0, 2, runs=4)]
        self.assertEqual(cricketdata.publish_new_balls(c, mid, backlog, None), 0)          # match already running: backlog recorded, not flooded
        balls = backlog + [b(3, 0, 3, runs=1, extra="lb"), b(4, 0, 4, wicket=True)]
        self.assertEqual(cricketdata.publish_new_balls(c, mid, balls, None), 2)
        self.assertEqual(cricketdata.publish_new_balls(c, mid, balls, None), 0)            # repeated poll / restart: nothing new
        c.commit()
        ev = [json.loads(r[0]) for r in c.execute("SELECT payload FROM live_events WHERE match_id=? AND kind='delivery' ORDER BY id", (mid,))]
        c.close()
        self.assertEqual([e["over"] for e in ev], ["0.3", "0.4"])
        self.assertIn("leg bye", ev[0]["commentary"].lower())
        self.assertNotIn("no run", ev[0]["commentary"].lower())                             # a leg bye is not a dot ball
        self.assertTrue(ev[1]["wicket"])
        self.assertEqual(ev[0]["status"], "PROVIDER_REPORTED")


class PlayerPhotos(unittest.TestCase):
    """Wikimedia lookups are faked here (no network in tests)."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_v1 as T
        cls.T = T
        T._migrate_once()

    def fake(self, lic):
        def f(url):
            if "en.wikipedia.org" in url:
                return {"query": {"pages": {"1": {"index": 1, "title": "Henry Nicholls", "description": "New Zealand cricketer", "pageimage": "HN.jpg",
                                                   "thumbnail": {"source": "https://upload.wikimedia.org/x/240px-HN.jpg"}}}}}
            return {"query": {"pages": {"-1": {"imageinfo": [{"extmetadata": {"LicenseShortName": {"value": lic}, "Artist": {"value": "<a>Some Photographer</a>"}}}]}}}}
        return f

    def test_free_licence_only_and_cached(self):
        import photos, schema
        c = self.T.db()
        out = photos.get_many(c, ["Henry Nicholls"], schema.now, fetch=self.fake("CC BY-SA 4.0"))
        self.assertEqual((out["Henry Nicholls"]["license"], out["Henry Nicholls"]["author"]), ("CC BY-SA 4.0", "Some Photographer"))
        calls = []
        photos.get_many(c, ["Henry Nicholls"], schema.now, fetch=lambda u: calls.append(u))       # cached: no outside call
        self.assertEqual(calls, [])
        out = photos.get_many(c, ["Nathan Smith"], schema.now, fetch=self.fake("Fair use"))       # surname mismatch / non-free: none
        self.assertIsNone(out["Nathan Smith"])
        c.execute("DELETE FROM player_photos")
        out = photos.get_many(c, ["Henry Nicholls"], schema.now, fetch=self.fake("Non-free media"))
        self.assertIsNone(out["Henry Nicholls"])
        c.close()


class ScorecardCommentary(unittest.TestCase):
    """No ball rows from the source: SH lines and board flashes from two scorecard snapshots (synthetic cards)."""
    def card(self, r, w, o, bats, bowl=None):
        return [{"inning": "Heat Inning 1", "total": {"r": r, "w": w, "o": o},
                 "batting": [{"name": n, "r": rr, "b": bb, "fours": f, "sixes": s, "dismissal": d} for n, rr, bb, f, s, d in bats],
                 "bowling": bowl or []}]

    def test_four_six_wicket_and_dot(self):
        import cricketdata as CD
        a = self.card(100, 0, "9.3", [("Grace Harris", 34, 23, 2, 3, "not out"), ("Charli Knott", 28, 19, 4, 1, "not out")])
        b = self.card(104, 0, "9.4", [("Grace Harris", 38, 24, 3, 3, "not out"), ("Charli Knott", 28, 19, 4, 1, "not out")])
        u = CD.derive_updates(a, b)
        self.assertTrue(u[0]["text"].startswith("FOUR! Grace Harris"))
        self.assertEqual(u[0]["flash"], {"runs": 4})
        c = self.card(110, 0, "9.5", [("Grace Harris", 44, 25, 3, 4, "not out"), ("Charli Knott", 28, 19, 4, 1, "not out")])
        self.assertEqual(CD.derive_updates(b, c)[0]["flash"], {"runs": 6})
        d = self.card(110, 1, "9.6", [("Grace Harris", 44, 26, 3, 4, "c Smith b Bates"), ("Charli Knott", 28, 19, 4, 1, "not out")])
        u = CD.derive_updates(c, d)
        self.assertEqual(u[0]["kind"], "wicket"); self.assertTrue(u[0]["flash"]["wicket"])
        self.assertIn("c Smith b Bates, 44 (26)", u[0]["text"])
        e = self.card(110, 1, "10.1", [("Grace Harris", 44, 26, 3, 4, "c Smith b Bates"), ("Charli Knott", 28, 20, 4, 1, "not out")])
        u = CD.derive_updates(d, e)
        self.assertEqual((u[0]["text"], u[0]["flash"]), ("No run.", {"runs": 0}))
        # several balls between two looks: a summary line, no flash (we cannot tell which ball did what)
        f = self.card(121, 1, "10.4", [("Grace Harris", 44, 26, 3, 4, "c Smith b Bates"), ("Charli Knott", 39, 23, 5, 1, "not out")])
        u = CD.derive_updates(e, f)
        self.assertIsNone(u[0]["flash"])


class BackfillAndNews(unittest.TestCase):
    """Synthetic data only: replay kept scorecard snapshots once; RSS headlines parsed to title + link + publisher."""
    def test_backfill_replays_snapshots_once(self):
        import cricketdata as CD
        c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE matches(id INTEGER PRIMARY KEY)"); c.execute("INSERT INTO matches VALUES(7)")
        c.execute("CREATE TABLE data_provider_syncs(provider TEXT, provider_entity TEXT, provider_id TEXT, local_id INTEGER)")
        c.execute("INSERT INTO data_provider_syncs VALUES('cricketdata','match','pid-7',7)")
        c.execute("CREATE TABLE source_records(id INTEGER PRIMARY KEY, provider TEXT, provider_id TEXT, kind TEXT, payload TEXT, payload_hash TEXT, fetched_at TEXT)")
        def raw(r, o, h, h4):
            return {"scorecard": [{"inning": "Heat Inning 1", "batting": [{"batsman": {"name": "A Batter"}, "r": h, "b": 10, "4s": h4, "6s": 0, "dismissal-text": "not out"}],
                                   "bowling": [], "totals": {"R": r, "W": 0, "O": o}}]}
        for i, (r, o, h, h4) in enumerate([(10, 1.5, 10, 1), (14, 1.6, 14, 2), (15, 2.1, 15, 2)]):
            c.execute("INSERT INTO source_records(provider,provider_id,kind,payload,payload_hash,fetched_at) VALUES('cricketdata','pid-7','scorecard',?,?,?)",
                      (json.dumps(raw(r, o, h, h4)), str(i), "2026-11-20T01:0%d:00+00:00" % i))
        n = CD.backfill_updates(c, 7)
        rows = c.execute("SELECT text, created_at FROM score_updates ORDER BY id").fetchall()
        self.assertGreaterEqual(n, 1)
        self.assertTrue(any("FOUR" in r[0] for r in rows), [r[0] for r in rows])
        self.assertEqual(CD.backfill_updates(c, 7), 0)     # only once

    def test_rss_headlines(self):
        import news
        xml = b"""<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
          <item><title>Test side win series</title><link>https://example.org/a</link><description>&lt;p&gt;Short teaser.&lt;/p&gt;</description>
          <pubDate>Fri, 20 Nov 2026 01:00:00 GMT</pubDate><media:thumbnail url="https://example.org/i.jpg"/></item>
          <item><title>No link</title></item></channel></rss>"""
        items = news.parse_rss(xml, "Publisher")
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["title"], items[0]["summary"], items[0]["source"], items[0]["image"]), ("Test side win series", "Short teaser.", "Publisher", "https://example.org/i.jpg"))
        self.assertTrue(items[0]["published_at"].startswith("2026-11-20T01:00"))
        c = sqlite3.connect(":memory:")
        class R:
            def __init__(s, b): s.b = b
            def read(s): return s.b
        out = news.fetch(c, {"feeds": [{"name": "Publisher", "url": "https://example.org/rss"}], "keep_days": 100000}, lambda: "2026-11-20T02:00:00+00:00", lambda req, timeout: R(xml))
        self.assertEqual(out["new"], 1)
        self.assertEqual(news.fetch(c, {"feeds": [{"name": "Publisher", "url": "x"}], "keep_days": 100000}, lambda: "t", lambda req, timeout: R(xml))["new"], 0)


class LiveLoopStatus(unittest.TestCase):
    """Unlimited plan: the fast loop runs, a failing match does not stop the others, /api/v1/live-status reports it (synthetic provider)."""
    def test_loop_and_status(self):
        import copy, threading
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_bridge as TB
        import scheduler
        TB.T._migrate_once(); os.environ["CRICKETDATA_API_KEY"] = "k"
        try:
            c = TB.T.db()
            c.execute("DELETE FROM api_budget")
            c.execute("INSERT INTO system_settings(key,value,updated_at,updated_by) VALUES('cricketdata_plan_override',?, 'now','t') "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps({"mode": "unlimited"}),))
            c.commit(); c.close()
            sc = copy.deepcopy(TB.SC)
            fake = TB.Fake({"/v1/matches": json.dumps(TB.CD_MATCHES).encode(), "currentMatches": json.dumps(TB.CD_MATCHES).encode(),
                            "match_scorecard": lambda: json.dumps(sc).encode(), "match_squad": json.dumps(TB.SQ).encode(),
                            "match_info": json.dumps(TB.INFO).encode(), "match_bbb": json.dumps(TB.BBB).encode()})
            TB.run("cricketdata_matches", fake)
            stop = threading.Event()
            th = threading.Thread(target=scheduler.live_loop, args=(TB.T.db, fake, stop), daemon=True); th.start()
            for _ in range(50):
                if scheduler.LIVE_STATE.get("last_ok"):
                    break
                stop.wait(0.1)
            stop.set(); th.join(5)
            st = TB.T.call("/api/v1/live-status")[1]
            self.assertTrue(st["key_set"] and st["plan_unlimited"])
            self.assertIsNotNone(st["loop"]["last_ok"], st)
            m = [x for x in st["matches"] if x["featured"]]
            self.assertTrue(m and m[0]["balls"] == 3 and m[0]["scorecard_age_s"] is not None, st)
            self.assertNotIn("apikey", json.dumps(st))
        finally:
            os.environ.pop("CRICKETDATA_API_KEY", None); TB.free_plan()


class TwoProvidersMerge(unittest.TestCase):
    """Synthetic balls: CricketData + SH Data Line merged into one list, each delivery once, conflicts counted, live events once."""
    CD = [{"n": 1, "inning": "Heat Inning 1", "over": 0, "ball": 1, "runs": 1, "wicket": False, "extra": None},
          {"n": 2, "inning": "Heat Inning 1", "over": 0, "ball": 2, "runs": 1, "wicket": False, "extra": "wd"},
          {"n": 3, "inning": "Heat Inning 1", "over": 0, "ball": 2, "runs": 4, "wicket": False, "extra": None}]
    SH = [{"inning": 1, "over": 0, "ball": 1, "runs": 1, "wicket": False, "extra": None, "src": "sh"},      # same as CD ball 1
          {"inning": 1, "over": 0, "ball": 2, "runs": 6, "wicket": False, "extra": None, "src": "sh"},      # disagrees with CD ball 3
          {"inning": 1, "over": 0, "ball": 3, "runs": 0, "wicket": True, "extra": None, "src": "sh"}]      # only SH has it

    def test_merge(self):
        import ball_merge
        out, st = ball_merge.merge(self.CD, self.SH)
        self.assertEqual(len(out), 4)
        self.assertEqual((st["duplicates"], st["conflicts"], st["added"]), (2, 1, [3, 1]))
        self.assertEqual(out[2]["runs"], 4)                       # first provider kept, nothing changed
        self.assertTrue(out[3]["wicket"] and out[3]["src"] == "sh")

    def test_sh_data_line_sync_and_single_events(self):
        import shdataline, cricketdata
        c = sqlite3.connect(":memory:"); c.row_factory = sqlite3.Row
        c.executescript("""CREATE TABLE teams(id INTEGER PRIMARY KEY, name TEXT, short_code TEXT);
            CREATE TABLE matches(id INTEGER PRIMARY KEY, home_team_id INT, away_team_id INT, status TEXT, start_utc TEXT, data_origin TEXT);
            CREATE TABLE data_provider_syncs(id INTEGER PRIMARY KEY, provider TEXT, provider_entity TEXT, provider_id TEXT, local_table TEXT, local_id INT, synced_at TEXT,
                UNIQUE(provider,provider_entity,provider_id));
            CREATE TABLE ext_match_detail(match_id INTEGER PRIMARY KEY, source TEXT, balls_json TEXT, balls_at TEXT);
            CREATE TABLE live_events(id INTEGER PRIMARY KEY, match_id INT, kind TEXT, payload TEXT, created_at TEXT);
            INSERT INTO teams VALUES(1,'Brisbane Heat Women','BH-W'),(2,'Sydney Thunder Women','ST-W'),(3,'Brisbane Heat','BH'),(4,'Sydney Thunder','ST');
            INSERT INTO matches VALUES(5,3,4,'live','2026-11-20T08:00:00+00:00','provider'),(6,1,2,'live','2026-11-20T08:00:00+00:00','provider');""")
        c.execute("INSERT INTO ext_match_detail VALUES(6,'cricketdata',?, 'x')", (json.dumps(self.CD),))
        pubs = []
        import live
        orig = live.publish
        live.publish = lambda c_, mid, kind, p: pubs.append((mid, kind, p))
        os.environ.update(SH_DATA_API_URL="https://sh-data-line.example", SH_DATA_API_KEY="secret-k")
        try:
            cricketdata.publish_new_balls(c, 6, self.CD, lambda: "t")          # backlog recorded, nothing sent
            class R:
                def __init__(s, o): s.o = o
                def read(s): return json.dumps(s.o).encode()
            seen = []
            def opener(req, timeout):
                seen.append(req.headers.get("Authorization"))
                if req.full_url.endswith("/api/v1/matches"):
                    return R({"matches": [{"match_id": "dl-1", "status": "live", "teams": ["Sydney Thunder Women", "Brisbane Heat Women"], "source": "x"},
                                          {"match_id": "dl-2", "status": "live", "teams": ["Nowhere XI", "Elsewhere XI"], "source": "x"}]})
                return R({"balls": [{"innings": 1, "over_number": 0, "ball_number": b["ball"], "runs_bat": b["runs"], "extras": 0, "wicket": b["wicket"],
                                     "source": "x", "source_event_id": str(i)} for i, b in enumerate(self.SH)]})
            r = shdataline.sync(c, lambda: "2026-11-20T09:00:00+00:00", opener)
            self.assertEqual((r["linked"], r["seen"], r["new_sh_balls"], r["conflicts"]), (1, 2, 1, 1), r)   # women's match, not the men's
            self.assertEqual(shdataline.STATE["unlinked"], ["Nowhere XI v Elsewhere XI"])
            self.assertEqual(len(json.loads(c.execute("SELECT balls_json FROM ext_match_detail WHERE match_id=6").fetchone()[0])), 4)
            self.assertEqual([p[2]["wicket"] for p in pubs if p[1] == "delivery"], [True])                 # only the new SH ball goes live
            shdataline.sync(c, lambda: "t2", opener)
            self.assertEqual(len([p for p in pubs if p[1] == "delivery"]), 1)                              # repeat poll: nothing twice
            self.assertTrue(all(h == "Bearer secret-k" for h in seen))
            self.assertIsNone(c.execute("SELECT 1 FROM ext_match_detail WHERE match_id=5").fetchone())
        finally:
            live.publish = orig
            for k in ("SH_DATA_API_URL", "SH_DATA_API_KEY"):
                os.environ.pop(k, None)
