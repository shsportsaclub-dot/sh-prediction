"""Owner Google Sheets adapter (free, no API key).

Each league spreadsheet is downloaded as .xlsx through Google's export link, which works for sheets shared as
"Anyone with the link: Viewer". Every tab is read; the header row is found automatically from the column
names (Match, Date, Time, Home, Away, Venue, Toss, Decision, Winner, Result, Margin, Season...).
Values are taken exactly as written: blank cells stay unknown, nothing is filled in or guessed.
Stable IDs: owner_sheets:<sheet id>:<tab>:<match number> (or date+teams when there is no match number).
A changed row (new toss, result correction, new date) updates the same match; predictions are re-settled.
"""
import datetime
import hashlib
import io
import json
import re
import urllib.request

EXPORT = "https://docs.google.com/spreadsheets/d/%s/export?format=xlsx"
UA = {"User-Agent": "SH-PREDICTION-sheets-sync/1.0"}

ALIASES = {
    "match_no": ["match", "match no", "match no.", "match number", "match #", "no", "no.", "#", "s.no", "sno", "m.no", "mno", "game"],
    "date": ["date", "match date", "day/date"],
    "time": ["time", "start time", "time (ist)", "ist", "start", "local time", "time (local)", "time (gst)", "time (utc)"],
    "home": ["home", "home team", "team 1", "team a", "team1", "teama", "h"],
    "away": ["away", "away team", "team 2", "team b", "team2", "teamb", "a"],
    "venue": ["venue", "ground", "stadium", "location"],
    "toss": ["toss", "toss winner", "toss won by", "toss result"],
    "decision": ["toss decision", "decision", "elected", "elected to", "choice"],
    "winner": ["winner", "win", "match winner", "won", "won by team", "winning team", "result winner"],
    "result": ["result", "result type", "outcome", "status"],
    "margin": ["margin", "won by", "win margin", "winning margin"],
    "season": ["season", "year", "edition"],
    "pick_toss": ["p.t", "pt", "predicted toss", "toss pick", "my toss"],
    "pick_toss_mark": ["t✓", "t ✓", "toss ✓", "toss check"],
    "pick_win": ["p.win", "pwin", "p win", "predicted winner", "winner pick", "my winner"],
    "pick_win_mark": ["w✓", "w ✓", "win ✓", "winner check"],
    "notes": ["notes", "note", "remarks", "comment", "comments"],
}
# Extra facts per owner sheet that the sheet itself does not carry: the season's competition name and the team codes it uses.
# Codes are the owner's abbreviations; full names match the SH fixture snapshot (app/data/abu_dhabi_t10_2026_11_19_prematch.json).
SHEET_EXTRAS = {
    "1ydZ1gF9u8ii_qWu8fTSj2xGSnoKg0tsToMpcVzXwdZo": {
        "competition": "Abu Dhabi T10 2026",
        "codes": {"UB": "UAE Bulls", "YL": "Yas Lions", "RDC": "Royal Desert Champions", "EE": "Emirates Eagles", "UT": "United Tigers", "AA": "Arabian Aces"}},
    # WBBL: names as the live provider spells them, so sheet rows and live matches land on the same SH match
    "1afb5WkqGQs7u-PZXnHIahQOQmFnbpl10LAbpZIfs_U4": {
        "competition": "Womens Big Bash League 2026",
        "codes": {"AS": "Adelaide Strikers Women", "BH": "Brisbane Heat Women", "HH": "Hobart Hurricanes Women", "MR": "Melbourne Renegades Women",
                  "MS": "Melbourne Stars Women", "PS": "Perth Scorchers Women", "SS": "Sydney Sixers Women", "ST": "Sydney Thunder Women"}},
    "1i4YlNzCEeyqwAOpLXkxVYP3Cbl7561TmmmHhwr8Tz_8": {
        "codes": {"SR": "Sudurpaschim Royals", "LL": "Lumbini Lions", "CR": "Chitwan Rhinos", "BK": "Biratnagar Kings", "KY": "Karnali Yaks",
                  "JB": "Janakpur Bolts", "PA": "Pokhara Avengers", "KG": "Kathmandu Gorkhas"}},
    "1U3OlRR7HSGGLm7zXKr71c2V0lJV311Thai0n1U25_D0": {
        "codes": {"AS": "Adelaide Strikers", "BH": "Brisbane Heat", "HH": "Hobart Hurricanes", "MR": "Melbourne Renegades",
                  "MS": "Melbourne Stars", "PS": "Perth Scorchers", "SS": "Sydney Sixers", "ST": "Sydney Thunder"}},
    "1dI9hLDwJq6J1bXapXI3nLYdsp7k2zvghXmMal7FKocg": {
        "codes": {"ADKR": "Abu Dhabi Knight Riders", "DC": "Dubai Capitals", "DV": "Desert Vipers", "GG": "Gulf Giants",
                  "MIE": "MI Emirates", "SW": "Sharjah Warriorz"}},
    "1SX9sK5xvkt-t4EQVc8_3Ns6iJITmvXqijqJ6AW017AI": {
        "codes": {"DSG": "Durban's Super Giants", "JSK": "Joburg Super Kings", "MICT": "MI Cape Town", "PR": "Paarl Royals",
                  "PC": "Pretoria Capitals", "SEC": "Sunrisers Eastern Cape"}},
}
SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")
HEADER_TZ = {"ist": "+05:30", "time (ist)": "+05:30", "gst": "+04:00", "time (gst)": "+04:00", "utc": "+00:00", "time (utc)": "+00:00"}
MARGIN_RE = re.compile(r"^\s*(\d+)\s*(runs?|wkts?|wickets?)\s*$", re.I)
SCORE_RE = re.compile(r"^(\d{1,3})\s*[/-]\s*(\d{1,2})\s*(?:\((\d{1,3}(?:\.\d)?)\))?$")
PLACEHOLDER_TEAMS = {"tbd", "tba", "tbc", "—", "-", "?"}


