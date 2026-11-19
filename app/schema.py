"""SH PREDICTION v1 normalized schema, versioned migrations and the legacy bridge.

Migrations are append-only: never edit an applied migration, add a new one.
Legacy tables (fixtures, predictions, outcomes, archive, odds) stay untouched and
keep serving the existing screens; bridge_legacy() mirrors them into v1 tables.
"""
import datetime
import json

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

M001 = """
CREATE TABLE IF NOT EXISTS login_sessions(token_hash TEXT PRIMARY KEY, phone TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS languages(code TEXT PRIMARY KEY, name TEXT NOT NULL, native_name TEXT NOT NULL,
  rtl INTEGER NOT NULL DEFAULT 0, ui_complete INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS countries(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, iso2 TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, phone TEXT UNIQUE, display_name TEXT,
  role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','expert','admin')), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),
  language_code TEXT NOT NULL DEFAULT 'en' REFERENCES languages(code),
  theme TEXT NOT NULL DEFAULT 'dark' CHECK(theme IN ('dark','light')),
  favorite_team_ids TEXT NOT NULL DEFAULT '[]', favorite_competition_ids TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS competitions(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT,
  division TEXT, country_id INTEGER REFERENCES countries(id), format TEXT, source TEXT,
  data_origin TEXT NOT NULL DEFAULT 'verified' CHECK(data_origin IN ('verified','imported','demo')), featured INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS seasons(id INTEGER PRIMARY KEY, competition_id INTEGER NOT NULL REFERENCES competitions(id),
  name TEXT NOT NULL, start_date TEXT, end_date TEXT, UNIQUE(competition_id,name));
CREATE TABLE IF NOT EXISTS venues(id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT, country_id INTEGER REFERENCES countries(id),
  latitude REAL, longitude REAL, UNIQUE(name,city));
CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, short_code TEXT UNIQUE,
  short_code_approved INTEGER NOT NULL DEFAULT 0, country_id INTEGER REFERENCES countries(id),
  gender TEXT CHECK(gender IN ('men','women','open')), logo_url TEXT);
CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT NOT NULL, country_id INTEGER REFERENCES countries(id),
  role TEXT CHECK(role IN ('batter','bowler','all_rounder','wicket_keeper')), batting_style TEXT, bowling_style TEXT);
CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY, competition_id INTEGER NOT NULL REFERENCES competitions(id),
  season_id INTEGER REFERENCES seasons(id), venue_id INTEGER REFERENCES venues(id),
  home_team_id INTEGER NOT NULL REFERENCES teams(id), away_team_id INTEGER NOT NULL REFERENCES teams(id),
  match_no TEXT, format TEXT NOT NULL DEFAULT 'T20' CHECK(format IN ('T10','T20','The Hundred','ODI','List A','Test','First-class','Other')),
  start_utc TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled'
  CHECK(status IN ('scheduled','live','completed','abandoned','no_result','canceled')),
  weather TEXT, pitch_report TEXT, source TEXT NOT NULL,
  data_origin TEXT NOT NULL DEFAULT 'verified' CHECK(data_origin IN ('verified','imported','demo')),
  legacy_fixture_id INTEGER UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK(home_team_id<>away_team_id), UNIQUE(competition_id,home_team_id,away_team_id,start_utc));
CREATE INDEX IF NOT EXISTS matches_start ON matches(start_utc);
CREATE TABLE IF NOT EXISTS match_squads(match_id INTEGER NOT NULL REFERENCES matches(id), team_id INTEGER NOT NULL REFERENCES teams(id),
  player_id INTEGER NOT NULL REFERENCES players(id), PRIMARY KEY(match_id,team_id,player_id));
CREATE TABLE IF NOT EXISTS playing_xi(match_id INTEGER NOT NULL REFERENCES matches(id), team_id INTEGER NOT NULL REFERENCES teams(id),
  player_id INTEGER NOT NULL REFERENCES players(id), batting_order INTEGER, is_captain INTEGER NOT NULL DEFAULT 0,
  is_keeper INTEGER NOT NULL DEFAULT 0, is_impact_sub INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(match_id,team_id,player_id));
CREATE TABLE IF NOT EXISTS toss_results(match_id INTEGER PRIMARY KEY REFERENCES matches(id), winner_team_id INTEGER NOT NULL REFERENCES teams(id),
  decision TEXT CHECK(decision IN ('bat','bowl')), source TEXT NOT NULL, verified_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS match_results(match_id INTEGER PRIMARY KEY REFERENCES matches(id),
  result_type TEXT NOT NULL CHECK(result_type IN ('win','tie_super_over','tie','no_result','abandoned','canceled','awarded')),
  winner_team_id INTEGER REFERENCES teams(id), margin TEXT, method TEXT, source TEXT NOT NULL, verified_at TEXT NOT NULL,
  CHECK((result_type IN ('win','tie_super_over','awarded')) = (winner_team_id IS NOT NULL)));
CREATE TABLE IF NOT EXISTS innings(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id), innings_no INTEGER NOT NULL,
  batting_team_id INTEGER NOT NULL REFERENCES teams(id), runs INTEGER NOT NULL DEFAULT 0, wickets INTEGER NOT NULL DEFAULT 0,
  legal_balls INTEGER NOT NULL DEFAULT 0, target INTEGER, max_balls INTEGER, is_super_over INTEGER NOT NULL DEFAULT 0,
  completed INTEGER NOT NULL DEFAULT 0, UNIQUE(match_id,innings_no));
CREATE TABLE IF NOT EXISTS ball_events(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id), innings_no INTEGER NOT NULL,
  over_no INTEGER NOT NULL, ball_in_over INTEGER NOT NULL, seq INTEGER NOT NULL, batter_id INTEGER REFERENCES players(id),
  bowler_id INTEGER REFERENCES players(id), runs_bat INTEGER NOT NULL DEFAULT 0, extras INTEGER NOT NULL DEFAULT 0,
  extra_type TEXT CHECK(extra_type IN ('wide','no_ball','bye','leg_bye','penalty') OR extra_type IS NULL),
  is_wicket INTEGER NOT NULL DEFAULT 0, wicket_kind TEXT, commentary TEXT, source TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(match_id,innings_no,seq));
CREATE TABLE IF NOT EXISTS scorecards(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id), innings_no INTEGER NOT NULL,
  player_id INTEGER NOT NULL REFERENCES players(id), runs INTEGER, balls INTEGER, fours INTEGER, sixes INTEGER, dismissal TEXT,
  overs_bowled TEXT, maidens INTEGER, runs_conceded INTEGER, wickets INTEGER, UNIQUE(match_id,innings_no,player_id));
CREATE TABLE IF NOT EXISTS expert_profiles(id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE REFERENCES users(id), display_name TEXT NOT NULL,
  country_id INTEGER REFERENCES countries(id), language_code TEXT REFERENCES languages(code), bio TEXT, contact_url TEXT,
  verified INTEGER NOT NULL DEFAULT 0, verified_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expert_follows(user_id INTEGER NOT NULL REFERENCES users(id), expert_id INTEGER NOT NULL REFERENCES expert_profiles(id),
  created_at TEXT NOT NULL, PRIMARY KEY(user_id,expert_id));
CREATE TABLE IF NOT EXISTS model_versions(id INTEGER PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL, description TEXT NOT NULL,
  params_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(name,version));
CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY, prediction_uid TEXT NOT NULL UNIQUE, match_id INTEGER NOT NULL REFERENCES matches(id),
  source_type TEXT NOT NULL CHECK(source_type IN ('expert','model','legacy')), expert_id INTEGER REFERENCES expert_profiles(id),
  model_version_id INTEGER REFERENCES model_versions(id),
  prediction_type TEXT NOT NULL CHECK(prediction_type IN ('toss','winner','first_innings_score','second_innings_score','live_winner')),
  predicted_team_id INTEGER REFERENCES teams(id), predicted_value REAL, confidence REAL CHECK(confidence IS NULL OR (confidence>=0 AND confidence<=100)),
  explanation TEXT, factors_json TEXT, score_snapshot TEXT, created_at TEXT NOT NULL, locked_at TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','locked','canceled')),
  data_origin TEXT NOT NULL DEFAULT 'verified' CHECK(data_origin IN ('verified','imported','demo')),
  CHECK((source_type='expert') = (expert_id IS NOT NULL)), CHECK((source_type='model') = (model_version_id IS NOT NULL)));
CREATE INDEX IF NOT EXISTS predictions_match ON predictions(match_id);
CREATE TRIGGER IF NOT EXISTS v1_pred_locked_immutable BEFORE UPDATE ON predictions WHEN OLD.locked_at IS NOT NULL
 AND (NEW.match_id IS NOT OLD.match_id OR NEW.predicted_team_id IS NOT OLD.predicted_team_id OR NEW.predicted_value IS NOT OLD.predicted_value
  OR NEW.confidence IS NOT OLD.confidence OR NEW.explanation IS NOT OLD.explanation OR NEW.created_at IS NOT OLD.created_at
  OR NEW.locked_at IS NOT OLD.locked_at OR NEW.prediction_type IS NOT OLD.prediction_type OR NEW.score_snapshot IS NOT OLD.score_snapshot
  OR NEW.factors_json IS NOT OLD.factors_json OR NEW.source_type IS NOT OLD.source_type OR NEW.expert_id IS NOT OLD.expert_id
  OR NEW.model_version_id IS NOT OLD.model_version_id OR NEW.prediction_uid IS NOT OLD.prediction_uid)
 BEGIN SELECT RAISE(ABORT,'locked prediction is immutable'); END;
CREATE TRIGGER IF NOT EXISTS v1_pred_locked_nodelete BEFORE DELETE ON predictions WHEN OLD.locked_at IS NOT NULL
 BEGIN SELECT RAISE(ABORT,'locked prediction cannot be deleted'); END;
CREATE TABLE IF NOT EXISTS prediction_versions(id INTEGER PRIMARY KEY, prediction_id INTEGER NOT NULL REFERENCES predictions(id),
  version_no INTEGER NOT NULL, predicted_team_id INTEGER REFERENCES teams(id), predicted_value REAL, confidence REAL,
  factors_json TEXT, score_snapshot TEXT, created_at TEXT NOT NULL, UNIQUE(prediction_id,version_no));
CREATE TRIGGER IF NOT EXISTS v1_versions_noupdate BEFORE UPDATE ON prediction_versions BEGIN SELECT RAISE(ABORT,'prediction versions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS v1_versions_nodelete BEFORE DELETE ON prediction_versions BEGIN SELECT RAISE(ABORT,'prediction versions are append-only'); END;
CREATE TABLE IF NOT EXISTS prediction_evaluations(id INTEGER PRIMARY KEY, prediction_id INTEGER NOT NULL REFERENCES predictions(id),
  actual_team_id INTEGER REFERENCES teams(id), actual_value REAL,
  result TEXT NOT NULL CHECK(result IN ('correct','incorrect','void','pending','ineligible')), rule TEXT NOT NULL,
  evaluated_at TEXT NOT NULL, superseded_at TEXT);
CREATE INDEX IF NOT EXISTS evals_current ON prediction_evaluations(prediction_id,superseded_at);
CREATE TABLE IF NOT EXISTS venue_statistics(venue_id INTEGER PRIMARY KEY REFERENCES venues(id), matches INTEGER NOT NULL DEFAULT 0,
  bat_first_wins INTEGER NOT NULL DEFAULT 0, chase_wins INTEGER NOT NULL DEFAULT 0, avg_first_innings REAL, avg_second_innings REAL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS team_statistics(team_id INTEGER PRIMARY KEY REFERENCES teams(id), played INTEGER NOT NULL DEFAULT 0,
  won INTEGER NOT NULL DEFAULT 0, lost INTEGER NOT NULL DEFAULT 0, no_result INTEGER NOT NULL DEFAULT 0, last5 TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS player_statistics(player_id INTEGER NOT NULL REFERENCES players(id), format TEXT NOT NULL, matches INTEGER, runs INTEGER,
  batting_avg REAL, strike_rate REAL, wickets INTEGER, economy REAL, updated_at TEXT NOT NULL, PRIMARY KEY(player_id,format));
CREATE TABLE IF NOT EXISTS fantasy_teams(id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id), user_id INTEGER REFERENCES users(id),
  model_version_id INTEGER REFERENCES model_versions(id), players_json TEXT NOT NULL, captain_id INTEGER REFERENCES players(id),
  vice_captain_id INTEGER REFERENCES players(id), risk TEXT CHECK(risk IN ('low','medium','high')), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), kind TEXT NOT NULL,
  message_key TEXT NOT NULL, params_json TEXT, created_at TEXT NOT NULL, read_at TEXT);
CREATE TABLE IF NOT EXISTS data_provider_syncs(id INTEGER PRIMARY KEY, provider TEXT NOT NULL, provider_entity TEXT NOT NULL,
  provider_id TEXT NOT NULL, local_table TEXT NOT NULL, local_id INTEGER NOT NULL, payload_hash TEXT, synced_at TEXT NOT NULL,
  UNIQUE(provider,provider_entity,provider_id));
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, action TEXT NOT NULL, payload TEXT, old_value TEXT, created_at TEXT NOT NULL);
"""

