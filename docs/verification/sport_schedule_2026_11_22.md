# Sports schedule verification — 22 November 2026 (Asia/Kolkata)

## Shipped

- `1597c6359ff85edef470c27ca02cf4feaffae36d`: 45 stable sport choices, Cricket default, viewer-local Today, all formats initially, format → actual leagues cascade, full-set metadata before pagination, source-separated public schedule API and owned cricket match-centre routing.
- `68f428320d95b178c1e323d92a2ce12f260f114d`: main Schedule navigation reaches the sports schedule; renamed misleading football-only entry; Info tab now uses the selected SH timezone consistently with the match header.
- Render LIVE deployment `dep-dc0ufmm0tbcc73a55e2g`, finished 2026-11-21 18:51:11 UTC (22 November 00:21:11 IST). Health returned 200, build `68f428320d95`.

## Validation actually run

- Full local Python regression: **173 tests passed**, 27.608 seconds. Compileall passed.
- Node schedule behaviour, demo OTP and viewer timezone tests passed; JS syntax checks passed.
- New match Info timezone regression reproduced device-time rendering and passed after the correction. Added to CI along with the schedule client test.
- CI `44937315907` and `44937659188`: completed/success. Final runtime CI compile, schedule client behaviour and full server regression steps all succeeded.
- Read-only code review found no critical issues; reported that periodic polls discarded extra loaded pages. Fixed polling to refresh the loaded extent.
- All hub inline scripts passed Node syntax validation; the current remote hub/shell/insights blobs were reacquired before the follow-up edit to preserve concurrent changes.

## Observed production behaviour

See `sport_schedule_api_2026_11_22.json` for actual HTTP responses.

- Cricket Today in Asia/Kolkata: **13 stored records**, 8 leagues/series; Test 6, ODI 2, T20 4, Other 1. Includes source-reported ongoing matches with recent score/scorecard fetches; this is not independently verified live acquisition.
- T20 selection: **4 records** and exactly three applicable leagues. WBBL selection: **2 records** and only the two WBBL teams/matches rendered.
- Format options include Test, ODI, T20, T10, The Hundred and Super Six; zero-count options do not imply matches or engine readiness. Native source format labels remain intact.
- Selecting Football resets to Today/all formats/all leagues and produces no collected matches for today. All dates shows **9** independent OpenLigaDB football fixtures and their one competition.
- Selecting Tennis resets filters and shows only tennis format choices, with an explicit missing-source notice and no cricket records.
- Cricket All dates: **1,570 records at the time of this check**. First page rendered 200, Load more rendered 400; later observation after the poll boundary still rendered 400. The live catalogue can change independently of this code.
- Clicking Brisbane Heat Women vs Adelaide Strikers Women opens owned `/#/match/160`. Existing tabs rendered: Info, Fantasy XI, Discussions, Commentary, Live, Scorecard, History, Graphs, Points Table, Playing XI, Results & Stats and Prediction. This verifies navigation/tab rendering, not complete underlying data for each feature.
- Header and Info both show **22 November, 10:10 AM GMT+5:30** for that match, matching the selected timezone.
- Main Schedule link opens `/sports-fixtures`, returning Cricket Today/all formats. Final visible tabs: Overview, Live, Schedule, Fixtures and Results.
- Legacy `/fixtures` remains admin protected (403). Invalid sport returns 400. Existing `/api/provider-fixtures` still returns 9 records.
- Error/Traceback log filter after final runtime became LIVE returned no matching app logs in the checked interval.

## Failures and limits retained

During disk-service deployments, early probes observed transient 502 responses and the browser showed schedule unavailable. After the final deployment became LIVE, reload and all recorded API/UI checks succeeded. No retry of CI or hidden test failure was used to obtain the green runs. Browser extension metadata errors were observed; these are extension messages, not SH application exceptions.

Full owned Scoring advanced-feature parity remains unverified. Read `docs/OWNED_SCORING_REUSE.md` for the audited modules, format contract differences and remaining Hundred arithmetic work. This change reuses the owned format catalogue and existing owned Prediction match centre, not the entire Scoring monolith. No scoring/prediction rules or source acquisition settings were changed.

Existing cricket subscriptions/sheets remain separate from SH DATA LINE independent acquisition. No worldwide fixture coverage, tennis collection, licensed independent live balls, one-second latency or complete squads/media is claimed. Existing source inaccuracies, stale source statuses and missing fixtures cannot be repaired by adding filters.
