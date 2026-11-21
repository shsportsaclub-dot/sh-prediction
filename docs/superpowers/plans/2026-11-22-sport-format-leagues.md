# Sport → Today → Format → League

Owner correction: default Cricket, Today and all formats/statuses. Changing sport resets format, league and date to Today. Format selection then narrows league choices; league selection narrows matches. Include stable sport selection even when source data is absent. Use Overview/Live/Schedule/Fixtures/Results consistently.

Root cause: prior page derived its sport/league/format controls solely from the nine-row football consumer snapshot. Cricket already has a separate public catalogue in Prediction (1562 observed rows, 60 upcoming at inspection); it was never connected to this schedule. Formats also ignored the selected competition. Existing cricket records include historical Cricsheet rows and optional third-party/owner feeds: preserve provenance and do not count them as independent SH DATA LINE acquisition.

- Add a read-only unified schedule API over existing cricket tables and the separate owned football receipts, with server-side viewer-local date filtering, pagination and full-scope option counts. No source acquisition, key or prediction-rule changes.
- Preserve unknown/date-only Cricsheet start times as unknown; exclude invented midnight from daily schedules. Include current multi-day matches only with fresh source score evidence, with their original start and ongoing-day distinction.
- Default sport S001, Today, Overview, all formats. Provide stable 45-sport registry, declared sport-specific format options with observed counts and actual leagues after date/format selection. Do not invent leagues or connected feeds for unsupported sports.
- Reuse existing SH cricket match centre via its own match route; audit user's separate owned Scoring Heroes source for exact reusable format/advanced modules. Other sports get an own-panel match centre with real facts and explicit unavailable live/statistical sections.
- Add backend tests for hierarchy, midnight boundaries, demo exclusion, stale live exclusion, namespace/provenance and pagination; Node tests for defaults/reset/cascade; full regression, review, LIVE/browser verification and evidence.

Today's schedules and current-league coverage remain limited to actually stored/authorized observations. Registered format names and sport IDs are not proof of connected live sources or implemented scoring processors.
