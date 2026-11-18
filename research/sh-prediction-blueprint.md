# SH PREDICTION blueprint v0.1
## A. Existing repository audit (commit 2c42b83)
Stack found: Python stdlib http.server (app/main.py), SQLite (SH_PREDICTION_DB), single-file HTML client (app/index.html), render.yaml (web, starter plan, 1 GB disk at /var/data). NOT found: Kotlin/Compose Android project, FastAPI, PostgreSQL, tests, CI.
Gap vs master script: script says Kotlin + FastAPI + PostgreSQL; repo is Python stdlib + SQLite + web. Decision needed from owner (see section D).
Existing tables: fixtures, predictions, outcomes, archive, odds. Endpoints: /health, /fixtures, /results, /predictions, /archive, /odds, /accuracy, /auth/generate|verify|logout, /admin/fixtures|predictions|approve|outcomes|import_odds_batch|review_odds|archive|review_archive.
Good practices already present: approval workflow (draft->approved), prediction locked after start time, odds range 1.01-1000, source and timezone required, HTTPS source for archive, reviewed-only public reads, "no invented data" empty states.
## B. Findings
1. HIGH — Admin authorization hole: auth() returns true for ANY valid login session, so any logged-in user can call /admin/* (create fixtures, approve predictions, record outcomes). Fix: admin endpoints must require X-Admin-Token only (constant-time compare, token non-empty).
2. HIGH — OTP is returned in the API response and shown on screen; it proves nothing about phone ownership. Acceptable only as a convenience login; no personal or paid features behind it. Real SMS OTP needs a paid provider (not free) — keep convenience login and label it.
3. MEDIUM — Pending OTPs are in memory; lost on restart and not shared across instances.
4. MEDIUM — Sessions never expire (login_sessions has created_at but no TTL check).
5. MEDIUM — README says app files are not committed; outdated.
6. MEDIUM — /health and static pages public; fine. Data GETs need login; decide if fixtures should be public.
7. LOW — fixtures UNIQUE and INSERT OR IGNORE silently ignore duplicates; outcomes INSERT can fail on repeat (PRIMARY KEY) with generic error.
8. LOW — No tests; no rate limit on /auth/generate beyond 20s per phone (no per-IP limit).
9. LOW — index.html is one dense file; hard to maintain. Split later.
10. INFO — Render disk + sqlite requires a single instance and a paid plan (starter); consistent with render.yaml.
## C. Navigation blueprint
Top switch (locked): CRICKET | WORLD. Bottom nav (proposed): Home, Matches, Series, Predictions, More.
Match Center: 17 tabs from the master script, including Odds Price History (already built). Every tab: data only from authorized or user-supplied sources, with source label and observed-at time.
## D. Decisions needed from owner
1. Keep Python + SQLite + web app for now, or restart as Kotlin + FastAPI + PostgreSQL? (Recommend: keep current backend, add Android WebView/Compose shell later.)
2. Data source: where will fixtures/scores come from legally (official API with a licence, or manual entry)? Without this, Live Score tabs stay empty.
3. WORLD section: which sports/regions first?
## E. Next batches
BATCH 02: fix admin auth, session TTL, README, tests. BATCH 03: Match Center 17-tab shell with empty states. BATCH 04: Home/Series/Teams/Players. BATCH 05: Android shell.
