# QA addendum — owner mockups (10 concept boards, 19 Nov 2026) applied to the real app

`pytest`: **93 passed**. Chrome: 48 page loads (12 routes × 2 loads × phone 390 px and desktop 1366 px): no JavaScript errors, no "could not load". Startup now draws once, after all screen scripts load, which fixes an intermittent "Cannot set properties of null" on deep links.
Built from the mockups with our own data only: sport selector (Cricket live; Tennis, Football, Badminton, Kabaddi "Coming soon", contract order), quick links (Live, Upcoming, Series, Predictions, News); Match Center view modes SH Advanced / CREX-style / Cricbuzz-style (saved per device) with CREX order Info, Fantasy, Discussions, Commentary, Live, Scorecard, History, Series Stats, Graphs; header strip CRR / Target / RRR / Overs left / Toss and lead-trail banner for multi-day matches; Commentary filters All, Highlights, Overs, W, 4s, 6s with end-of-over summaries; History (innings progression; day/session split marked unavailable: no ball times from sources); Series Stats (points table, most runs/wickets). Mockup sample players, scores and percentages were not copied. The "World" tab in one mockup was left out per the implementation contract.
Pending: Discussions uses SH SOCIAL match posts; fantasy rankings by filters (last 5 / at venue / vs team), player analysis page, day/session history, AI recap need data or work not yet done.

---

# QA addendum — Blueprint v2.0, Phase 2 (core application)

`pytest`: **93 passed**. Chrome at 360/390/430 px (phone), 768 px (tablet), 1366 px (desktop): Home, Matches, Series list, Series page (points table), Predictions, Match Center (default tab by status), More, Search, Social, Leaderboard: **no JavaScript errors, no horizontal overflow** (only the intended scrolling rows). The new Home is drawn on every load (3 loads per width). Screenshots: `docs/qa/v2/`.
Built: 5-item bottom bar (Home · Matches · Series · Predictions · More), global header (live indicator, search, language, notifications, theme, profile), Cricbuzz-style Home (featured match cards with innings scores, RRR when chasing, status/result/start time; filters All/Live/Upcoming/Results/International/Domestic/Women/T20/ODI/Test/T10 against real match fields; featured predictions labelled Estimate; SH feature shortcuts; dashboard), Series pages (fixtures, results, points table with ICC-style NRR, teams, top run-scorers and wicket-takers), Match Center tab order Weather → Graphs plus "More match details", one missing-data sentence in 9 languages.
Not available from current sources (shown as such): news, rankings. Not built yet: player/team/venue profile pages, weather feed, 3D Virtual Live, Broadcast Studio (Phases 3–5).

---

# QA addendum — Batch 05b (AllCric-style Match Center on the free plan, tipster world ranking)

`pytest`: **85 passed** (2 runs). SH SOCIAL E2E: **21/21**. Chrome 390×844: Live (score header with last-ball flash, over strip, batters, bowler, opening-stand partnership), Scorecard (batting, extras breakdown, total, bowling), Playing XI (squads with roles, initials instead of photos), Graphs (Manhattan from provider ball rows), Head-to-head (last-5 form, H2H list), Info (venue stats), Tipster leaderboard (pinned "#1 You" row + world rank): `docs/qa/match-center/*.png`. No JavaScript errors.
Field names for CricketData scorecard/squad replies come from the owner's working live-line server (`mename-shs-backend`), which reads them live; tests use replies in that shape. **The real CricketData calls still have to be proven on the server** (blocked here). If the free plan refuses `match_scorecard`/`match_bbb` (CricketData marks these fantasy endpoints as plan-dependent), the tabs show the provider's refusal and fall back to the score line; nothing is invented.
Not built, by decision: betting odds (Back/Lay, session YES/NO), "Watch Live" (no broadcast rights), player photos (copyright).

---

# QA report — Batch 05 (Automatic cricket data: Google Sheets, Cricsheet, CricketData, worldwide registry)

Run date: 2026-11-19 (UTC). `python -m pytest -q tests` → **82 passed**, three runs in a row. The SH SOCIAL end-to-end proof was rerun: **21/21 steps passed**.

