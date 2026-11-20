"""SH Global Cricket Registry: countries, governing boards, sources and collector schedules.

Only facts we can stand behind are seeded. Everything else starts as 'Not Researched' / 'unverified' and is
filled in by research, the owner's League Index sheet and the importers. Nothing is invented to fill gaps.
"""
import json

from schema import now

CHECKED = "2026-11-19"

# ICC membership: 111 members (12 Full + 99 Associate) after Mauritius was admitted in July 2026
# (ICC Annual Conference, Edinburgh). Full members and their national boards:
FULL_MEMBERS = [
    ("Afghanistan", "Afghanistan Cricket Board", "https://www.acb.af", "Asia", "2017"),
    ("Australia", "Cricket Australia", "https://www.cricket.com.au", "East Asia-Pacific", "1909"),
    ("Bangladesh", "Bangladesh Cricket Board", "https://www.tigercricket.com.bd", "Asia", "2000"),
    ("England", "England and Wales Cricket Board", "https://www.ecb.co.uk", "Europe", "1909"),
    ("India", "Board of Control for Cricket in India", "https://www.bcci.tv", "Asia", "1926"),
    ("Ireland", "Cricket Ireland", "https://www.cricketireland.ie", "Europe", "2017"),
    ("New Zealand", "New Zealand Cricket", "https://www.nzc.nz", "East Asia-Pacific", "1926"),
    ("Pakistan", "Pakistan Cricket Board", "https://www.pcb.com.pk", "Asia", "1953"),
    ("South Africa", "Cricket South Africa", "https://www.cricket.co.za", "Africa", "1909"),
    ("Sri Lanka", "Sri Lanka Cricket", "https://www.srilankacricket.lk", "Asia", "1981"),
    ("West Indies", "Cricket West Indies", "https://www.windiescricket.com", "Americas", "1926"),
    ("Zimbabwe", "Zimbabwe Cricket", "https://www.zimcricket.org", "Africa", "1992"),
]
# Associate members confirmed in the sources read so far; the remaining associates are added by research.
ASSOCIATES_CONFIRMED = ["Fiji", "United States of America", "Netherlands", "Papua New Guinea", "Scotland", "Nepal",
                        "United Arab Emirates", "Namibia", "Oman", "Thailand", "Canada", "Mauritius", "Timor-Leste",
                        "Cambodia", "Cote d'Ivoire", "Uzbekistan"]
ICC_NOTE = ("ICC: 111 members (12 Full, 99 Associate) as of July 2026. %d associates confirmed so far; "
            "the rest are pending research.") % len(ASSOCIATES_CONFIRMED)