LANGS = [  # code, english name, native name, rtl, ui_complete
    ("en", "English", "English", 0, 1), ("hi", "Hindi", "हिन्दी", 0, 1), ("te", "Telugu", "తెలుగు", 0, 1),
    ("ta", "Tamil", "தமிழ்", 0, 0), ("bn", "Bengali", "বাংলা", 0, 0), ("mr", "Marathi", "मराठी", 0, 0),
    ("kn", "Kannada", "ಕನ್ನಡ", 0, 0), ("ml", "Malayalam", "മലയാളം", 0, 0), ("gu", "Gujarati", "ગુજરાતી", 0, 0),
    ("pa", "Punjabi", "ਪੰਜਾਬੀ", 0, 0), ("ur", "Urdu", "اردو", 1, 0), ("ar", "Arabic", "العربية", 1, 0),
    ("ne", "Nepali", "नेपाली", 0, 0), ("si", "Sinhala", "සිංහල", 0, 0), ("ps", "Pashto", "پښتو", 1, 0),
    ("es", "Spanish", "Español", 0, 0), ("fr", "French", "Français", 0, 0), ("pt", "Portuguese", "Português", 0, 0),
    ("de", "German", "Deutsch", 0, 0), ("nl", "Dutch", "Nederlands", 0, 0), ("zh", "Chinese", "中文", 0, 0),
    ("ja", "Japanese", "日本語", 0, 0), ("af", "Afrikaans", "Afrikaans", 0, 0), ("sw", "Swahili", "Kiswahili", 0, 0),
]

