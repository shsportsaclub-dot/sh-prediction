# SH PREDICTION — Implementation Contract v1 (2026-11-19)

## Ground truth and scope
This document governs changes to the EXISTING Python app, not a separate mockup. Repository: shsportsaclub-dot/sh-prediction. Running server: python app/main.py. README confirms / and /admin-panel, app/api_v1.py, app/gateway.py, backed-up migration flow and tests. SH PREDICTION is independent of Scoring Heroes. Existing features and user data must be preserved.

## Non-negotiable visual/product contract
1. Global app: information-rich Cricbuzz-inspired *functional hierarchy*, not its copied appearance. Preserve two top-level sections CRICKET and WORLD, with For You / Live / Upcoming / Finished and access to series, teams, players, rankings, news, and search.
2. Match center: CREX-inspired *functional depth*, original SH styling, never copied assets or exact visual composition. A compact persistent match header shows competition, teams, score, overs, state, target/lead/trail/session when applicable, and data freshness.
3. Navigation is NOT one long row of unlimited tabs and NOT a long page of all tables. Use hierarchical route-driven MAIN TAB -> SUBMENU -> SUBTAB -> ONE functional view. Main tabs: Overview, Live, Scorecard, Prediction, More. Each submenu exposes relevant subtabs only. Back navigation returns to prior level; URLs are deep-linkable; active tab survives refresh.
4. Overview groups: Match Summary (summary, match info, key moments); Pre-Match (weather, toss, pitch, venue); Insights (H2H, form, team strength). Live groups: Live Center (score, batters, bowlers, over); Commentary (all balls, boundaries, wickets, over summary); Analysis (win probability, momentum, run rate). Scorecard groups: Innings (format-appropriate innings); Batting (dismissals, extras); Bowling (spells, economy); Partnerships (partnerships, fall of wickets). Prediction groups: Match Prediction (winner, projected score, chase/defend); Toss & Pitch (toss, pitch impact, venue); Advanced (matchups, confidence, prediction history). More groups: Teams (XI, squads, comparisons); Statistics (graphs, records, venue); Extras (fantasy, highlights, SH Social, virtual live, broadcast). Menus may expand through data-driven configuration without adding an unbounded top row.
5. Data contracts for each subtab: loading, loaded, partial, unavailable, error, stale. Never render invented data or a blank unlabelled screen. Explicitly distinguish actual scores, sourced statistics, model estimates, and illustrative reconstructions. Tests must check navigation and empty states.
6. CricketData: use existing paid subscription (renewal reported as Nov 28); do not assume free-plan limits or entitlement. Server-only CRICKETDATA_API_KEY. Inspect actual plan and endpoint responses before enabling scorecard/squads/commentary. currentMatches adapter exists in app/gateway.py; do not claim all feeds work. Implement caching, throttling, dedupe, provenance, and quota observability. No unauthorized CREX scraping.
7. Universal language selection, saved preference, accessible mobile-first responsive layouts, RTL support; never mix languages unnecessarily. Keep current language support functioning while extending it.

## Ordered implementation (do not skip)
P0: inspect current routes, CSS/HTML, provider mapping, DB, migrations, test suite and deployment; capture baseline. Confirm durable verified backup before any production migration. Verify service storage persistence. Never expose tokens.
P1: implement hierarchical navigation and routing against existing match pages; create actual browser screens backed by real components and real API data states. No AI-generated concept screens. Keep old routes functional.
P2: implement cricket/world home, match lists and filtering, compact match header, scorecard and commentary with verified provider data; show unavailable states for unsupported fields.
P3: pitch/toss/weather/H2H/graphs/prediction/fantasy and cross-linked team, player, series, venue pages, sourced statistics and explanation.
P4: SH Social, Virtual Live, broadcast integrations and universal localization; do not imply replay accuracy without event tracking data.

## Deployment and proof gate
For EACH phase: implement actual code; run unit tests and browser navigation checks; commit to GitHub; verify Render deployment is live at that commit; open the deployed URL and capture screenshots of the *running code*. Only these screenshots may be shown to the owner. A generated image, wireframe, or local un-deployed HTML preview is NOT proof. If deployment, API, or migration is blocked, report exact blocker and don't invent screenshots or successful results.

## Acceptance checklist
[ ] Baseline routes and production migration verified
[ ] Nested main/submenu/subtab navigation and browser back work
[ ] Cricket/World main sections and real match list work
[ ] Live and scorecard show verified data or explicit unavailable states
[ ] Commentary and charts correctly handle absent source data
[ ] Existing admin, predictions, social, and other features preserved
[ ] Responsive mobile QA and accessibility checks pass
[ ] Render live commit verified; actual browser screenshots captured
