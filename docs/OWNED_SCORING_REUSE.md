# Owned Scoring reuse audit — 22 November 2026 (Asia/Kolkata)

Owner authorized reuse of owned Scoring code. Inspected the current SH repositories and Render service before changing the consumer schedule.

- `scoring-heroes` main `d688347b1936a417361a58b1e131e738c6119c4a` is an Android wrapper, not the scoring implementation.
- Actual owned scoring implementation: `mename-shs-backend` main `a2ef126218753c6f79fcfc42c3e5822e7ef31acd`, Render `scoring-heroes-api` (`srv-db74t30u01pc73c9920g`).
- `app-index.html:3828–3850` contains the sport/format catalogue. Reused labels in `app/scoring_format_catalogue.json`, with source commit retained. Cricket Super Six is the owner's requested label; the owned wizard supports custom six-over configuration. Native source labels remain unchanged.
- Owned Hundred setup uses five-ball sets, 100 balls and a 25-ball powerplay. Owned wizard supports custom overs and multiday configuration.
- Owned pure modules include `pulse-model.cjs`, `match-intelligence.cjs`, `score-update-commentary.cjs`, `match-journal.mjs`, and `recent.mjs`. Their global UI/data contracts differ from Prediction and are not transplanted wholesale.

## Implemented boundary

`/sports-fixtures` now reads `/api/sports-schedule`, including existing non-demo cricket catalogue records and the separate independent football receipt lane. Default Cricket → viewer-local Today → all formats/leagues. Format selection narrows actual league options across the full filtered set before pagination. Changing sport resets filters/date to Today. All 45 stable sport IDs are selectable, with missing source coverage explicit.

Cricket Match centre links route to the existing owned `/#/match/<id>` UI. This retains its existing live timeline/SSE, scorecards, squads, graphs, insights and match information implementation. No separate imitation centre or fabricated data is created. Football fixture-only details explicitly report that score/timeline observations have not been supplied.

## Remaining work; not certified by this release

Full advanced scoring parity has not been established. The owned pulse model currently assumes six balls for completeness; Hundred requires a parameterized adapter. Prediction display paths also contain six-ball overs conversion and a 17-over Hundred graph quota. Feed notation must be explicit before changing these calculations. Graphs/projections, journal revisions, end-of-over reconciliation and sport-specific scoring need individual contract tests before shared model integration.

Existing cricket source reports are not SH DATA LINE independent acquisition. This release does not add global discovery, tennis feeds, genuine live collection or permission to redistribute another source. Live status is only shown as current when a recent score/scorecard observation and plausible start date support the source report; independent live verification remains false. Date-only Cricsheet records retain source dates and are excluded from timed daily schedules.

No prediction eligibility rules, source credentials, scoring writes or acquisition settings change in this release.
