# SH Universal Cricket Data Gateway

All cricket data enters through one gateway and is stored in our own normalized tables with our own IDs. Each record keeps its `source`, `data_origin` (`verified`, `imported`, `demo`) and, for outside providers, a row in `data_provider_syncs` (provider + provider ID → our ID) so the same match is never stored twice.

## Three separate kinds of data (never mixed)
| Kind | Tables | Who writes |
|---|---|---|
| Actual results | `toss_results`, `match_results`, `innings`, `ball_events`, scorecards | admin / own scoring / imports |
| User & expert predictions | `predictions` (+ `prediction_versions`, `prediction_publications`), social prediction posts | tipsters, experts — locked before the start, never edited |
| SH AI predictions | model predictions with `model_version_id` | our engine |

Accuracy = Correct ÷ (Correct + Incorrect) × 100. Pending, void (tie without Super Over, no result, abandoned, canceled per ICC Men's T20I playing conditions clause 16) and late picks (locked at or after the start) are excluded.

## Adapters
| Adapter | Status | Notes |
|---|---|---|
| SH own scoring | ✅ live | Admin enters each delivery (`/admin/ball-events`). Each ball updates innings totals, scorecard, fall of wickets, partnerships, run rates, live win probability and player stats; publishes `ball` + `probability` events to the SSE stream; commentary is generated in the viewer's language. Laws checks: wides/no-balls carry ≥1 extra and are not legal balls (Laws 21–22), duplicate sequence numbers rejected. |
| Cricsheet historical | ✅ (tested with Cricsheet-format files) | Free ball-by-ball data, **Open Data Commons Attribution 1.0** — attribution shown on every imported match. Only allow-listed zips from cricsheet.org; incremental (skips known Cricsheet IDs, updates corrected files), limited-overs matches only. Not live: data appears after a match ends. This workspace cannot reach cricsheet.org, so the first real download must run on the server (Admin → Cricsheet). |
| Owner master list | ✅ | Abu Dhabi T10, 30 matches from your prototype, stored as `imported` with source "user-supplied, not independently verified". Dates were not supplied: admin enters the first start. |
| CSV import | ✅ | Dry run first; rolled back on any error. |
| Authorized external live feed | ⬜ placeholder | Interface ready (`gateway.py`). No provider connected: none was bought, and we do not scrape sites, bypass logins, anti-bot controls or private APIs. Without a feed, live screens say "No ball-by-ball data… live data appears only for matches scored in SH PREDICTION or received from an authorized feed." |

## Live event processing
`live_events` table + `/api/v1/matches/{id}/stream` (Server-Sent Events). Events: `status`, `ball` (score, overs, commentary), `probability`. Clients resume with `Last-Event-ID`; heartbeat every 15 s. The viewer Live tab subscribes automatically.

## Commentary engine (original)
`commentary.py` writes commentary from the recorded event only (runs, extras, wicket kind, milestones, partnerships, required rate, probability swings) in English, Hindi and Telugu; other languages fall back to English and say so. It never invents events: missing names become "the batter"/"the bowler".

## Statistics
Player statistics are rebuilt from ball events (runs, balls, 4s, 6s, wickets, economy, strike rate) after each completed innings and after imports. Team, venue, toss, batting-first-vs-chasing and head-to-head statistics are computed from verified results only; demo data is kept apart.