# Competition listing from the owner's "SH Predictor - Global League Index" > "2026 Verified Archive" tab.
# Only names/divisions/regions are seeded: no fixtures or results are invented from it.
INDEX_SOURCE = "https://www.cricbuzz.com/cricket-scorecard-archives/2026 (via SH Predictor - Global League Index)"
COMPETITIONS_2026 = [
    ("International", "Women", "Global", "ICC Women's T20 World Cup 2026"), ("International", "Women", "Asia", "Women's Asia Cup 2026"),
    ("International", "Women", "Asia", "ACC Women's T20I Premier Cup 2026"), ("International", "Women", "Global", "ICC Women's T20 World Cup Global Qualifier 2026"),
    ("International", "Women", "Global", "ICC Women's Emerging Nations Trophy 2026"), ("International", "Men", "Asia", "ACC Men's U19 Asia Cup 2026"),
    ("International", "Men", "Asia", "ACC Men's Asia Cup Rising Stars 2026"), ("International", "Men", "Global", "ICC U19 World Cup 2026"),
    ("League", "Women", "Australia", "Women's Big Bash League 2026"), ("League", "Women", "India", "Women's Premier League 2026"),
    ("League", "Women", "England", "The Hundred Women 2026"), ("League", "Women", "West Indies", "Women's Caribbean Premier League 2026"),
    ("League", "Women", "England", "Women's T20 Blast 2026"), ("League", "Men", "UAE", "Abu Dhabi T10 2026"),
    ("League", "Men", "UAE", "International League T20 2026"), ("League", "Men", "Australia", "Big Bash League 2026-27"),
    ("Domestic", "Men", "India", "Ranji Trophy Elite 2026-27"), ("Domestic", "Men", "India", "Ranji Trophy Plate 2026-27"),
    ("Domestic", "Men", "India", "Vijay Hazare Trophy Elite 2026-27"), ("Domestic", "Men", "Australia", "Sheffield Shield 2026-27"),
    ("Domestic", "Men", "New Zealand", "The Ford Trophy 2026-27"), ("Domestic", "Men", "New Zealand", "Plunket Shield 2026-27"),
    ("Domestic", "Men", "South Africa", "CSA Four-Day Series Division One 2026-27"), ("Domestic", "Men", "England", "County Championship Division One 2026"),
    ("Domestic", "Women", "Australia", "T20 Spring Challenge 2026"),
]