def split_team_cell(v, codes=None):
    """'UB\n121/3 (9.4)' -> ('UAE Bulls', {'runs':121,'wickets':3,'overs':'9.4'}). The score line is user-reported, never verified."""
    lines = [x.strip() for x in str(v or "").splitlines() if x.strip()]
    if not lines:
        return None, None
    name = lines[0]
    name = (codes or {}).get(name.upper(), name)
    score = None
    for ln in lines[1:]:
        m = SCORE_RE.match(ln)
        if m:
            score = {"runs": int(m.group(1)), "wickets": int(m.group(2)), "overs": m.group(3)}
    return name, score
TZ = {"Indian Premier League": "+05:30", "Women's Premier League": "+05:30", "Abu Dhabi T10": "+04:00",
      "Nepal Premier League": "+05:45", "Big Bash League": None, "Women's Big Bash League": None}   # Australia: several time zones


class SheetError(Exception):
    pass


def norm(h):
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def header_map(row):
    m = {}
    cells = [norm(x) for x in row]
    for field, names in ALIASES.items():
        for i, cell in enumerate(cells):
            if cell in names and i not in m.values():
                m[field] = i
                break
    if m and "time" in m:
        m["_tz"] = HEADER_TZ.get(cells[m["time"]])
    return m if "home" in m and "away" in m else None


def fetch_xlsx(sheet_id, opener=urllib.request.urlopen):
    try:
        r = opener(urllib.request.Request(EXPORT % sheet_id, headers=UA), timeout=60)
        data = r.read()
    except Exception as e:
        raise SheetError("could not download sheet %s: %s (is it shared as 'Anyone with the link: Viewer'?)" % (sheet_id, e))
    if not data.startswith(b"PK"):
        raise SheetError("sheet %s is not shared publicly (Google returned a sign-in page). Share it as 'Anyone with the link: Viewer'." % sheet_id)
    return data


def read_tabs(xlsx_bytes):
    try:
        import openpyxl
    except ImportError:          # plain Python runtime without openpyxl: use the built-in reader
        return read_tabs_stdlib(xlsx_bytes)
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = [list(r) for r in ws.iter_rows(values_only=True)]
    return out


def read_tabs_stdlib(xlsx_bytes):
    """Minimal .xlsx reader (zip + XML): values only. Numbers stay numbers; parse_date/parse_time read Excel serials."""
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", ns):
        target = rels[sh.get("{%s}id" % ns["r"])].lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(path)).iter("{%s}row" % ns["m"]):
            cells = {}
            for cel in row.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", cel.get("r", "A")).group(1)
                col = 0
                for ch in ref:
                    col = col * 26 + ord(ch) - 64
                t, v = cel.get("t"), cel.find("m:v", ns)
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in cel.iter("{%s}t" % ns["m"]))
                elif v is not None and v.text is not None:
                    try:
                        f = float(v.text)
                        val = int(f) if f.is_integer() else f
                    except ValueError:
                        val = v.text
                else:
                    val = None
                cells[col - 1] = val
            rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
        out[sh.get("name")] = rows
    return out


