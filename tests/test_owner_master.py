"""Owner's Abu Dhabi T10 master list import and the approved Master List colour rule."""
import json, os, re, sys, unittest
sys.path.insert(0, os.path.dirname(__file__))
import test_v1 as T

class OwnerMaster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        T._migrate_once()

    def test_import_and_colours(self):
        s, r = T.call("/api/v1/admin/owner-master", {"start_utc": "2026-11-18T10:00:00+04:00", "dry_run": True}, T.A)
        self.assertEqual((s, r["matches"], r["with_result"], r["pending"]), (200, 30, 25, 5))
        self.assertEqual(T.call("/api/v1/admin/owner-master", {"dry_run": True}, T.A)[0], 400)   # dates are required, never guessed
        self.assertIn(T.call("/api/v1/admin/owner-master", {"start_utc": "2026-11-18T10:00:00+04:00"})[0], (401, 403))
        # same 30 rows with prefixed codes so the shared test database keeps the real codes free for other tests
        src = json.load(open(os.path.join(os.path.dirname(__file__), "..", "app", "data", "owner_master_abu_dhabi_t10.json")))["rows"]
        q = lambda v: None if v is None else re.sub(r"^([HA]-)?", lambda m: (m.group(1) or "") + "Q", v)
        rows = [[q(x) for x in r] for r in src]
        s, r = T.call("/api/v1/admin/owner-master", {"start_utc": "2026-11-18T10:00:00+04:00", "competition": "Abu Dhabi T10 test", "rows": rows}, T.A)
        self.assertEqual((s, r["created"], r["results_recorded"], r["toss_recorded"]), (200, 30, 25, 20), r)
        s, again = T.call("/api/v1/admin/owner-master", {"start_utc": "2026-11-18T10:00:00+04:00", "competition": "Abu Dhabi T10 test", "rows": rows}, T.A)
        self.assertEqual((again["created"], again["duplicate"], again["results_recorded"]), (0, 30, 0))   # idempotent
        comp = [x for x in T.call("/api/v1/competitions")[1]["items"] if x["name"] == "Abu Dhabi T10 test"][0]["id"]
        ml = T.call("/api/v1/admin/master-list?competition_id=%d" % comp, h=T.A)[1]["items"]
        self.assertEqual(len(ml), 30)
        cell = lambda c: None if c is None else (c["side"] + "-" + c["code"][1:], c["outcome"])
        # rows 01-05 exactly as in the approved sample: toss green if the toss winner won, red if lost
        want = [("01", "UB", "YL", ("H-UB", "won"), ("H-UB", "won")), ("02", "RDC", "EE", ("H-RDC", "lost"), ("A-EE", "won")),
                ("03", "UT", "AA", ("A-AA", "lost"), ("H-UT", "won")), ("04", "YL", "EE", ("H-YL", "won"), ("H-YL", "won")),
                ("05", "UT", "UB", ("A-UB", "lost"), ("H-UT", "won"))]
        for row, (no, h, a, toss, win) in zip(ml, want):
            self.assertEqual((row["match"], row["home"]["code"][1:], row["away"]["code"][1:], cell(row["toss"]), cell(row["winner"])), (no, h, a, toss, win))
        self.assertEqual(ml[14]["toss"], None)                       # 15: toss not supplied -> grey dash
        self.assertEqual(ml[14]["winner"]["outcome"], "won")
        self.assertTrue(all(r["toss"] is None and r["winner"] is None for r in ml[25:]))   # 26-30 pending
        # viewers never get the master list
        self.assertIn(T.call("/api/v1/admin/master-list")[0], (401, 403))

if __name__ == "__main__":
    unittest.main()