BASELINE_MODEL = ("sh-baseline", "1.0.0",
    "Explainable logistic blend of smoothed recent form, head-to-head, home advantage and venue toss/chase bias. "
    "Uses only verified completed matches stored in SH PREDICTION. Toss is modelled as a fair coin.",
    {"form_window": 10, "form_weight": 1.6, "h2h_weight": 0.8, "home_weight": 0.25, "venue_weight": 0.6, "laplace": 1})

def _seed(c):
    c.executemany("INSERT OR IGNORE INTO languages(code,name,native_name,rtl,ui_complete) VALUES(?,?,?,?,?)", LANGS)
    for cat, div, region, name in COMPETITIONS_2026:
        country_id = None
        if region not in ("Global", "Asia"):
            c.execute("INSERT OR IGNORE INTO countries(name) VALUES(?)", (region,))
            country_id = c.execute("SELECT id FROM countries WHERE name=?", (region,)).fetchone()[0]
        c.execute("INSERT OR IGNORE INTO competitions(name,category,division,country_id,source,data_origin) VALUES(?,?,?,?,?,'verified')",
                  (name, cat, div, country_id, INDEX_SOURCE))
    n, v, d, p = BASELINE_MODEL
    c.execute("INSERT OR IGNORE INTO model_versions(name,version,description,params_json,created_at) VALUES(?,?,?,?,?)",
              (n, v, d, json.dumps(p), now()))

