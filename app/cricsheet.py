"""Cricsheet importer — historical ball-by-ball data (free, Open Data Commons Attribution License 1.0).

* Downloads only the official zip files listed on https://cricsheet.org/downloads/ (fixed allow-list, no
  arbitrary URLs), parses the JSON match files with our own code and stores them in our own tables.
* Historical only: Cricsheet publishes a match after it has finished. It is not a live feed.
* Every imported match keeps its Cricsheet match id (data_provider_syncs) so re-imports never duplicate.
* Attribution is stored on every match (matches.source) and shown to viewers.
* All formats are imported: T20/IT20, ODI/ODM, Test and other multi-day (MDM) matches, including draws.
* Home / away: Cricsheet lists the two teams without a home flag. The listed order is kept in
  matches.listed_order and home_away_verified=0, so the first team is never presented as a verified home side.
* Corrections: each file's SHA-256 is stored; a changed file replaces that match's imported records
  (no duplicate statistics). Innings totals are cross-checked against the deliveries.
"""
import hashlib
import io
import json
import sqlite3
import os
import re
import tempfile
import threading
import time
import urllib.request
import zipfile

from schema import now

BASE = "https://cricsheet.org/downloads/"
ATTRIBUTION = "Cricsheet (cricsheet.org), Open Data Commons Attribution License 1.0"
LICENSE_URL = "https://cricsheet.org/licensing/"
ZIPS = {  # key -> (file, label); verified on cricsheet.org/downloads (19 Nov 2026)
    "recent_2": ("recently_added_2_json.zip", "Recently added — last 2 days"),
    "recent_7": ("recently_added_7_json.zip", "Recently added — last 7 days"),
    "recent_30": ("recently_added_30_json.zip", "Recently added — last 30 days"),
    "ipl": ("ipl_json.zip", "Indian Premier League"),
    "bbl": ("bbl_json.zip", "Big Bash League"),
    "wbb": ("wbb_json.zip", "Women's Big Bash League"),
    "wpl": ("wpl_json.zip", "Women's Premier League"),
    "npl": ("npl_json.zip", "Nepal Premier League"),
    "ilt": ("ilt_json.zip", "International League T20"),
    "t20s": ("t20s_json.zip", "T20 Internationals"),
    "all": ("all_json.zip", "All matches (very large)"),
}
MAX_BYTES = 400 * 1024 * 1024
MISMATCHES = []   # scorecard cross-check failures found during the current import (reported in the job log)
DOWNLOADS_PAGE = "https://cricsheet.org/downloads/"

def discover(opener=urllib.request.urlopen):
    """Read Cricsheet's official downloads page and return the JSON zip names it offers (e.g. ipl_json.zip)."""
    html = opener(urllib.request.Request(DOWNLOADS_PAGE, headers={"User-Agent": "SH-PREDICTION/1.0 (+cricsheet attribution)"}), timeout=60).read().decode("utf-8", "replace")
    names = []
    for z in re.findall(r'([a-z0-9_]+_json\.zip)', html):
        if z not in names:
            names.append(z)
    return names
LIMITED = {"T20", "IT20", "ODI", "ODM"}
BOWLER_KINDS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_A_WICKET = {"retired hurt", "retired not out"}

