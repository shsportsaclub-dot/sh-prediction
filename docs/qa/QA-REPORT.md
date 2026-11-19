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