## Test types (kept separate on purpose)
| Kind | What | Result |
|---|---|---|
| Unit | header detection, H-/A- code resolution, Excel date/time cells, built-in .xlsx reader = openpyxl output | pass |
| Mocked integration (local stand-ins in the real formats) | owner sheet sync incl. corrections, blanks, unshared sheet; League Index → registry using the **real index rows**; CricketData JSON (finished, live, upcoming), budget stop and shared-key reserve, key never logged; Cricsheet Test draw, corrected file (no duplicate balls), catalogue discovery from a downloads page, players not merged by name; scheduler backoff + log; admin-only controls; public status | pass (`tests/test_bridge.py`) |
| Real process | server stopped and started twice on the imported data; every imported match still served | pass |
| **Real external services** | Google Sheets export, CricketData API, Cricsheet download (real IPL import of 20 matches) | **NOT RUN: blocked here.** This workspace cannot reach docs.google.com, api.cricapi.com or cricsheet.org. They run on the server once deployed; the owner's league sheets are also not shared yet. |

## Screens checked in Chrome (390×844 @2x, no JavaScript errors)
`docs/qa/bridge-matches.png`: Matches list with honest labels ("Live · score only (cricketdata)" with the score line, "Upcoming", "Result only · no ball-by-ball", "Historical · ball-by-ball") and the home/away note. `docs/qa/admin-bridge.png`, `docs/qa/admin-registry.png`: the Data Bridge and Global Registry admin screens.

## Pending acceptance (needs your approval to deploy, then runs on the server)
1. Share the 6 league sheets → Admin → Data Bridge → owner_sheets_sync → Run now → matches appear in Matches.
2. Add `CRICKETDATA_API_KEY` → cricketdata_matches → Run now.
3. cricsheet_backfill → Run now (imports ipl_json.zip first) → open an IPL match: scorecard, commentary, graphs; run again → 0 created / all duplicates.
4. Restart the service → data still there (only with a persistent disk; the free plan erases it).

---

# QA report — Batch 04 (Final Integration & Security, Tipster Social Network, SH SOCIAL photos/videos/Reels)

Run date: 2026-11-19T03:58:32Z (UTC). Python 3.13, SQLite (WAL), FFmpeg 6.1, Pillow 12, Google Chrome (Playwright).

## Automated tests
`python -m pytest -q tests` → **72 passed**, repeated **15 times in a row with no failure** after the fixes below.
New: `tests/test_social.py` (accounts, social, media with real JPEG/MP4, live SSE, commentary, game, admin sweep of 22 GET + 33 POST admin paths × no credentials / normal account / wrong key) and `tests/test_owner_master.py` (30-row owner master, approved colour rule rows 01–05, idempotent, admin-only).

Bugs found and fixed during QA:
* Cricsheet background import intermittently rejected matches with "database is locked" (about 1 run in 6) → one `BEGIN IMMEDIATE` transaction per match with retry.
* Media worker could leave a job "running" forever if the final write met a lock → retried final write; jobs stuck over 30 min are re-queued (max 3 attempts).
* Demo mode hid real users' posts from the feed → real posts always show; demo adds only labelled DEMO posts.
* Reel action buttons picked up two different styles → unified.
* Login lockout counter was rolled back on error → committed before the error.

## Mandatory end-to-end acceptance proof (`tools/e2e_social.py`)
Real server process, production-like settings (codes not exposed; verification emails delivered over SMTP to a local mail catcher), real files (2000×1200 JPEG, 6-second 1280×720 H.264 video), real Chrome. Evidence: `docs/qa/e2e/e2e-evidence.json` (API responses, database counts, worker logs), `docs/qa/e2e/server.log`, screenshots in `docs/qa/e2e/`.

