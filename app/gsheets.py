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
    "winner": ["winner", "match winner", "won", "won by team", "winning team", "result winner"],
    "result": ["result", "result type", "outcome", "status"],
    "margin": ["margin", "won by", "win margin", "winning margin"],
    "season": ["season", "year", "edition"],
}
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
        d = {f: _cell(r[i]) if i < len(r) else None for f, i in hm.items()}
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


def sync_league(c, league, xlsx, create_match, record_result, now_fn):
    """Import every tab of one league workbook. Returns counts; raises nothing for bad rows (they are reported)."""
    tabs = read_tabs(xlsx)
    k = {"tabs": 0, "rows": 0, "created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "toss": 0, "results": 0, "problems": []}
    comp = league["league"]
    for tab, rows in tabs.items():
        hm, data = parse_rows(rows)
        if not hm:
            continue
        k["tabs"] += 1
        for d in data:
            k["rows"] += 1
            day = parse_date(d.get("date"))
            if not day:
                k["skipped"] += 1
                if len(k["problems"]) < 15:
                    k["problems"].append("%s / %s: row %s v %s has no readable date" % (comp, tab, d["home"], d["away"]))
                continue
            tm, tz = parse_time(d.get("time")), league.get("tz") or TZ.get(comp)
            if tm and tz:
                start = "%sT%s%s" % (day.isoformat(), tm.strftime("%H:%M:%S"), tz)
                tnote = ""
            else:
                start = day.isoformat() + "T00:00:00+00:00"
                tnote = " Start time not supplied in the sheet." if not tm else " Local time zone not fixed for this league; time kept as date only."
            key = row_key(league["sheet_id"], tab, {**d, "date": day.isoformat()})
            raw = json.dumps({x: str(v) if v is not None else None for x, v in d.items()}, sort_keys=True)
            h = hashlib.sha256(raw.encode()).hexdigest()
            prev = c.execute("SELECT local_id, payload_hash FROM data_provider_syncs WHERE provider='owner_sheets' AND provider_entity='match' AND provider_id=?",
                             (key,)).fetchone()
            if prev and prev[1] == h:
                k["unchanged"] += 1
                continue
            season = d.get("season") or (tab if re.fullmatch(r"(19|20)\d\d(/\d\d)?", str(tab).strip()) else str(day.year))
            src = "Owner Google Sheet '%s' (tab '%s'); user-supplied, not independently verified.%s" % (comp, tab, tnote)
            if prev:
                mid = prev[0]
                c.execute("UPDATE matches SET start_utc=?, match_no=COALESCE(?,match_no), source=?, updated_at=? WHERE id=?",
                          (start, d.get("match_no"), src, now_fn(), mid))
                k["updated"] += 1
            else:
                r = create_match({"competition": comp, "season": str(season), "home": str(d["home"]), "away": str(d["away"]), "start_utc": start,
                                  "venue": d.get("venue"), "format": league.get("format", "T20"), "match_no": d.get("match_no"),
                                  "source": src, "data_origin": "imported", "provider": "owner_sheets", "provider_id": key})
                mid = r["match_id"]
                k["created" if r["status"] == "created" else "updated"] += 1
            c.execute("UPDATE data_provider_syncs SET payload_hash=?, synced_at=? WHERE provider='owner_sheets' AND provider_entity='match' AND provider_id=?",
                      (h, now_fn(), key))
            m = c.execute("SELECT home_team_id, away_team_id FROM matches WHERE id=?", (mid,)).fetchone()
            ids = {"H": m[0], "A": m[1]}
            ts = side(d.get("toss"), d["home"], d["away"])
            if ts:
                dec = str(d.get("decision") or "").strip().lower()
                dec = "bat" if dec.startswith("bat") else "bowl" if dec.startswith(("bowl", "field")) else None
                old = c.execute("SELECT winner_team_id, decision FROM toss_results WHERE match_id=?", (mid,)).fetchone()
                if not old or old[0] != ids[ts] or (dec and old[1] != dec):
                    c.execute("""INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)
                                 ON CONFLICT(match_id) DO UPDATE SET winner_team_id=excluded.winner_team_id, decision=excluded.decision,
                                 source=excluded.source, verified_at=excluded.verified_at""", (mid, ids[ts], dec, src, now_fn()))
                    k["toss"] += 1
            ws = side(d.get("winner"), d["home"], d["away"])
            rword = RESULT_WORDS.get(str(d.get("result") or d.get("winner") or "").strip().lower())
            rt = "win" if ws else rword
            if rt:
                old = c.execute("SELECT result_type, winner_team_id, margin FROM match_results WHERE match_id=?", (mid,)).fetchone()
                new = (rt, ids[ws] if ws and rt in ("win", "tie_super_over") else None, d.get("margin"))
                if rt == "tie_super_over" and not ws:
                    continue   # super over winner not stated: leave the result unrecorded rather than guess
                if not old or tuple(old) != new:
                    record_result({"match_id": mid, "result_type": rt, "winner_team_id": new[1], "margin": d.get("margin"),
                                   "source": src, "reason": "owner sheet updated" if old else None})
                    k["results"] += 1
    return k


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
