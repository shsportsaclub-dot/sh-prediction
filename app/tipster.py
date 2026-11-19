"""SH Tipster desk: one screen per series with every fixture, the tipster's toss and winner picks, their timing and results,
and the same rows as a sheet (the owner's league-sheet columns plus pick columns).

The sheet reaches the tipster's own Google account without any Google login on our side: a private link per tipster
(/tipster-sheet/<token>.csv) that Google Sheets reads with =IMPORTDATA(...) and refreshes by itself; .xlsx for Excel.
"""
import csv, datetime, io, json, secrets
import engine

HEAD = ["Match", "Date", "Time (UTC)", "Home", "Away", "Venue", "Toss", "Decision", "My toss pick", "Toss pick", "Winner", "Margin",
        "My winner pick", "Winner pick", "Picked at (UTC)", "Timing", "Innings-break update"]


def _expert(c, uid):
    return c.execute("SELECT id FROM expert_profiles WHERE user_id=?", (uid,)).fetchone()


def _code(c, tid, home_id):
    if not tid:
        return ""
    r = c.execute("SELECT name FROM teams WHERE id=?", (tid,)).fetchone()
    return ("H-" if tid == home_id else "A-") + (r[0] if r else "")


def series_list(c, uid):
    ex = _expert(c, uid)
    eid = ex[0] if ex else -1
    return [dict(r) for r in c.execute("""SELECT cp.id, cp.name, MIN(m.start_utc) AS first_match, MAX(m.start_utc) AS last_match,
        SUM(m.status IN ('scheduled','live')) AS open_matches, COUNT(*) AS matches,
        (SELECT COUNT(*) FROM predictions p JOIN matches m2 ON m2.id=p.match_id WHERE m2.competition_id=cp.id AND p.expert_id=? AND p.status='locked') AS my_picks
        FROM competitions cp JOIN matches m ON m.competition_id=cp.id AND m.data_origin<>'demo'
        GROUP BY cp.id HAVING open_matches>0 OR my_picks>0 ORDER BY open_matches=0, first_match LIMIT 60""", (eid,))]


def board(c, uid, competition_id, window_fn, timing_fn, now_fn):
    ex = _expert(c, uid)
    eid = ex[0] if ex else -1
    cp = c.execute("SELECT id, name FROM competitions WHERE id=?", (competition_id,)).fetchone()
    if not cp:
        return None
    out = []
    for m in c.execute("""SELECT m.*, h.name AS home_name, a.name AS away_name, v.name AS venue, t.winner_team_id AS toss_winner, t.decision AS toss_decision,
            t.verified_at AS toss_at, r.result_type, r.winner_team_id, r.margin FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
            LEFT JOIN venues v ON v.id=m.venue_id LEFT JOIN toss_results t ON t.match_id=m.id LEFT JOIN match_results r ON r.match_id=m.id
            WHERE m.competition_id=? AND m.data_origin<>'demo' ORDER BY m.start_utc, m.id""", (competition_id,)):
        picks = {}
        for p in c.execute("""SELECT p.id, p.prediction_type, p.predicted_team_id, p.created_at, p.locked_at, e.result FROM predictions p
                LEFT JOIN prediction_evaluations e ON e.prediction_id=p.id AND e.superseded_at IS NULL
                WHERE p.match_id=? AND p.expert_id=? AND p.status='locked' AND p.prediction_type IN ('toss','winner','live_winner') ORDER BY p.id""", (m["id"], eid)):
            age = (engine.pdt(now_fn()) - engine.pdt(p["created_at"])).total_seconds()
            w = timing_fn(c, m["id"], p["locked_at"])
            picks[p["prediction_type"]] = {"prediction_id": p["id"], "team_id": p["predicted_team_id"], "at": p["locked_at"], "result": p["result"] or "pending",
                                           "changeable_seconds": max(0, int(300 - age)), "timing_weight": w,
                                           "timing": "Before toss" if w >= 1 else "After toss (credit %.2f)" % w}
        win = window_fn(c, m)
        out.append({"id": m["id"], "match_no": m["match_no"], "start_utc": m["start_utc"], "status": m["status"], "venue": m["venue"],
                    "home": {"id": m["home_team_id"], "name": m["home_name"]}, "away": {"id": m["away_team_id"], "name": m["away_name"]},
                    "toss": {"team_id": m["toss_winner"], "decision": m["toss_decision"], "at": m["toss_at"]} if m["toss_winner"] else None,
                    "result": {"type": m["result_type"], "winner_id": m["winner_team_id"], "margin": m["margin"]} if m["result_type"] else None,
                    "window": win, "picks": picks,
                    "can_pick_toss": win["pre_match"] == "open", "can_pick_winner": win["pre_match"] in ("open", "post_toss")})
    settled = [p for x in out for k, p in x["picks"].items() if k != "live_winner" and p["result"] in ("correct", "incorrect")]
    return {"series": dict(cp), "matches": out,
            "summary": {"picks": sum(len([k for k in x["picks"] if k != "live_winner"]) for x in out), "settled": len(settled),
                        "correct": sum(1 for p in settled if p["result"] == "correct")},
            "rule": "Toss picks close at the toss. Winner picks close 10 minutes after the toss or at the first ball. "
                    "A pick can be changed for 5 minutes after you make it, then it locks. Picks made before the toss rank higher."}