MIGRATIONS = [("001_normalized_core", M001, _seed)]

def migrate(c):
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in c.execute("SELECT name FROM schema_migrations")}
    for name, ddl, seed in MIGRATIONS:
        if name in done:
            continue
        c.executescript(ddl)
        # legacy audit_logs predates v1; add actor/entity columns if missing
        cols = {r[1] for r in c.execute("PRAGMA table_info(audit_logs)")}
        for col in ("actor", "entity", "entity_id"):
            if col not in cols:
                c.execute("ALTER TABLE audit_logs ADD COLUMN " + col + " TEXT")
        if seed:
            seed(c)
        c.execute("INSERT INTO schema_migrations(name,applied_at) VALUES(?,?)", (name, now()))
    c.commit()

# ---------------------------------------------------------------- legacy bridge
def _team(c, name):
    c.execute("INSERT OR IGNORE INTO teams(name) VALUES(?)", (name,))
    return c.execute("SELECT id FROM teams WHERE name=?", (name,)).fetchone()[0]

def _comp(c, name):
    c.execute("INSERT OR IGNORE INTO competitions(name,source,data_origin) VALUES(?,?, 'imported')", (name, "legacy SH PREDICTION fixtures"))
    return c.execute("SELECT id FROM competitions WHERE name=?", (name,)).fetchone()[0]

