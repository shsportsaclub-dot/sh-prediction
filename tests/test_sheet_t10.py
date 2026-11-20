"""Owner's Abu Dhabi T10 2026 'SH Complete Match Master' sheet: real header and rows copied from the sheet on 20 Nov 2026
(owner data, not synthetic). Checks codes -> full names, IST times, user-reported scores, margin in RESULT, pending/TBD rows,
picks kept as first seen, no duplicates with the T10 fixture snapshot, and no overwrite of results from another source."""
import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import test_v1 as T
from test_bridge import xlsx, Fake, set_sheets, run

SHEET = "1ydZ1gF9u8ii_qWu8fTSj2xGSnoKg0tsToMpcVzXwdZo"
HEAD = ["#", "DATE", "IST", "HOME", "VS", "AWAY", "TOSS", "WIN", "RESULT", "P.T", "T✓", "P.WIN", "W✓", "NOTES"]
ROWS = [
    ["1", "07-11-2026", "05:00 PM", "UB\n121/3 (9.4)", "VS", "YL\n120/3 (10)", "H-UB", "H-UB", "7 wickets", "—", "—", "H-UB", "✓ RIGHT", "User: chase"],
    ["2", "07-11-2026", "07:15 PM", "RDC\n109/7 (10)", "VS", "EE\n125/2 (10)", "H-RDC", "A-EE", "16 runs", "—", "—", "—", "—"],
    ["26", "18-11-2026", "07:15 PM", "UB\n98/6 (10)", "VS", "UT\n70/8 (10)", "A-UT", "H-UB", "28 runs", "H-UB", "✗ WRONG", "A-UT", "✗ WRONG", "18 Nov; Cricbuzz verified: UB won by 28 runs"],
    ["28", "19-11-2026", "05:00 PM", "UB\n99/3 (7)", "VS", "AA\n96/6 (10)", "H-UB", "H-UB", "7 wickets", "A-AA", "—", "H-UB", "✓ RIGHT", "19 Nov | result reported"],
    ["29", "19-11-2026", "07:15 PM", "YL\n—", "VS", "RDC\n—", "H-YL", "—", "Pending", "H-YL", "✓ RIGHT", "A-RDC", "—", "19 Nov | toss user-reported"],
    ["31", "20-11-2026", "07:00 PM", "TBD\n—", "VS", "TBD\n—", "—", "—", "Qualifier", "—", "—", "—", "—", "20 Nov"],
]


class AbuDhabiT10Sheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_real_sheet_layout(self):
        import t10_seed
        print(t10_seed.seed(T.db))                     # the fixture snapshot already holds matches 28-30
        lg = {"league": "Abu Dhabi T10", "sheet_id": SHEET, "format": "T10", "gender": "men", "tz": "+04:00"}
        book = {"v": xlsx({"SH Complete Match Master": [HEAD] + ROWS})}
        set_sheets([lg])
        r = run("owner_sheets_sync", Fake({SHEET: lambda: book["v"]}))
        k = r["summary"]["leagues"]["Abu Dhabi T10"]
        self.assertEqual((k["rows"], k["placeholder"], k["scores"], k["picks"]), (6, 1, 8, 4), k)   # TBD final row skipped
        c = T.db()
        q = lambda no: c.execute("""SELECT m.*, h.name AS hn, a.name AS an, cp.name AS comp FROM matches m JOIN teams h ON h.id=m.home_team_id
                                    JOIN teams a ON a.id=m.away_team_id JOIN competitions cp ON cp.id=m.competition_id
                                    WHERE cp.name='Abu Dhabi T10 2026' AND m.match_no=?""", (no,)).fetchall()
        m1 = q("1")
        self.assertEqual(len(m1), 1)
        self.assertEqual((m1[0]["hn"], m1[0]["an"], m1[0]["start_utc"]), ("UAE Bulls", "Yas Lions", "2026-11-07T11:30:00+00:00"))   # 5 PM IST
        self.assertFalse(c.execute("SELECT 1 FROM teams WHERE name LIKE '%/%'").fetchone())                 # no score text inside team names
        self.assertEqual(len(q("28")), 1)                                                                  # snapshot + sheet = one match
        res = c.execute("SELECT * FROM match_results WHERE match_id=?", (m1[0]["id"],)).fetchone()
        self.assertEqual((res["result_type"], res["margin"]), ("win", "7 wickets"))
        sc = {x["runs"]: x["status"] for x in c.execute("SELECT * FROM reported_scores WHERE match_id=?", (m1[0]["id"],))}
        self.assertEqual(sc, {121: "USER_REPORTED", 120: "USER_REPORTED"})
        m29 = q("29")[0]
        self.assertIsNone(c.execute("SELECT 1 FROM match_results WHERE match_id=?", (m29["id"],)).fetchone())   # Pending stays pending
        self.assertNotEqual(m29["status"], "completed")
        p26 = c.execute("SELECT * FROM sheet_picks WHERE match_id=?", (q("26")[0]["id"],)).fetchone()
        self.assertEqual((p26["toss_pick"], p26["win_pick"], p26["win_mark"]), ("H-UB", "A-UT", "✗ WRONG"))
        c.close()
        # owner edits the original winner pick later: the first pick is kept, the edit is logged
        ROWS2 = [list(r) for r in ROWS]
        ROWS2[2][11] = "H-UB"
        book["v"] = xlsx({"SH Complete Match Master": [HEAD] + ROWS2})
        run("owner_sheets_sync", Fake({SHEET: lambda: book["v"]}))
        c = T.db()
        mid26 = q("26")[0]["id"]
        self.assertEqual(c.execute("SELECT win_pick FROM sheet_picks WHERE match_id=?", (mid26,)).fetchone()[0], "A-UT")
        self.assertEqual(c.execute("SELECT old_value, new_value FROM sheet_pick_history WHERE match_id=? AND field='win_pick'", (mid26,)).fetchone()[:], ("A-UT", "H-UB"))
        # a result from another source is never overwritten by the sheet
        mid2 = q("2")[0]["id"]
        home = q("2")[0]["home_team_id"]
        c.execute("UPDATE match_results SET winner_team_id=?, source='CricketData.org' WHERE match_id=?", (home, mid2))
        c.commit(); c.close()
        ROWS3 = [list(r) for r in ROWS2]
        ROWS3[1] = ROWS3[1] + ["edited note"]
        book["v"] = xlsx({"SH Complete Match Master": [HEAD] + ROWS3})
        r = run("owner_sheets_sync", Fake({SHEET: lambda: book["v"]}))
        k = r["summary"]["leagues"]["Abu Dhabi T10"]
        self.assertTrue(any("CricketData.org" in x for x in k["conflicts"]), k)
        c = T.db()
        self.assertEqual(c.execute("SELECT winner_team_id FROM match_results WHERE match_id=?", (mid2,)).fetchone()[0], home)
        c.close()


if __name__ == "__main__":
    unittest.main()
