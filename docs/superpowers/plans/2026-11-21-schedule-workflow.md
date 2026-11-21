# Schedule workflow implementation

Owner requests Cricbuzz-style functional behaviour for SH fixture schedules. Reference pages were inspected for current/live/upcoming/recent, matches-by-day and competition navigation. Implement independent SH UI with existing licensed SH DATA LINE records; no reference-site data ingestion or extra coverage claims.

- Keep the existing read-only provider/consumer pipeline and legacy admin routes intact.
- Add All / Live / Upcoming / Results tabs; verify live-state flags rather than inferring action from scheduled times.
- Group by selected viewer-local calendar day, then competition; filter sport, series/competition, exact source format, date, Today, Tomorrow, next seven days and team/competition search. Unknown times and formats remain explicit.
- Encode shareable filters in URL parameters and support back/forward. Keep saved viewer timezone and AM/PM; include selected timezone aliases in options.
- Add a fixture-info view using available facts only. No invented scorecard, venue, scores, squads, category/gender or commentary.
- Add pure client regression tests for day boundaries, DST, repeated filters, verified live state, unknown values, exact format preservation and grouping; verify actual deployed tab/filter/date/detail behaviour in browser.
- Full backend regression, JavaScript checks, code review, commit with expected head, LIVE deployment, CI and saved evidence.

Current feed remains nine football fixtures from one Bundesliga matchday. Sport/format/competition filters are data-driven; options do not imply uncollected sources exist. Existing cricket match browsing remains linked and separate from SH independent acquisition.