def bridge_legacy(c):
    """Idempotently mirror legacy fixtures / approved predictions / outcomes into v1 tables."""
    if not c.execute("SELECT name FROM sqlite_master WHERE name='fixtures'").fetchone():
        return
    for f in c.execute("SELECT * FROM fixtures WHERE id NOT IN (SELECT legacy_fixture_id FROM matches WHERE legacy_fixture_id IS NOT NULL)").fetchall():
        comp = _comp(c, f["competition"])
        c.execute("INSERT OR IGNORE INTO seasons(competition_id,name) VALUES(?,?)", (comp, f["season"]))
        season = c.execute("SELECT id FROM seasons WHERE competition_id=? AND name=?", (comp, f["season"])).fetchone()[0]
        venue = None
        if f["venue"]:
            c.execute("INSERT OR IGNORE INTO venues(name,city) VALUES(?,'')", (f["venue"],))
            venue = c.execute("SELECT id FROM venues WHERE name=? AND city=''", (f["venue"],)).fetchone()[0]
        h, a = _team(c, f["home"]), _team(c, f["away"])
        c.execute("""INSERT OR IGNORE INTO matches(competition_id,season_id,venue_id,home_team_id,away_team_id,match_no,start_utc,source,data_origin,
                     legacy_fixture_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'imported',?,?,?)""",
                  (comp, season, venue, h, a, f["match_no"], f["start_utc"], f["source"], f["id"], now(), now()))
    mid = {r[0]: r[1] for r in c.execute("SELECT legacy_fixture_id,id FROM matches WHERE legacy_fixture_id IS NOT NULL")}
    for p in c.execute("SELECT p.*,f.home,f.away FROM legacy_predictions p JOIN fixtures f ON f.id=p.fixture_id WHERE p.status='approved'").fetchall():
        for kind, pick in (("toss", p["toss_pick"]), ("winner", p["winner_pick"])):
            if not pick or p["fixture_id"] not in mid:
                continue
            uid = "legacy-%d-%s" % (p["id"], kind)
            c.execute("""INSERT OR IGNORE INTO predictions(prediction_uid,match_id,source_type,prediction_type,predicted_team_id,explanation,
                         created_at,locked_at,status,data_origin) VALUES(?,?,'legacy',?,?,?,?,?,'locked','imported')""",
                      (uid, mid[p["fixture_id"]], kind, _team(c, pick), "Imported from SH PREDICTION v0 register", p["created_at"], p["approved_at"]))
    for o in c.execute("SELECT * FROM outcomes").fetchall():
        m = mid.get(o["fixture_id"])
        if not m:
            continue
        if o["toss_winner"]:
            dec = (o["toss_decision"] or "").lower() or None
            c.execute("""INSERT INTO toss_results(match_id,winner_team_id,decision,source,verified_at) VALUES(?,?,?,?,?)
                         ON CONFLICT(match_id) DO UPDATE SET winner_team_id=excluded.winner_team_id,decision=excluded.decision,
                         source=excluded.source,verified_at=excluded.verified_at WHERE toss_results.verified_at<>excluded.verified_at""",
                      (m, _team(c, o["toss_winner"]), dec, o["source"], o["verified_at"]))
        st = o["status"] or "completed"
        rtype = {"completed": "win", "abandoned": "abandoned", "no_result": "no_result", "void": "canceled"}[st]
        winner = _team(c, o["match_winner"]) if (st == "completed" and o["match_winner"]) else None
        if rtype == "win" and winner is None:
            continue
        c.execute("""INSERT INTO match_results(match_id,result_type,winner_team_id,source,verified_at) VALUES(?,?,?,?,?)
                     ON CONFLICT(match_id) DO UPDATE SET result_type=excluded.result_type,winner_team_id=excluded.winner_team_id,
                     source=excluded.source,verified_at=excluded.verified_at WHERE match_results.verified_at<>excluded.verified_at""",
                  (m, rtype, winner, o["source"], o["verified_at"]))
        c.execute("UPDATE matches SET status=? WHERE id=? AND status<>?", (st if st != "void" else "canceled", m, st if st != "void" else "canceled"))