| Step | Result |
|---|---|
| database migration with verified backup | PASS |
| 1. User A registers, verifies email via SMTP and logs in | PASS |
| 2. Photo uploaded (chunked), processed and published | PASS |
| 3. Text post created and published | PASS |
| 4. Video uploaded; reel post waits for processing | PASS |
| 5. Background worker processed the video automatically | PASS |
| 6. Thumbnail, MP4 and HLS renditions generated on disk | PASS |
| 7. Reel published automatically after processing | PASS |
| 7b. Second reel published (needed to prove swipe navigation) | PASS |
| 8-9. User B opens the Reel in Chrome; it plays, advances and pauses | PASS |
| 9b. Swipe navigation scrolls to the next reel slot | PASS |
| 10-13. User B followed, liked, commented, shared and saved; counts match the database | PASS |
| 14. Creator analytics updated (views, likes, comments, shares, saves, followers, watch time, completion) | PASS |
| 15. Cricket posts appear in the Match Center Community by Match ID | PASS |
| 16. Post reported by User B and removed by an administrator | PASS |
| 17-18. Only the owner can delete; deletion removes the media files | PASS |
| 19. Admin endpoints reject a logged-in non-admin | PASS |
| 20. Social feed renders without horizontal overflow on android-phone | PASS |
| 20. Social feed renders without horizontal overflow on desktop | PASS |
| browser had no JavaScript errors | PASS |
| 10 (persistence). After a server restart the Reel, its counts and its media are still served | PASS |

Not covered by this proof (blocked here, not claimed): object storage/CDN (not set up), real SMTP provider (local catcher used), ClamAV (not installed), Docker image build (Docker Hub unreachable from this workspace), a physical Android phone, Firefox and Safari (not installed; Chrome desktop + Android-size emulation only).

## Viewer screens checked in Chrome (390×844 @2x), no JavaScript errors
Account login, Social feed (English and Telugu), Create post, Profile, Creator dashboard, Leaderboard, More, Cricket game with 2D field, Reels, post detail with comment, Match Center Community, admin Moderation and Master List (owner Abu Dhabi T10, 30 rows). Screenshots: `docs/qa/social/`, `docs/qa/e2e/`, `docs/qa/owner-master-list.png`.

---

# QA report — Batch 03 (own platform: admin/viewer split, engines, fantasy, assistant, data gateway)

Run date: 2026-11-19 (IST). Python 3.13, SQLite, Google Chrome headless (Playwright).
Every PASS below comes from an actual run of `python -m unittest discover -s tests -v` → **Ran 57 tests, OK**
(the 33 tests from commit 8cf4369 were re-run first and passed; some were updated where the new instructions changed the rules, see below).

## Master Script §12 checklist
| Requirement | Evidence | Result |
|---|---|---|
| Admin access restrictions | `ViewerIsolation.test_viewer_cannot_see_private_things`, `Security.*`, browser probe: 4 admin endpoints → 403 without key | PASS |
| Viewer data isolation | unpublished / draft predictions invisible to anonymous and logged-in viewers; expert history and accuracy count published only; viewer page has 0 admin links | PASS |
| Prediction immutability | `Integrity.test_prediction_locking_and_immutability`, `test_live_versions_append_only`, `test_publication_cannot_bypass_lock_in_db` | PASS |
| Actual result separation | Master List reads only toss_results / match_results; predictions in separate tables; recording a result leaves the prediction row byte-identical | PASS |
| Prediction accuracy | `Evaluation.test_correct_wrong_void_pending_and_formula` (4 / (4+3) = 57.1%) | PASS |
| ICC result handling | Super Over winner counts, tie without Super Over → void, no result → void, toss still settles | PASS |
| API authorization | Bearer for user data, admin key for /admin, verified-expert check, structured 401/403 | PASS |
| Data synchronization | ball-by-ball totals (wides/no-balls not legal), duplicate ball rejected, provider sync dedupe, retry ×3 then "failed" recorded | PASS |
| Localization | 9 languages at 100% (en, hi, te, ta, kn, bn, mr, ur, es); others report their real coverage and say English is used for the rest; preference persists on a second session; browser shows Telugu tabs | PASS |
| Mobile responsiveness | all viewer screens at 390×844 @2x, admin at 390 px and 1280 px | Checked visually (not on a physical phone) |
| Browser compatibility | Chrome (headless) only | Partial — Firefox/Safari not run |
| Error handling | every screen has loading / empty / error+Retry / offline states; API errors are structured | Implemented; Retry path not automated |
| Database migration safety | no migration on page load (viewer gets 503 until admin migrates); backup taken and verified first; v0 data kept; classic accuracy unchanged after migration | PASS |