def download(key, opener=urllib.request.urlopen, retries=3):
    if key in ZIPS:
        fname = ZIPS[key][0]
    elif re.fullmatch(r"[a-z0-9_]+_json\.zip", key or ""):   # a file name found on the official downloads page
        fname = key
    else:
        raise ValueError("unknown Cricsheet file")
    url = BASE + fname
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SH-PREDICTION-importer (+https://sh-prediction.onrender.com)"})
            r = opener(req, timeout=120)
            fd, path = tempfile.mkstemp(suffix=".zip")
            size = 0
            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise RuntimeError("download larger than limit")
                    f.write(chunk)
            return path
        except Exception as e:  # network trouble: retry with backoff
            last = e
            time.sleep(2 * attempt)
    raise RuntimeError("download failed after %d attempts: %s" % (retries, last))

def _format(info):
    mt, overs, bpo = info.get("match_type"), info.get("overs"), info.get("balls_per_over", 6)
    if mt in ("T20", "IT20"):
        if bpo == 5:
            return "The Hundred"
        return "T10" if overs == 10 else "T20"
    if mt == "ODI":
        return "ODI"
    if mt == "ODM":
        return "List A"
    if mt == "Test":
        return "Test"
    if mt == "MDM":
        return "First-class"
    return None

def _result(info, team_ids):
    o = info.get("outcome") or {}
    method = o.get("method")
    if o.get("winner"):
        by = o.get("by") or {}
        if by.get("innings"):
            margin = "an innings and %s runs" % by.get("runs", 0)
        elif "runs" in by:
            margin = "%d runs" % by["runs"]
        elif "wickets" in by:
            margin = "%d wickets" % by["wickets"]
        else:
            margin = None
        rtype = "awarded" if method == "Awarded" else "win"
        return rtype, team_ids[o["winner"]], margin, (method if method != "Awarded" else None)
    res = o.get("result")
    if res == "tie":
        if o.get("eliminator"):
            return "tie_super_over", team_ids[o["eliminator"]], None, "Super Over"
        if o.get("bowl_out"):
            return "tie_super_over", team_ids[o["bowl_out"]], None, "Bowl-out"
        return "tie", None, None, method
    if res == "no result":
        return "no_result", None, None, method
    if res == "draw":
        return "draw", None, None, method
    return None

def parse_innings(inn):
    """Totals, ball rows and per-player figures from one Cricsheet innings."""
    runs = wkts = legal = 0
    seq = 0
    balls, bat, bowl, order = [], {}, {}, []
    for ov in inn.get("overs", []):
        legal_in_over = 0
        for d in ov.get("deliveries", []):
            seq += 1
            ex = d.get("extras") or {}
            illegal = "wides" in ex or "noballs" in ex
            if not illegal:
                legal += 1
                legal_in_over += 1
            r = d.get("runs") or {}
            runs += r.get("total", 0)
            etype = next((k for k in ("wides", "noballs", "byes", "legbyes", "penalty") if k in ex), None)
            etype = {"wides": "wide", "noballs": "no_ball", "byes": "bye", "legbyes": "leg_bye", "penalty": "penalty"}.get(etype)
            w = [x for x in d.get("wickets", []) if x.get("kind") not in NOT_A_WICKET]
            wkts += len(w)
            b = bat.setdefault(d["batter"], {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None})
            if d["batter"] not in order:
                order.append(d["batter"])
            if d.get("non_striker") and d["non_striker"] not in order:
                order.append(d["non_striker"])
                bat.setdefault(d["non_striker"], {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None})
            b["runs"] += r.get("batter", 0)
            if "wides" not in ex:
                b["balls"] += 1
            if not r.get("non_boundary"):
                b["fours"] += r.get("batter", 0) == 4
                b["sixes"] += r.get("batter", 0) == 6
            bw = bowl.setdefault(d["bowler"], {"balls": 0, "runs": 0, "wickets": 0})
            bw["balls"] += 0 if illegal else 1
            bw["runs"] += r.get("total", 0) - ex.get("byes", 0) - ex.get("legbyes", 0) - ex.get("penalty", 0)
            for x in d.get("wickets", []):
                out = bat.setdefault(x["player_out"], {"runs": 0, "balls": 0, "fours": 0, "sixes": 0, "dismissal": None})
                out["dismissal"] = x["kind"] + (" b " + d["bowler"] if x["kind"] in BOWLER_KINDS else "")
                if x["kind"] in BOWLER_KINDS:
                    bw["wickets"] += 1
            text = "%s to %s, %s" % (d["bowler"], d["batter"], ("OUT (%s)" % w[0]["kind"]) if w else ("%d run%s" % (r.get("total", 0), "" if r.get("total", 0) == 1 else "s")))
            balls.append({"over_no": int(ov["over"]), "ball_in_over": legal_in_over if not illegal else legal_in_over,
                          "seq": seq, "batter": d["batter"], "bowler": d["bowler"], "runs_bat": r.get("batter", 0),
                          "extras": r.get("extras", 0), "extra_type": etype, "is_wicket": 1 if w else 0,
                          "wicket_kind": w[0]["kind"] if w else None, "commentary": text})
    return {"runs": runs, "wickets": wkts, "legal_balls": legal, "balls": balls, "batting": bat, "batting_order": order, "bowling": bowl}

def _clear_match(c, mid):
    """Remove the imported records of one match before re-importing a corrected Cricsheet file."""
    for t in ("ball_events", "scorecards", "innings", "playing_xi", "toss_results", "match_results"):
        c.execute("DELETE FROM %s WHERE match_id=?" % t, (mid,))

def import_match(c, match_key, doc, create_match, content_hash=None):
    """Import one Cricsheet JSON document. Returns 'created', 'corrected', 'duplicate' or 'skipped:<reason>'."""
    known = c.execute("SELECT local_id, payload_hash FROM data_provider_syncs WHERE provider='cricsheet' AND provider_entity='match' AND provider_id=?",
                      (match_key,)).fetchone()
    if known and (content_hash is None or known[1] in (None, content_hash)):
        if known[1] is None and content_hash:
            c.execute("UPDATE data_provider_syncs SET payload_hash=? WHERE provider='cricsheet' AND provider_entity='match' AND provider_id=?", (content_hash, match_key))
        return "duplicate"
    info = doc.get("info") or {}
    fmt = _format(info)
    if not fmt:
        return "skipped:unsupported format %s" % info.get("match_type")
    teams = info.get("teams") or []
    if len(teams) != 2 or not info.get("dates"):
        return "skipped:missing teams or date"
    ev = info.get("event") or {}
    comp = "%s %s" % (ev.get("name") or "%s %s" % (info.get("gender", ""), info.get("match_type")), info.get("season", ""))
    gender = "women" if info.get("gender") == "female" else "men"
    if gender == "women" and "women" not in comp.lower():
        comp = comp + " (Women)"
    src = "%s — match %s. Home/away order as listed by Cricsheet." % (ATTRIBUTION, match_key)
    res = create_match({"competition": comp.strip(), "season": str(info.get("season", "")), "home": teams[0], "away": teams[1],
                        "start_utc": info["dates"][0] + "T00:00:00+00:00", "venue": info.get("venue"), "city": info.get("city"),
                        "format": fmt, "match_no": str(ev["match_number"]) if ev.get("match_number") else (ev.get("stage") or None),
                        "source": src, "data_origin": "imported", "provider": "cricsheet", "provider_id": match_key})
    mid = res["match_id"]
    outcome = "created"
    if res["status"] != "created":
        if not known:
            return "duplicate"
        _clear_match(c, mid)          # corrected source file: replace this match's imported records
        outcome = "corrected"
    c.execute("UPDATE matches SET listed_order=?, home_away_verified=0 WHERE id=?", (json.dumps(teams), mid))
    if content_hash:
        c.execute("UPDATE data_provider_syncs SET payload_hash=?, synced_at=? WHERE provider='cricsheet' AND provider_entity='match' AND provider_id=?",
                  (content_hash, now(), match_key))
    m = c.execute("SELECT home_team_id, away_team_id FROM matches WHERE id=?", (mid,)).fetchone()
    tid = {teams[0]: m[0], teams[1]: m[1]}
    c.execute("UPDATE teams SET gender=COALESCE(gender,?) WHERE id IN (?,?)", (gender, m[0], m[1]))
    people = (info.get("registry") or {}).get("people") or {}
    pids = {}

    def player(name):
        if name in pids:
            return pids[name]
        reg = people.get(name)
        row = c.execute("SELECT local_id FROM data_provider_syncs WHERE provider='cricsheet' AND provider_entity='player' AND provider_id=?", (reg,)).fetchone() if reg else None
        if row:
            pids[name] = row[0]
        else:
            # never merge players by name: a name without a Cricsheet registry ID gets its own unverified record
            c.execute("INSERT INTO players(name, identity_status) VALUES(?,?)", (name, "cricsheet_registry" if reg else "unverified"))
            pids[name] = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            if reg:
                c.execute("INSERT INTO data_provider_syncs(provider,provider_entity,provider_id,local_table,local_id,synced_at) VALUES('cricsheet','player',?,'players',?,?)",
                          (reg, pids[name], now()))
        return pids[name]

    for team, names in (info.get("players") or {}).items():
        if team in tid:
            for i, n in enumerate(names, 1):
                c.execute("INSERT OR IGNORE INTO playing_xi(match_id,team_id,player_id,batting_order) VALUES(?,?,?,?)", (mid, tid[team], player(n), i))
    toss = info.get("toss") or {}
    if toss.get("winner") in tid:
        c.execute("INSERT OR IGNORE INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)",
                  (mid, tid[toss["winner"]], "bat" if toss.get("decision") == "bat" else "bowl", src, now()))
    bpo = info.get("balls_per_over", 6)
    for n, inn in enumerate(doc.get("innings") or [], 1):
        if inn.get("team") not in tid or inn.get("forfeited"):
            continue
        p = parse_innings(inn)
        bat_sum = sum(b["runs_bat"] + b["extras"] for b in p["balls"])
        if bat_sum != p["runs"]:
            MISMATCHES.append("%s innings %d: deliveries %d vs total %d" % (match_key, n, bat_sum, p["runs"]))
        target = (inn.get("target") or {}).get("runs")
        max_balls = int(((inn.get("target") or {}).get("overs") or info.get("overs") or 0) * bpo) or None
        c.execute("""INSERT INTO innings(match_id,innings_no,batting_team_id,runs,wickets,legal_balls,target,max_balls,is_super_over,completed)
                     VALUES(?,?,?,?,?,?,?,?,?,1)""", (mid, n, tid[inn["team"]], p["runs"], p["wickets"], p["legal_balls"], target, max_balls,
                                                       1 if inn.get("super_over") else 0))
        c.executemany("""INSERT INTO ball_events(match_id,innings_no,over_no,ball_in_over,seq,batter_id,bowler_id,runs_bat,extras,extra_type,is_wicket,
                         wicket_kind,commentary,source,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      [(mid, n, b["over_no"], b["ball_in_over"], b["seq"], player(b["batter"]), player(b["bowler"]), b["runs_bat"], b["extras"],
                        b["extra_type"], b["is_wicket"], b["wicket_kind"], b["commentary"], "cricsheet", now()) for b in p["balls"]])
        for name in p["batting_order"]:
            s = p["batting"][name]
            c.execute("INSERT OR IGNORE INTO scorecards(match_id,innings_no,player_id,runs,balls,fours,sixes,dismissal) VALUES(?,?,?,?,?,?,?,?)",
                      (mid, n, player(name), s["runs"], s["balls"], s["fours"], s["sixes"], s["dismissal"] or "not out"))
        for name, s in p["bowling"].items():
            pid = player(name)
            ov = "%d.%d" % divmod(s["balls"], bpo) if bpo == 6 else str(s["balls"]) + " balls"
            if c.execute("SELECT 1 FROM scorecards WHERE match_id=? AND innings_no=? AND player_id=?", (mid, n, pid)).fetchone():
                c.execute("UPDATE scorecards SET overs_bowled=?,runs_conceded=?,wickets=? WHERE match_id=? AND innings_no=? AND player_id=?",
                          (ov, s["runs"], s["wickets"], mid, n, pid))
            else:
                c.execute("INSERT INTO scorecards(match_id,innings_no,player_id,overs_bowled,runs_conceded,wickets) VALUES(?,?,?,?,?,?)",
                          (mid, n, pid, ov, s["runs"], s["wickets"]))
    r = _result(info, tid)
    if r:
        rtype, winner, margin, method = r
        c.execute("INSERT OR IGNORE INTO match_results(match_id,result_type,winner_team_id,margin,method,source,verified_at) VALUES(?,?,?,?,?,?,?)",
                  (mid, rtype, winner, margin, method, src, now()))
        c.execute("UPDATE matches SET status=? WHERE id=?", ({"no_result": "no_result"}.get(rtype, "completed"), mid))
    else:
        c.execute("UPDATE matches SET status='completed' WHERE id=?", (mid,))
    return outcome

def import_zip(c, path, create_match, limit=None, progress=None, commit_every=50):
    """Import every JSON match file in a Cricsheet zip. Each match is atomic (savepoint)."""
    counts = {"created": 0, "corrected": 0, "duplicate": 0, "skipped": 0, "errors": 0, "error_samples": []}
    del MISMATCHES[:]
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.endswith(".json"))
        c.commit()
        for i, n in enumerate(names[:limit] if limit else names, 1):
            key = os.path.splitext(os.path.basename(n))[0]
            # one short write transaction per match: BEGIN IMMEDIATE waits for other writers (busy timeout)
            # instead of failing when a read transaction has to upgrade; retried if the database stays busy
            for attempt in range(5):
                try:
                    c.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as e:
                    if "locked" in str(e) and attempt < 4:
                        time.sleep(0.5 * (attempt + 1)); continue
                    raise
                try:
                    raw = z.read(n)
                    doc = json.loads(raw)
                    out = import_match(c, key, doc, create_match, hashlib.sha256(raw).hexdigest())
                    c.commit()
                    counts[out if out in ("created", "corrected", "duplicate") else "skipped"] += 1
                except sqlite3.OperationalError as e:
                    c.rollback()
                    if "locked" in str(e) and attempt < 4:
                        time.sleep(0.5 * (attempt + 1)); continue
                    counts["errors"] += 1
                    if len(counts["error_samples"]) < 10:
                        counts["error_samples"].append("%s: %s" % (key, e))
                except Exception as e:
                    c.rollback()
                    counts["errors"] += 1
                    if len(counts["error_samples"]) < 10:
                        counts["error_samples"].append("%s: %s" % (key, e))
                break
            if progress and i % commit_every == 0:
                progress(i, len(names), counts)
    c.commit()
    counts["scorecard_mismatches"] = list(MISMATCHES[:20])
    return counts

def rebuild_player_statistics(c):
    """Career figures per format from our own stored scorecards (imported + entered)."""
    rows = c.execute("""SELECT s.player_id, m.format, COUNT(DISTINCT s.match_id) AS matches, SUM(COALESCE(s.runs,0)) AS runs,
                        SUM(COALESCE(s.balls,0)) AS balls, SUM(CASE WHEN s.dismissal IS NOT NULL AND s.dismissal NOT IN ('not out','retired hurt','retired not out') THEN 1 ELSE 0 END) AS outs,
                        SUM(COALESCE(s.wickets,0)) AS wkts, SUM(COALESCE(s.runs_conceded,0)) AS conceded,
                        SUM(CASE WHEN s.overs_bowled LIKE '%.%' THEN CAST(substr(s.overs_bowled,1,instr(s.overs_bowled,'.')-1) AS INTEGER)*6
                                 + CAST(substr(s.overs_bowled,instr(s.overs_bowled,'.')+1) AS INTEGER) ELSE 0 END) AS bowled
                        FROM scorecards s JOIN matches m ON m.id=s.match_id WHERE m.data_origin<>'demo' GROUP BY s.player_id, m.format""").fetchall()
    for r in rows:
        c.execute("""INSERT INTO player_statistics(player_id,format,matches,runs,batting_avg,strike_rate,wickets,economy,updated_at) VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(player_id,format) DO UPDATE SET matches=excluded.matches,runs=excluded.runs,batting_avg=excluded.batting_avg,
                     strike_rate=excluded.strike_rate,wickets=excluded.wickets,economy=excluded.economy,updated_at=excluded.updated_at""",
                  (r["player_id"], r["format"], r["matches"], r["runs"], round(r["runs"] / r["outs"], 2) if r["outs"] else None,
                   round(100 * r["runs"] / r["balls"], 2) if r["balls"] else None, r["wkts"], round(6 * r["conceded"] / r["bowled"], 2) if r["bowled"] else None, now()))
    # roles from what players actually did (only when an admin has not set one)
    c.execute("""UPDATE players SET role=CASE WHEN (SELECT SUM(wickets) FROM player_statistics ps WHERE ps.player_id=players.id) >= 5
                 AND (SELECT SUM(runs) FROM player_statistics ps WHERE ps.player_id=players.id) >= 150 THEN 'all_rounder'
                 WHEN (SELECT SUM(wickets) FROM player_statistics ps WHERE ps.player_id=players.id) >= 5 THEN 'bowler' ELSE 'batter' END
                 WHERE role IS NULL AND id IN (SELECT player_id FROM player_statistics)""")
    c.commit()
    return {"player_format_rows": len(rows)}

# ------------------------------------------------------------------ background job (imports can take minutes)
_jobs_lock = threading.Lock()
_running = {}

def start_job(db_fn, key, create_match_factory, limit=None, opener=None):
    with _jobs_lock:
        if _running.get("cricsheet"):
            raise RuntimeError("a Cricsheet import is already running")
        _running["cricsheet"] = True
    c = db_fn()
    c.execute("INSERT INTO data_sync_runs(provider,started_at,status) VALUES('cricsheet',?,'running')", (now(),))
    run_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit(); c.close()

    def work():
        conn = db_fn()
        attempts, err, counts = 1, None, None
        try:
            path = download(key, opener=opener) if opener else download(key)
            try:
                def progress(i, total, k):
                    conn.execute("UPDATE data_sync_runs SET created=?,duplicates=?,rejected=?,error=? WHERE id=?",
                                 (k["created"], k["duplicate"], k["skipped"] + k["errors"], "%d of %d files" % (i, total), run_id))
                    conn.commit()
                counts = import_zip(conn, path, create_match_factory(conn), limit=limit, progress=progress)
                rebuild_player_statistics(conn)
            finally:
                os.remove(path)
        except Exception as e:
            err = str(e)
        status = "ok" if counts and not err else "failed"
        conn.execute("UPDATE data_sync_runs SET finished_at=?,status=?,attempts=?,created=?,duplicates=?,rejected=?,error=? WHERE id=?",
                     (now(), status, attempts, (counts or {}).get("created", 0), (counts or {}).get("duplicate", 0),
                      (counts or {}).get("skipped", 0) + (counts or {}).get("errors", 0),
                      err or ("; ".join(counts["error_samples"]) if counts and counts["error_samples"] else None), run_id))
        conn.execute("UPDATE data_providers SET last_sync_at=?,last_status=?,last_error=? WHERE name='cricsheet'", (now(), status, err))
        conn.commit(); conn.close()
        with _jobs_lock:
            _running.pop("cricsheet", None)

    t = threading.Thread(target=work, daemon=True, name="cricsheet-import")
    t.start()
    return {"run_id": run_id, "status": "running", "file": ZIPS[key][0] if key in ZIPS else key, "attribution": ATTRIBUTION}, t