SOURCES = [
    dict(key="cricsheet", name="Cricsheet", organization="Cricsheet (Stephen Rushe)", url="https://cricsheet.org",
         coverage="International Tests, ODIs, T20Is (men and women) and many leagues listed on its downloads page",
         historical=1, live=0, ball_by_ball=1, scorecard=1, commentary=0, update_frequency="New files shortly after matches finish",
         data_format="JSON (also CSV/YAML)", access_method="Official zip downloads", terms_url="https://cricsheet.org/register/",
         license="Open Data Commons Attribution License 1.0 (ODC-By)", redistribution="Allowed with attribution",
         reliability="High (curated scorecards)", adapter="implemented", permission="verified",
         note="Attribution shown on every imported match."),
    dict(key="cricketdata", name="CricketData.org API (formerly CricAPI)", organization="CricketData.org", url="https://cricketdata.org",
         coverage="International and major franchise cricket as offered by the provider", historical=0, live=1, ball_by_ball=None,
         scorecard=1, commentary=None, update_frequency="Near-live", data_format="JSON REST (api.cricapi.com/v1)",
         access_method="API key (Lifetime Free plan: 100 hits/day; paid plans from $5.99/mo for 2,000/day)",
         terms_url="https://cricketdata.org", license="Commercial API with a free plan", redistribution="Per CricketData.org terms (owner to confirm)",
         reliability="To be measured", adapter="implemented", permission="api_key",
         note="Used within a daily hit budget so the Telegram bot sharing the key keeps working."),
    dict(key="owner_sheets", name="Owner league sheets (Google Sheets)", organization="SH Sports Club", url="https://docs.google.com/spreadsheets",
         coverage="Owner-maintained leagues: IPL, Abu Dhabi T10, Nepal Premier League, WPL, Big Bash men and women",
         historical=1, live=0, ball_by_ball=0, scorecard=0, commentary=0, update_frequency="Whenever the owner edits; synced every 30 min",
         data_format="Google Sheets (CSV export)", access_method="Sheets shared as 'Anyone with the link: Viewer'",
         license="Owner data", redistribution="Owner decides", reliability="User-supplied, not independently verified",
         adapter="implemented", permission="owner", note=None),
    dict(key="sh_scoring", name="SH own scoring (Scoring Heroes / admin scorer)", organization="SH Sports Club", url=None,
         coverage="Matches scored by SH scorers", historical=1, live=1, ball_by_ball=1, scorecard=1, commentary=1,
         update_frequency="Every ball", data_format="Internal events", access_method="Authenticated scorer API",
         license="First-party", redistribution="First-party", reliability="Primary controlled source", adapter="implemented", permission="first_party", note=None),
    dict(key="icc", name="ICC official site", organization="International Cricket Council", url="https://www.icc-cricket.com",
         coverage="ICC events, fixtures and results", historical=1, live=1, ball_by_ball=None, scorecard=1, commentary=None,
         update_frequency="Live", data_format="Web pages", access_method="Website", license="Not reviewed", redistribution="Not granted",
         reliability="Official", adapter="none", permission="unverified",
         note="Reference for discovery and cross-checks only; no automated collection until permission is confirmed."),
    dict(key="cricbuzz", name="Cricbuzz", organization="Cricbuzz", url="https://www.cricbuzz.com", coverage="Worldwide", historical=1, live=1,
         ball_by_ball=1, scorecard=1, commentary=1, update_frequency="Live", data_format="Web/app", access_method="Website/app",
         license="Proprietary", redistribution="Not granted", reliability="Reference", adapter="none", permission="not_permitted",
         note="Functional reference only. Not collected or redistributed."),
    dict(key="espncricinfo", name="ESPNcricinfo", organization="ESPN", url="https://www.espncricinfo.com", coverage="Worldwide", historical=1,
         live=1, ball_by_ball=1, scorecard=1, commentary=1, update_frequency="Live", data_format="Web/app", access_method="Website/app",
         license="Proprietary", redistribution="Not granted", reliability="Reference", adapter="none", permission="not_permitted",
         note="Functional reference only. Not collected or redistributed."),
    dict(key="crex", name="CREX", organization="CREX", url="https://crex.com", coverage="Worldwide", historical=1, live=1, ball_by_ball=1,
         scorecard=1, commentary=1, update_frequency="Live", data_format="Web/app", access_method="Website/app", license="Proprietary",
         redistribution="Not granted", reliability="Reference", adapter="none", permission="not_permitted",
         note="Functional reference only. Not collected or redistributed; no APK used as a data source."),
]
for _n, _b, _u, _r, _y in FULL_MEMBERS:
    SOURCES.append(dict(key="board_" + _n.lower().replace(" ", "_"), name=_b, organization=_b, url=_u, coverage=_n + " national and domestic cricket",
                        historical=None, live=None, ball_by_ball=None, scorecard=None, commentary=None, update_frequency=None,
                        data_format="Web pages", access_method="Website", license="Not reviewed", redistribution="Not granted",
                        reliability="Official", adapter="none", permission="unverified",
                        note="Official board site: used to verify competitions; terms not yet reviewed for automated collection."))