def rows(c, uid, competition_id, window_fn, timing_fn, now_fn):
    b = board(c, uid, competition_id, window_fn, timing_fn, now_fn)
    if not b:
        return None, []
    res = {"correct": "✓", "incorrect": "✗", "pending": "pending", "void": "void", "ineligible": "late"}
    out = []
    for i, m in enumerate(b["matches"], 1):
        hid = m["home"]["id"]
        dt = m["start_utc"][:16].replace("T", " ")
        tp, wp, up = m["picks"].get("toss"), m["picks"].get("winner"), m["picks"].get("live_winner")
        first = min([p["at"] for p in (tp, wp) if p] or [""])
        timing = "; ".join(sorted({p["timing"] for p in (tp, wp) if p}))
        out.append([m["match_no"] or "%02d" % i, dt[:10], dt[11:], m["home"]["name"], m["away"]["name"], m["venue"] or "",
                    _code(c, m["toss"]["team_id"], hid) if m["toss"] else "", (m["toss"]["decision"] or "").title() if m["toss"] else "",
                    _code(c, tp["team_id"], hid) if tp else "", res.get(tp["result"], tp["result"]) if tp else "",
                    _code(c, m["result"]["winner_id"], hid) if m["result"] and m["result"]["winner_id"] else ((m["result"]["type"] or "").replace("_", " ").title() if m["result"] else ""),
                    (m["result"]["margin"] or "") if m["result"] else "",
                    _code(c, wp["team_id"], hid) if wp else "", res.get(wp["result"], wp["result"]) if wp else "",
                    first[:16].replace("T", " "), timing, _code(c, up["team_id"], hid) if up else ""])
    return b["series"], out


def to_csv(series, data):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([series["name"] if series else "SH PREDICTION"])
    w.writerow(HEAD)
    w.writerows(data)
    return buf.getvalue().encode("utf-8")


def to_xlsx(books):
    """books: [(series, rows)] -> one tab per series, owner's sheet layout (title row, blank row, header)."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for series, data in books or [({"name": "SH PREDICTION"}, [])]:
        ws = wb.create_sheet(("".join(ch for ch in series["name"] if ch not in "[]:*?/\\") or "Series")[:31])
        ws.append([series["name"]]); ws["A1"].font = Font(bold=True, size=13)
        ws.append([])
        ws.append(HEAD)
        for cell in ws[3]:
            cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="1D3FA8")
        for r in data:
            ws.append(r)
        for col, wdt in zip("ABCDEFGHIJKLMNOPQ", (7, 11, 9, 24, 24, 26, 18, 9, 18, 9, 18, 14, 18, 9, 17, 22, 18)):
            ws.column_dimensions[col].width = wdt
        ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _links_table(c):
    c.execute("""CREATE TABLE IF NOT EXISTS tipster_sheet_links(user_id INTEGER PRIMARY KEY REFERENCES users(id), token TEXT NOT NULL UNIQUE,
                 created_at TEXT NOT NULL)""")

def link(c, uid, reset=False, now_fn=None):
    _links_table(c)
    r = c.execute("SELECT token FROM tipster_sheet_links WHERE user_id=?", (uid,)).fetchone()
    if r and not reset:
        return r[0]
    tok = secrets.token_urlsafe(24)
    c.execute("INSERT INTO tipster_sheet_links(user_id,token,created_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET token=excluded.token, created_at=excluded.created_at",
              (uid, tok, now_fn() if now_fn else datetime.datetime.now(datetime.timezone.utc).isoformat()))
    return tok

def user_for_token(c, token):
    _links_table(c)
    r = c.execute("SELECT l.user_id FROM tipster_sheet_links l JOIN accounts a ON a.user_id=l.user_id WHERE l.token=? AND a.status='active'", (token,)).fetchone()
    return r[0] if r else None