def _cell(v):
    if v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v
    if isinstance(v, float) and 0 <= v < 1:
        return v                       # Excel time fraction (built-in reader)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000:
        return v                       # Excel serial date (built-in reader)
    s = str(v).strip()
    return s or None


def parse_rows(rows):
    """Find the header row and return the data rows as dicts of raw values. Rows without both teams are skipped."""
    for hi, row in enumerate(rows[:15]):
        hm = header_map(row)
        if hm:
            break
    else:
        return None, []
    out = []
    for r in rows[hi + 1:]:
        d = {f: _cell(r[i]) if i < len(r) else None for f, i in hm.items() if not f.startswith("_")}
        if d.get("home") and d.get("away"):
            out.append(d)
    return hm, out


DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%a, %d %b %Y", "%d-%b-%Y", "%d-%b-%y")


EXCEL_EPOCH = datetime.datetime(1899, 12, 30)


def parse_date(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000:   # Excel serial date
        return (EXCEL_EPOCH + datetime.timedelta(days=float(v))).date()
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if not v:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    for f in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def parse_time(v):
    if isinstance(v, float) and 0 <= v < 1:                                              # Excel time fraction
        secs = round(v * 86400)
        return datetime.time(secs // 3600, secs % 3600 // 60)
    if isinstance(v, datetime.time):
        return v
    if isinstance(v, datetime.datetime):
        return v.time()
    if not v:
        return None
    s = str(v).strip().upper().replace(".", ":")
    for f in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, f).time()
        except ValueError:
            pass
    return None


def side(v, home, away):
    """Resolve a toss/winner cell to 'H' or 'A'. Accepts H-UB / A-EE codes, H / A, or the team's name or code."""
    if not v:
        return None
    s = str(v).strip()
    m = re.fullmatch(r"([HAha])\s*[-:]\s*(.+)", s)
    if m:
        return m.group(1).upper()
    if s.upper() in ("H", "HOME"):
        return "H"
    if s.upper() in ("A", "AWAY"):
        return "A"
    if s.lower() == str(home).lower():
        return "H"
    if s.lower() == str(away).lower():
        return "A"
    return None


RESULT_WORDS = {"tie": "tie", "tied": "tie", "no result": "no_result", "nr": "no_result", "abandoned": "abandoned",
                "cancelled": "canceled", "canceled": "canceled", "draw": "draw", "drawn": "draw", "super over": "tie_super_over"}


def row_key(sheet_id, tab, d):
    if d.get("match_no"):
        return "%s:%s:%s" % (sheet_id, tab, str(d["match_no"]).strip())
    return "%s:%s:%s:%s:%s" % (sheet_id, tab, d.get("date"), d["home"], d["away"])


def _sheet_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS reported_scores(match_id INTEGER NOT NULL REFERENCES matches(id), team_id INTEGER NOT NULL REFERENCES teams(id),
                 runs INTEGER NOT NULL, wickets INTEGER NOT NULL, overs TEXT, status TEXT NOT NULL DEFAULT 'USER_REPORTED', source TEXT NOT NULL,
                 synced_at TEXT NOT NULL, PRIMARY KEY(match_id, team_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS sheet_picks(match_id INTEGER PRIMARY KEY REFERENCES matches(id), toss_pick TEXT, win_pick TEXT,
                 toss_mark TEXT, win_mark TEXT, notes TEXT, source TEXT NOT NULL, first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS sheet_pick_history(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id), field TEXT NOT NULL,
                 old_value TEXT, new_value TEXT, changed_at TEXT NOT NULL)""")


def _owned(source):
    return str(source or "").startswith("Owner Google Sheet")


def sync_league(c, league, xlsx, create_match, record_result, now_fn, dry_run=False):
    """Import every tab of one league workbook. Returns counts and a reconciliation report; bad rows are reported, never guessed.
    Owner picks (P.T / P.WIN) are kept as first seen; later edits are logged in sheet_pick_history. Results or tosses that came
    from another source (e.g. CricketData) are never overwritten: the difference is reported as a conflict."""
    _sheet_tables(c)
    tabs = read_tabs(xlsx)
    k = {"tabs": 0, "rows": 0, "created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "placeholder": 0, "toss": 0, "results": 0,
         "scores": 0, "picks": 0, "conflicts": [], "problems": [], "dry_run": bool(dry_run)}
    extras = SHEET_EXTRAS.get(league.get("sheet_id"), {})
    comp = league.get("competition") or extras.get("competition") or league["league"]
    codes = dict(extras.get("codes") or {}, **(league.get("codes") or {}))
    for tab, rows in tabs.items():
        hm, data = parse_rows(rows)
        if not hm:
            continue
        k["tabs"] += 1
        for d in data:
            k["rows"] += 1
            home, hscore = split_team_cell(d["home"], codes)
            away, ascore = split_team_cell(d["away"], codes)
            if not home or not away or home.lower() in PLACEHOLDER_TEAMS or away.lower() in PLACEHOLDER_TEAMS:
                k["placeholder"] += 1          # e.g. Qualifier / Final with teams still TBD
                continue
            day = parse_date(d.get("date"))
            if not day:
                k["skipped"] += 1
                if len(k["problems"]) < 15:
                    k["problems"].append("%s / %s: row %s v %s has no readable date" % (comp, tab, home, away))
                continue
            tm, tz = parse_time(d.get("time")), hm.get("_tz") or league.get("tz") or TZ.get(league["league"])
            if tm and tz:
                start = "%sT%s%s" % (day.isoformat(), tm.strftime("%H:%M:%S"), tz)
                tnote = ""
            else:
                start = day.isoformat() + "T00:00:00+00:00"
                tnote = " Start time not supplied in the sheet." if not tm else " Local time zone not fixed for this league; time kept as date only."
            key = row_key(league["sheet_id"], tab, {**d, "home": home, "away": away, "date": day.isoformat()})
            raw = json.dumps(dict({x: str(v) if v is not None else None for x, v in d.items()}, _codes=codes or None), sort_keys=True)
            h = hashlib.sha256(raw.encode()).hexdigest()
            prev = c.execute("SELECT local_id, payload_hash FROM data_provider_syncs WHERE provider='owner_sheets' AND provider_entity='match' AND provider_id=?",
                             (key,)).fetchone()
            if prev and prev[1] == h:
                k["unchanged"] += 1
                continue
            if dry_run:
                k["updated" if prev else "created"] += 1
                k.setdefault("would_change", []).append("%s %s: %s v %s" % ("update" if prev else "new", d.get("match_no") or day, home, away))
                continue
            season = d.get("season") or (tab if re.fullmatch(r"(19|20)\d\d(/\d\d)?", str(tab).strip()) else str(day.year))
            src = "Owner Google Sheet '%s' (tab '%s'); user-supplied, not independently verified.%s" % (comp, tab, tnote)
            if prev:
                mid = prev[0]
                c.execute("UPDATE matches SET start_utc=?, match_no=COALESCE(?,match_no), updated_at=? WHERE id=?",
                          (start, d.get("match_no"), now_fn(), mid))
                _rename_teams(c, mid, home, away)
                k["updated"] += 1
            else:
                r = create_match({"competition": comp, "season": str(season), "home": home, "away": away, "start_utc": start,
                                  "venue": d.get("venue"), "format": league.get("format", "T20"), "match_no": d.get("match_no"),
                                  "source": src, "data_origin": "imported", "provider": "owner_sheets", "provider_id": key})
                if r.get("status") == "rejected":
                    k["skipped"] += 1
                    k["problems"].append("%s: %s v %s rejected: %s" % (comp, home, away, r.get("error")))
                    continue
                mid = r["match_id"]
                k["created" if r["status"] == "created" else "updated"] += 1
            c.execute("UPDATE data_provider_syncs SET payload_hash=?, synced_at=? WHERE provider='owner_sheets' AND provider_entity='match' AND provider_id=?",
                      (h, now_fn(), key))
            m = c.execute("SELECT home_team_id, away_team_id, status FROM matches WHERE id=?", (mid,)).fetchone()
            ids = {"H": m[0], "A": m[1]}
            label = "match %s %s v %s" % (d.get("match_no") or "?", home, away)
            ts = side(d.get("toss"), home, away)
            if ts:
                dec = str(d.get("decision") or "").strip().lower()
                dec = "bat" if dec.startswith("bat") else "bowl" if dec.startswith(("bowl", "field")) else None
                old = c.execute("SELECT winner_team_id, decision, source FROM toss_results WHERE match_id=?", (mid,)).fetchone()
                if old and not _owned(old[2]) and old[0] != ids[ts]:
                    k["conflicts"].append("%s: toss %s in sheet, %s from %s (kept)" % (label, d.get("toss"), old[0], old[2]))
                elif not old or old[0] != ids[ts] or (dec and old[1] != dec):
                    c.execute("""INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)
                                 ON CONFLICT(match_id) DO UPDATE SET winner_team_id=excluded.winner_team_id, decision=excluded.decision,
                                 source=excluded.source, verified_at=excluded.verified_at""", (mid, ids[ts], dec, src, now_fn()))
                    k["toss"] += 1
            # user-reported innings totals from the team cells (shown as reported, never as a verified scorecard)
            for code, sc in (("H", hscore), ("A", ascore)):
                if sc:
                    old = c.execute("SELECT runs, wickets, overs FROM reported_scores WHERE match_id=? AND team_id=?", (mid, ids[code])).fetchone()
                    if not old or tuple(old) != (sc["runs"], sc["wickets"], sc["overs"]):
                        c.execute("""INSERT INTO reported_scores(match_id,team_id,runs,wickets,overs,status,source,synced_at) VALUES(?,?,?,?,?,'USER_REPORTED',?,?)
                                     ON CONFLICT(match_id,team_id) DO UPDATE SET runs=excluded.runs, wickets=excluded.wickets, overs=excluded.overs,
                                     source=excluded.source, synced_at=excluded.synced_at""", (mid, ids[code], sc["runs"], sc["wickets"], sc["overs"], src, now_fn()))
                        k["scores"] += 1
            # owner's original picks: first value kept, every later edit logged
            pick = {"toss_pick": d.get("pick_toss"), "win_pick": d.get("pick_win"), "toss_mark": d.get("pick_toss_mark"),
                    "win_mark": d.get("pick_win_mark"), "notes": d.get("notes")}
            pick = {f: (None if str(v or "").strip() in ("", "—", "-") else str(v).strip()) for f, v in pick.items()}
            if any(pick.values()):
                old = c.execute("SELECT * FROM sheet_picks WHERE match_id=?", (mid,)).fetchone()
                if not old:
                    c.execute("INSERT INTO sheet_picks(match_id,toss_pick,win_pick,toss_mark,win_mark,notes,source,first_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                              (mid, pick["toss_pick"], pick["win_pick"], pick["toss_mark"], pick["win_mark"], pick["notes"], src, now_fn(), now_fn()))
                    k["picks"] += 1
                else:
                    for f, v in pick.items():
                        if old[f] != v:
                            c.execute("INSERT INTO sheet_pick_history(match_id,field,old_value,new_value,changed_at) VALUES(?,?,?,?,?)", (mid, f, old[f], v, now_fn()))
                            if f in ("toss_pick", "win_pick") and old[f]:
                                continue        # the original pick is never replaced
                            c.execute("UPDATE sheet_picks SET %s=?, updated_at=? WHERE match_id=?" % f, (v, now_fn(), mid))
            # result: WIN column = winner code; RESULT column may hold the margin ("7 wickets") or a word (Pending / No result / Tie)
            res_cell = str(d.get("result") or "").strip()
            margin = d.get("margin") or (res_cell if MARGIN_RE.match(res_cell) else None)
            if res_cell.lower() in ("pending", "live", "upcoming", "scheduled", "tbd"):
                continue                           # never treat a pending match as completed
            ws = side(d.get("winner"), home, away)
            rword = RESULT_WORDS.get(res_cell.lower()) or RESULT_WORDS.get(str(d.get("winner") or "").strip().lower())
            rt = "win" if ws else rword
            if rt:
                if rt == "tie_super_over" and not ws:
                    continue   # super over winner not stated: leave the result unrecorded rather than guess
                old = c.execute("SELECT result_type, winner_team_id, margin, source FROM match_results WHERE match_id=?", (mid,)).fetchone()
                new = (rt, ids[ws] if ws and rt in ("win", "tie_super_over") else None, margin)
                if old and not _owned(old[3]) and (old[0], old[1]) != new[:2]:
                    k["conflicts"].append("%s: sheet says %s, %s recorded %s/%s (kept)" % (label, d.get("winner") or res_cell, old[3], old[0], old[1]))
                elif not old or tuple(old[:3]) != new:
                    record_result({"match_id": mid, "result_type": rt, "winner_team_id": new[1], "margin": margin,
                                   "source": src, "reason": "owner sheet updated" if old else None})
                    k["results"] += 1
    return k


def _rename_teams(c, mid, home, away):
    """A row first imported with bare codes ('SR') moves to the full names once the code map knows them, so the match can
    join the same fixture from CricketData. Only a code -> name change is applied; a different pairing is left alone."""
    import api_v1
    row = c.execute("SELECT h.name, a.name FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id WHERE m.id=?",
                    (mid,)).fetchone()
    if not row or (row[0], row[1]) == (home, away):
        return
    sets = {}
    for col, old, new in (("home_team_id", row[0], home), ("away_team_id", row[1], away)):
        if old != new and len(old) <= 5 and old.upper() == old:
            sets[col] = api_v1.get_or_create(c, "teams", ["name"], {"name": new})
    if sets:
        try:
            c.execute("UPDATE matches SET %s WHERE id=?" % ", ".join("%s=?" % k for k in sets), list(sets.values()) + [mid])
        except Exception:      # e.g. a uniqueness clash: keep the old names rather than lose the row
            pass


def leagues_from_index(xlsx):
    """League sheets listed in the owner's Global League Index ('Leagues' tab: League | Category | Country | ... | Sheet Link)."""
    out = []
    for tab, rows in read_tabs(xlsx).items():
        if not rows:
            continue
        head = [norm(x) for x in rows[0]]
        if "league" not in head or not any("sheet" in h and "link" in h for h in head):
            continue
        il, ilink = head.index("league"), next(i for i, h in enumerate(head) if "sheet" in h and "link" in h)
        col = lambda name: head.index(name) if name in head else None
        icat, ictry = col("category"), col("country")
        for r in rows[1:]:
            get = lambda i: str(r[i]).strip() if i is not None and i < len(r) and r[i] is not None else ""
            m = SHEET_ID_RE.search(get(ilink))
            if not get(il) or not m:
                continue
            cat = get(icat).lower()
            out.append({"league": get(il), "sheet_id": m.group(1), "format": "T10" if "t10" in get(il).lower() else "T20",
                        "gender": "women" if cat.startswith("wom") else "men", "country": get(ictry) or None, "from_index": True})
    return out


def merge_index_leagues(current, found):
    """Add index leagues whose sheet is not imported yet; existing entries and their settings are never changed."""
    have = {x.get("sheet_id") for x in current}
    added = [x for x in found if x["sheet_id"] not in have]
    return current + added, [x["league"] for x in added]


def sync_index_registry(c, xlsx, now_fn):
    """Load the League Index tabs into the competition registry as unverified entries (never as confirmed)."""
    import registry
    tabs = read_tabs(xlsx)
    k = {"competitions": 0, "countries": 0}
    for tab, rows in tabs.items():
        if not rows:
            continue
        head = [norm(x) for x in rows[0]]
        if "competition" not in " ".join(head) and "competition season" not in head and "2026 competition / season" not in head:
            continue
        col = lambda *names: next((i for i, h in enumerate(head) if h in names), None)
        ci, cc, cd, ck, cs = (col("competition", "competition season", "2026 competition / season"), col("country / region", "country/region", "region"),
                              col("division"), col("category"), col("source url", "source"))
        for r in rows[1:]:
            name = (str(r[ci]).strip() if ci is not None and ci < len(r) and r[ci] else "")
            if not name:
                continue
            ctry = str(r[cc]).strip() if cc is not None and cc < len(r) and r[cc] else None
            cid = None
            if ctry and ctry.lower() not in ("global", "asia", "europe", "africa", "americas", "east asia-pacific"):
                cid = registry.country(c, ctry)
                k["countries"] += 1
            exists = c.execute("SELECT id, verification FROM competitions WHERE name=?", (name,)).fetchone()
            if exists:
                c.execute("UPDATE competitions SET country_id=COALESCE(country_id,?), division=COALESCE(division,?), category=COALESCE(category,?), "
                          "region=COALESCE(region,?), registry_source=COALESCE(registry_source,?) WHERE id=?",
                          (cid, r[cd] if cd is not None and cd < len(r) else None, r[ck] if ck is not None and ck < len(r) else None,
                           ctry if not cid else None, "owner index: " + tab, exists[0]))
            else:
                c.execute("INSERT INTO competitions(name,category,division,country_id,region,source,data_origin,verification,registry_source) "
                          "VALUES(?,?,?,?,?,?,?,?,?)",
                          (name, r[ck] if ck is not None and ck < len(r) else None, r[cd] if cd is not None and cd < len(r) else None, cid,
                           ctry if not cid else None, (str(r[cs]) if cs is not None and cs < len(r) and r[cs] else "Owner League Index"),
                           "imported", "unverified", "owner index: " + tab))
                k["competitions"] += 1
    return k