# owner's six league sheets, from the 'Leagues' tab of "SH Predictor - Global League Index"
INDEX_SHEET = "1PQDQcCLDA4cyynzE8oNQg4Moa5E2JOGx5m6SQjV_m0I"
OWNER_SHEETS = [
    {"league": "Abu Dhabi T10", "sheet_id": "1ydZ1gF9u8ii_qWu8fTSj2xGSnoKg0tsToMpcVzXwdZo", "format": "T10", "gender": "men", "country": "United Arab Emirates", "tz": "+04:00"},
    {"league": "Nepal Premier League", "sheet_id": "1i4YlNzCEeyqwAOpLXkxVYP3Cbl7561TmmmHhwr8Tz_8", "format": "T20", "gender": "men", "country": "Nepal"},
    {"league": "Indian Premier League", "sheet_id": "184wHvt822rFGm7mToXQOnMWCS5GLAlJah1DAvgwxqyw", "format": "T20", "gender": "men", "country": "India"},
    {"league": "Women's Premier League", "sheet_id": "1vQsAGrxphn8Orb2J7L8_uGA3fsXIqQBT6ZrgnUYoV50", "format": "T20", "gender": "women", "country": "India"},
    {"league": "Big Bash League", "sheet_id": "1U3OlRR7HSGGLm7zXKr71c2V0lJV311Thai0n1U25_D0", "format": "T20", "gender": "men", "country": "Australia"},
    {"league": "Women's Big Bash League", "sheet_id": "1afb5WkqGQs7u-PZXnHIahQOQmFnbpl10LAbpZIfs_U4", "format": "T20", "gender": "women", "country": "Australia"},
]

# scheduled collectors: name -> (interval minutes, enabled, config)
JOBS = {
    "owner_sheets_sync": (30, 1, {}),
    "registry_index_sync": (1440, 1, {"sheet_id": INDEX_SHEET}),
    "cricketdata_matches": (60, 1, {"daily_budget": 60}),
    "cricketdata_live": (15, 1, {"daily_budget": 60, "max_live_matches": 3}),
    "cricsheet_recent": (1440, 1, {"files": ["recently_added_7_json.zip"]}),
    "sh_agent_snapshots": (10, 1, {"hours_ahead": 36}),
    "cricsheet_backfill": (360, 1, {"priority": ["ipl_json.zip", "wpl_json.zip", "bbl_json.zip", "wbb_json.zip", "npl_json.zip"],
                                    "skip": ["all_json.zip"], "done": []}),
}


def country(c, name, **kw):
    c.execute("INSERT OR IGNORE INTO countries(name) VALUES(?)", (name,))
    if kw:
        sets = ", ".join("%s=?" % k for k in kw)
        c.execute("UPDATE countries SET " + sets + " WHERE name=?", list(kw.values()) + [name])
    return c.execute("SELECT id FROM countries WHERE name=?", (name,)).fetchone()[0]


def seed(c):
    for n, b, u, r, y in FULL_MEMBERS:
        country(c, n, icc_status="full", icc_region=r, board_name=b, board_url=u, research_status="Partially Verified",
                research_note="ICC Full Member since %s; national board verified; domestic competitions pending research" % y, last_verified=CHECKED)
    for n in ASSOCIATES_CONFIRMED:
        country(c, n, icc_status="associate", research_status="Not Researched", research_note=ICC_NOTE)
    for s in SOURCES:
        cols = list(s.keys())
        c.execute("INSERT OR IGNORE INTO source_registry(%s, last_check) VALUES(%s, ?)" % (",".join(cols), ",".join("?" * len(cols))),
                  [s[k] for k in cols] + [CHECKED])
    for name, (mins, en, cfg) in JOBS.items():
        c.execute("INSERT OR IGNORE INTO collector_jobs(name,enabled,interval_minutes,config_json,next_run_at) VALUES(?,?,?,?,?)",
                  (name, en, mins, json.dumps(cfg), now()))
    c.execute("INSERT OR IGNORE INTO system_settings(key,value,updated_at,updated_by) VALUES('owner_sheets',?,?, 'migration')",
              (json.dumps(OWNER_SHEETS), now()))
    for name, kind in (("cricketdata", "licensed"), ("owner_sheets", "manual")):
        c.execute("INSERT OR IGNORE INTO data_providers(name,kind,enabled) VALUES(?,?,1)", (name, kind))
    # Cricsheet matches imported before this migration: their team order was never a verified home/away
    c.execute("""UPDATE matches SET home_away_verified=0 WHERE id IN
                 (SELECT local_id FROM data_provider_syncs WHERE provider='cricsheet' AND provider_entity='match')""")
