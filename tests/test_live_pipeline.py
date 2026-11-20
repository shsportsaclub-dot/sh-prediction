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
