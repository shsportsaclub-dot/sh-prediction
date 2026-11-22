"""Automatic updates without manual sheet edits:
- a league sheet added to the owner's Global League Index is imported by the 30-minute sheet job on its own;
- a CricketData match for the same fixture joins the sheet's match (team spellings/order and start minute may differ),
  so the provider's toss and result appear on the owner's match instead of on a duplicate;
- rows first imported with bare team codes move to full names once the league's code map is known."""
import json, os, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import test_v1 as T
from test_bridge import xlsx, Fake, set_sheets, run, match_by, free_plan
import api_v1, gsheets, registry

ILT20 = "1dI9hLDwJq6J1bXapXI3nLYdsp7k2zvghXmMal7FKocg"
HEAD = ["#", "DATE", "IST", "HOME", "VS", "AWAY", "TOSS", "WIN", "RESULT", "P.T", "T✓", "P.WIN", "W✓", "NOTES"]
INDEX = xlsx({
    "Leagues": [["League", "Category", "Country", "Start Season", "Sheet Link", "Status"],
                ["International League T20", "Men", "UAE", "2026-27 (Season 5)", "https://docs.google.com/spreadsheets/d/%s/edit" % ILT20, "Auto-filled"],
                ["No link yet", "Women", "Nowhere", "", "", ""]],
    "World Competition Catalogue": [["Competition", "Category"], ["ICC T20 World Cup", "International"]]})
SHEET = xlsx({"SH Complete Match Master": [HEAD,
    ["1", "21-11-2026", "08:00 PM", "DV\n—", "VS", "MIE\n—", "—", "—", "Pending", "—", "—", "H-DV", "—", "opener"],
    ["2", "22-11-2026", "03:30 PM", "SW\n—", "VS", "GG\n—", "—", "—", "Pending", "—", "—", "—", "—", ""]]})
CD = {"status": "success", "info": {"hitsToday": 5, "hitsLimit": 100}, "data": [
    # provider lists the teams in the other order and a start 20 minutes off the sheet's time
    {"id": "cd-ilt-1", "name": "MI Emirates vs Desert Vipers, 1st Match, International League T20 2026-27", "matchType": "t20",
     "status": "MI Emirates won by 20 runs", "venue": "Dubai", "date": "2026-11-21", "dateTimeGMT": "2026-11-21T14:50:00",
     "teams": ["MI Emirates", "Desert Vipers"], "score": [{"r": 174, "w": 6, "o": 20, "inning": "MI Emirates Inning 1"}],
     "tossWinner": "Desert Vipers", "tossChoice": "bowling", "matchWinner": "MI Emirates", "matchStarted": True, "matchEnded": True}]}


class AutoLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def tearDown(self):
        os.environ.pop("CRICKETDATA_API_KEY", None)

    def test_index_league_then_provider_result_reaches_sheet_match(self):
        set_sheets([])
        fake = Fake({registry.INDEX_SHEET: INDEX, ILT20: SHEET})
        r = run("owner_sheets_sync", fake)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["summary"]["new_from_index"], ["International League T20"])
        c = T.db()
        lg = json.loads(c.execute("SELECT value FROM system_settings WHERE key='owner_sheets'").fetchone()[0])
        self.assertEqual([(x["sheet_id"], x["format"], x["gender"]) for x in lg], [(ILT20, "T20", "men")])
        c.close()
        mid = match_by("owner_sheets", "%s:SH Complete Match Master:1" % ILT20)
        m = T.call("/api/v1/matches/%d" % mid)[1]
        self.assertEqual((m["home"]["name"], m["away"]["name"], m["start_utc"]), ("Desert Vipers", "MI Emirates", "2026-11-21T14:30:00+00:00"))
        # second run: nothing new from the index, nothing re-created
        r = run("owner_sheets_sync", fake)
        self.assertEqual(r["summary"]["new_from_index"], [])
        # CricketData reports the same fixture: it joins the sheet match, never a duplicate
        os.environ["CRICKETDATA_API_KEY"] = "test-key-123"
        free_plan()
        r = run("cricketdata_matches", Fake({"/v1/matches": json.dumps(CD).encode()}))
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(match_by("cricketdata", "cd-ilt-1"), mid)
        m = T.call("/api/v1/matches/%d" % mid)[1]
        self.assertEqual((m["home"]["name"], m["away"]["name"]), ("Desert Vipers", "MI Emirates"))           # owner's home/away kept
        self.assertEqual((m["result_type"], m["margin"], m["toss_decision"]), ("win", "20 runs", "bowl"))
        c = T.db()
        w = c.execute("SELECT t.name FROM match_results r JOIN teams t ON t.id=r.winner_team_id WHERE r.match_id=?", (mid,)).fetchone()[0]
        tw = c.execute("SELECT t.name FROM toss_results r JOIN teams t ON t.id=r.winner_team_id WHERE r.match_id=?", (mid,)).fetchone()[0]
        n = c.execute("""SELECT COUNT(*) FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
                         WHERE h.name IN ('Desert Vipers','MI Emirates') AND a.name IN ('Desert Vipers','MI Emirates')""").fetchone()[0]
        c.close()
        self.assertEqual((w, tw, n), ("MI Emirates", "Desert Vipers", 1))

    def test_codes_learned_later_rename_teams(self):
        sid = "1TESTcodesSheet000000000000000000000000000"
        lg = {"league": "Code Test League", "sheet_id": sid, "format": "T20", "gender": "men", "tz": "+05:30"}
        book = xlsx({"Master": [HEAD, ["1", "10-11-2026", "07:00 PM", "QXA\n—", "VS", "QXB\n—", "—", "—", "Pending", "—", "—", "—", "—", ""]]})
        set_sheets([lg])
        run("owner_sheets_sync", Fake({sid: book}))
        mid = match_by("owner_sheets", "%s:Master:1" % sid)
        self.assertEqual(T.call("/api/v1/matches/%d" % mid)[1]["home"]["name"], "QXA")
        set_sheets([dict(lg, codes={"QXA": "Qx Alphas", "QXB": "Qx Betas"})])
        run("owner_sheets_sync", Fake({sid: book}))
        m = T.call("/api/v1/matches/%d" % mid)[1]
        self.assertEqual((m["home"]["name"], m["away"]["name"]), ("Qx Alphas", "Qx Betas"))

    def test_same_fixture_never_guesses(self):
        self.assertEqual(api_v1.team_key("Durban Super Giants"), api_v1.team_key("Durban's Super Giants"))
        self.assertEqual(api_v1.team_key("Sudur Paschim Royals"), api_v1.team_key("Sudurpaschim Royals"))
        self.assertNotEqual(api_v1.team_key("Sydney Sixers"), api_v1.team_key("Sydney Sixers Women"))
        c = T.db()
        who = {"actor": "t", "role": "admin", "user_id": None}
        base = {"competition": "Link Guard Cup", "source": "test", "data_origin": "imported", "format": "T20"}
        a = api_v1.admin_match(c, who, dict(base, home="Zq One", away="Zq Two", start_utc="2026-10-01T10:00:00+00:00", provider="owner_sheets", provider_id="lg-1"))
        b = api_v1.admin_match(c, who, dict(base, competition="Other Cup", home="Zq Two", away="Zq One", start_utc="2026-10-01T11:00:00+00:00",
                                            provider="cricketdata", provider_id="lg-cd-1"))
        self.assertEqual((b["status"], b["match_id"]), ("linked", a["match_id"]))
        # a second provider fixture cannot claim the same match; far-apart times never link
        b2 = api_v1.admin_match(c, who, dict(base, home="Zq One", away="Zq Two", start_utc="2026-10-01T12:00:00+00:00", provider="cricketdata", provider_id="lg-cd-2"))
        self.assertEqual(b2["status"], "created")
        far = api_v1.admin_match(c, who, dict(base, home="Zq One", away="Zq Two", start_utc="2026-10-03T10:00:00+00:00", provider="owner_sheets", provider_id="lg-2"))
        self.assertEqual(far["status"], "created")
        c.rollback(); c.close()


if __name__ == "__main__":
    unittest.main()