Tests changed on purpose (new instructions): viewer reads are public (401 now only for /me/*); v0 register endpoints (/fixtures, /register, /accuracy …) are admin-only; the public `/master-list` was removed (admin-only results master now).

## Browser probes (clearly labelled DEMO data)
* Viewer before migration: HTTP 503 `MIGRATION_PENDING`. Migration: `migrated`, backup integrity `ok`.
* Admin Master List colours (D1–D4): `H-` blue, `A-` orange; toss code green when the toss winner won (D1, D2), red when it lost (D3: H-DEE red, A-DRR green), grey with no result (D4: A-DUB grey, winner grey —). Same values in dark and desktop layouts.
* Viewer signals contain no factor weights (`contribution` absent). Console errors: none.
* Assistant: LBW → Law 36 with source; questions without stored data → "I don't have verified data…"; demo matches are never used as facts.

## All automated tests
| Test | Result |
|---|---|
| `test_v1.CricsheetImport.test_import_results_scorecards_dedupe_and_attribution` | PASS |
| `test_v1.CricsheetImport.test_download_retries_then_fails_cleanly` | PASS |
| `test_api.Acc.test_approved_prediction_immutable` | PASS |
| `test_api.Acc.test_csv_export_neutralises_formulas` | PASS |
| `test_api.Acc.test_late_prediction_excluded` | PASS |
| `test_api.Acc.test_revision_audited_and_admin_only` | PASS |
| `test_api.Acc.test_settlement_rules` | PASS |
| `test_api.T.test_admin_flow` | PASS |
| `test_api.T.test_bad_phone` | PASS |
| `test_api.T.test_data_needs_login` | PASS |
| `test_api.T.test_health_public` | PASS |
| `test_api.T.test_outcome_once` | PASS |
| `test_api.T.test_user_cannot_use_admin` | PASS |
| `test_v1.AdminOps.test_csv_import_dry_run_then_commit` | PASS |
| `test_v1.AdminOps.test_edit_match_guarded` | PASS |
| `test_v1.AdminOps.test_roles_settings_dashboard` | PASS |
| `test_v1.Assistant.test_grounded_and_honest` | PASS |
| `test_v1.DataGateway.test_contract_and_provider_sync` | PASS |
| `test_v1.DataGateway.test_retry_then_fail_recorded` | PASS |
| `test_v1.DataGateway.test_stats_endpoints` | PASS |
| `test_v1.Engines.test_calibration_backtest` | PASS |
| `test_v1.Engines.test_match_centre_sections` | PASS |
| `test_v1.Engines.test_over_projection_and_phases` | PASS |
| `test_v1.Evaluation.test_correct_wrong_void_pending_and_formula` | PASS |
| `test_v1.Evaluation.test_missing_result_handling` | PASS |
| `test_v1.Evaluation.test_tie_without_super_over_is_void_and_revision_supersedes` | PASS |
| `test_v1.Fantasy.test_configurable_rules` | PASS |
| `test_v1.Fantasy.test_unavailable_until_squad_then_provisional_then_confirmed` | PASS |
| `test_v1.Integrity.test_draft_lock_flow` | PASS |
| `test_v1.Integrity.test_duplicate_match_prevention` | PASS |
| `test_v1.Integrity.test_live_versions_append_only` | PASS |
| `test_v1.Integrity.test_pre_match_closed_after_start` | PASS |
| `test_v1.Integrity.test_prediction_locking_and_immutability` | PASS |
| `test_v1.LanguageAndDemo.test_demo_excluded_from_headline` | PASS |
| `test_v1.LanguageAndDemo.test_language_persistence` | PASS |
| `test_v1.Languages.test_coverage_is_honest` | PASS |
| `test_v1.Legacy.test_legacy_bridge` | PASS |
| `test_v1.LiveAndModel.test_live_probability_sane` | PASS |
| `test_v1.LiveAndModel.test_model_prediction_explainable` | PASS |
| `test_v1.LiveAndModel.test_score_update_sync` | PASS |
| `test_v1.MasterList.test_no_result_and_super_over` | PASS |
| `test_v1.MasterList.test_results_master_colours_and_admin_only` | PASS |
| `test_v1.MasterList.test_unapproved_code_not_shown` | PASS |
| `test_v1.MigrationSafety.test_backup_verified_and_legacy_kept` | PASS |
| `test_v1.MigrationSafety.test_no_migration_on_page_load` | PASS |
| `test_v1.OwnApk.test_redirect_without_token_and_stream_with_token` | PASS |
| `test_v1.Privacy.test_admin_key_with_user_session_keeps_preferences` | PASS |
| `test_v1.Privacy.test_admin_model_versions_secret_weights` | PASS |
| `test_v1.Privacy.test_users_see_outcomes_not_logic` | PASS |
| `test_v1.Security.test_audit_logged` | PASS |
| `test_v1.Security.test_auth_required_and_structured_errors` | PASS |
| `test_v1.Security.test_rate_limit` | PASS |
| `test_v1.Security.test_unverified_expert_blocked_verified_allowed` | PASS |
| `test_v1.Security.test_user_cannot_use_admin_or_post_predictions` | PASS |
| `test_v1.Security.test_validation_and_pagination` | PASS |
| `test_v1.ViewerIsolation.test_publication_cannot_bypass_lock_in_db` | PASS |
| `test_v1.ViewerIsolation.test_viewer_cannot_see_private_things` | PASS |
## Security findings
1. **HIGH — GitHub repository is public.** All source code (not the data or admin key) is readable by anyone. Model weights now live in the database (admin-only), but the code itself is public. Fix: make the repo private (free on GitHub). Before doing that, set `SH_GITHUB_TOKEN` (read-only) on Render so `/download/sh-prediction.apk` keeps working.
2. **HIGH — Login is an on-screen code.** It does not prove phone ownership, so anyone can log in as any number. Only low-risk features sit behind it (preferences, follows, expert submissions that stay private until an admin publishes). Admin rights come only from the admin key.
3. **MEDIUM — Single shared admin key.** No per-admin accounts yet; every admin action is audited as "admin-token". Keep the Render-generated key secret and rotate it if shared.
4. **MEDIUM — Paid hosting in render.yaml.** `plan: starter` + 1 GB disk are paid Render features. The free plan has no persistent disk (SQLite data would be lost on restart). Needs your decision.
5. **LOW — In-memory rate limit** (300 requests/min/IP) resets on restart; single instance only.
6. **INFO — Classic screens** moved to `/classic` and now need the admin key; `/` is the public viewer site.

## Screenshots (`docs/qa/`)
* viewer-dark-home.png
* viewer-dark-matches.png
* viewer-dark-match_5_prediction.png
* viewer-dark-match_5_fantasy.png
* viewer-dark-match_5_xi.png
* viewer-dark-match_5_weather.png
* viewer-dark-match_6_live.png
* viewer-dark-match_6_graphs.png
* viewer-dark-match_6_fow.png
* viewer-dark-match_6_partnerships.png
* viewer-dark-match_6_scorecard.png
* viewer-dark-match_6_commentary.png
* viewer-dark-match_1_result.png
* viewer-dark-match_1_h2h.png
* viewer-dark-experts.png
* viewer-dark-ai.png
* viewer-dark-accuracy.png
* viewer-dark-settings.png
* viewer-dark-assistant.png
* viewer-dark-telugu-prediction.png
* admin-dark-signin.png
* admin-dark-dashboard.png
* admin-dark-master.png
* admin-dark-matches.png
* admin-dark-results.png
* admin-dark-predictions.png
* admin-dark-experts.png
* admin-dark-import.png
* admin-dark-providers.png
* admin-dark-accuracy.png
* admin-dark-audit.png
* admin-dark-roles.png
* admin-dark-settings.png
* viewer-light-home.png
* viewer-light-match_5_prediction.png
* viewer-light-match_6_live.png
* admin-light-signin.png
* admin-light-dashboard.png
* admin-light-master.png
* admin-light-predictions.png

## Cricsheet importer
Tested with synthetic files in the exact Cricsheet JSON layout: win by runs, tie decided by Super Over, no result, D/L win, Test match skipped; re-import adds nothing; one player row per Cricsheet person id; bowler not charged leg-byes; wides not counted as balls faced; attribution visible on viewer scorecard and Data sources. Screenshots: viewer-dark-cricsheet-scorecard.png, viewer-dark-data-sources.png, admin-dark-cricsheet.png.

## Not verified
* A real download from cricsheet.org: this workspace's network blocks it, so the first real import must run on the server.
* Staging deployment (needs your approval), physical Android device, Firefox/Safari.
* Real league data: the six league Google Sheets returned "permission denied" to this session.
