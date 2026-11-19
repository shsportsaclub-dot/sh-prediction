# SH Universal Cricket Data Bridge

Server-side and independent of any APK. It runs inside the SH PREDICTION backend (`app/scheduler.py`) 24/7. The website and Android app only read our own API, which returns the same data to every client.

## Flow
```
Sources (adapters) ──> normalizer ──> our database (canonical IDs) ──> /api/v1 + SSE stream ──> website, Android, Assistant, Fantasy, Game
```
Every imported record keeps its provider and provider ID (`data_provider_syncs`). The original payload is kept for API sources (`source_records`), and so is a content hash for file sources, so corrections are detected.

## Adapters
| Adapter | Kind (script §2) | What it brings | Schedule | Status |
|---|---|---|---|---|
| Owner Google Sheets (`gsheets.py`) | A (owner CSV/XLSX) | Fixtures, teams, venue, toss, decision, winner, margin from the 6 league sheets; every tab read | every 30 min | Built and tested with stand-in files. **The sheets must be shared "Anyone with the link: Viewer"**; they are not shared yet. |
| League Index registry (`gsheets.sync_index_registry`) | A | The competition directory tabs → registry as *unverified* | daily | Built and tested with the real index rows |
| Cricsheet (`cricsheet.py`) | C (open dataset) | Full scorecards, ball-by-ball, toss, XI, results; all formats incl. Tests and draws | `recently_added_7` daily; one catalogue file every 6 h (IPL, WPL, BBL, WBBL, NPL first, then every other file on the official downloads page) | Built and tested with Cricsheet-format files. **Real download not yet run**: this workspace can't reach cricsheet.org; it runs on the server. |
| CricketData.org API (`cricketdata.py`) | A (authorized API, owner's key) | Match list (upcoming/live/finished), live score lines, toss, result | list hourly; live every 15 min, only when one of its matches is live or about to start | Built and tested with the provider's JSON format. Needs `CRICKETDATA_API_KEY` on the server. Free plan 100 hits/day, shared with the Telegram bot: SH PREDICTION uses ≤60 and stops when <15 remain. |
| SH own scoring (`admin_ball`) | D (first-party) | Ball-by-ball live, scorecard, commentary, probability via SSE | every ball | Built (Batch 04) |
| Authorized streaming feeds | E | — | — | Interface only; no feed is authorized yet |
| Permitted website parser | B | — | — | Not built: no site found whose terms clearly permit automated collection and reuse. Cricbuzz, ESPNcricinfo and CREX are references only. |

## Data rules
* **Nothing is invented.** Blank sheet cells stay unknown; a missing start time stays date-only and the source note says so. A score-only source never shows ball-by-ball.
* **Labels on every match** (`data_status`): Upcoming · Live (ball-by-ball, SH scoring) · Live (score only, CricketData) · Delayed (last update hh:mm, over 30 min old) · Live data unavailable · Historical (ball-by-ball) · Result only · Demo.
* **Home/away:** Cricsheet and CricketData list teams without a home flag, so the listed order is stored (`listed_order`), `home_away_verified=0`, and the app says "Team order as listed by the source; home/away not verified". The owner's sheets have Home/Away columns, so they count as verified.
* **Duplicates:** the same provider ID is never imported twice. Matches from *different* sources are never merged automatically; same day + same two teams are listed in Admin → Data Bridge for review.
* **Corrections:** a changed sheet row updates the same match; a changed result is recorded as an audited revision and predictions are re-settled. A corrected Cricsheet file (new hash) replaces that match's imported records: no duplicate balls or statistics.
* **Players** are never merged by name. A Cricsheet registry ID links the same person across matches; a name without one gets its own record marked `unverified`.
* **Scorecard check:** each Cricsheet innings total is compared with the sum of its deliveries; mismatches are reported in the job log, and `/cricket/matches/{id}/statistics` returns `deliveries_match_total`.
* **Formats:** T10, T20, The Hundred (5-ball overs), ODI, List A, Test, First-class; ties, super overs, bowl-outs, D/L method, draws, no results, abandoned.

## Reliability
* Each run is logged (`collector_log`, last 200 per job), with status, summary and error.
* A failed job retries after 5, 10, 20… minutes (never longer than its normal interval); after a restart, a job left "running" is cleared after 3 hours.
* Admin → Data Bridge: run now, pause/resume, change interval and CricketData daily budget, see last results and duplicate suspects.
* Turn off all collectors with `SH_COLLECTORS=0`.

## Limits (honest)
* The free Render plan **sleeps after 15 minutes without visitors**, and collectors stop while it sleeps. It also **erases the database on restart**. 24/7 collection and keeping data need a paid instance with a disk (see DEPLOYMENT.md).
* Worldwide live ball-by-ball is not available from any free, authorized source we found. Live ball-by-ball exists for SH-scored matches; other live matches show score only (CricketData) or "unavailable".
