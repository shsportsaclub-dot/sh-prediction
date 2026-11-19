# SH PREDICTION — inventory against Master Development Script V1.0

Baseline audited: commit `8166499` (Python stdlib server + SQLite + single-file web app + Android WebView shell).
This batch: **Batch 02 — V1 foundation** (normalized schema, `/api/v1`, engines, Hub screens, tests).

Legend: ✅ done and tested · 🟡 partial (works, but needs data or more UI) · ⬜ not started

| § | Module | Status | What exists now | What is still missing |
|---|---|---|---|---|
| A | Home | ✅ | Live / Upcoming / Completed filter, search, accuracy summary, favourite competitions (saved to profile) | "Featured" flag is admin-set only |
| B | Global Match Center | 🟡 | Info (venue, toss, result, weather, pitch, H2H, form, source), Playing XI/squads, Predictions, AI, Live, Scorecard, Commentary | Match graphs beyond live-probability line; needs a licensed data feed to fill squads/scorecards automatically |
| C | Expert Tips | 🟡 | Profiles, verification, country/language, ranking by accuracy, history with correct/incorrect, follow, contact link | Expert self-registration screen; expert-side prediction form (API ready: `POST /api/v1/predictions`) |
| D | AI Prediction Engine | 🟡 | Explainable `sh-baseline 1.0.0`: winner probability with 4 factors, toss = fair coin, first-innings projection (≥3 venue samples), confidence level, model versioning | Over-by-over / session projections, player projections (need player data) |
| E | Live Prediction Engine | ✅ | Ball-by-ball probability, CRR/RRR, wicket impact, partnership, last-12-ball momentum, turning points, append-only live history | Batter-vs-bowler matchups need player-level ball data |
| F | Fantasy Intelligence | ⬜ | `fantasy_teams` table only | Whole module (next batch; free-to-play, no money) |
| G | Prediction Accuracy | ✅ | Total/correct/incorrect/pending/void, overall, by type/league/expert/team/model, toss vs winner, batting first vs chasing, home/away, day of week, venue | Historical trend chart over time |
| H | AI Cricket Assistant | ⬜ | — | Whole module (next batch) |
| I | Administration | 🟡 | API: teams + short-code approval, matches (dedupe + provider IDs), toss/result record and audited revision, ball events, experts + verification, audit log, monitor, demo seed | Admin **screens** for the new v1 actions (classic Admin screen still covers v0 fixtures/predictions/outcomes) |
| §3 | Approved Master List | ✅ | Exactly 5 columns, H/A + approved short code, font colours only, Predictions / Results views, grey "—" for unknown | Import of the six league Google Sheets (no access — see report) |
| §4 | Prediction integrity | ✅ | All 14 required fields, lock before start, DB triggers block edits/deletes, live = new versions, evaluations kept separately with history | — |
| §5 | Database | ✅ | All 29 tables + `expert_follows`, versioned migrations, provider mapping uniqueness | — |
| §6 | API | ✅ | All 14 listed endpoints + extras, auth, roles, validation, pagination, rate limit, structured errors | OpenAPI file (docs/API.md is hand-written) |
| §7 | Languages | 🟡 | 24 languages registered, English/Hindi/Telugu UI complete, others fall back to English, preference saved per user across devices, RTL support | Translations for the other 21 languages; AI Assistant answers |
| §8 | UI/UX | ✅ (Hub) | Original design system, dark/light, loading/empty/error/retry/offline, ARIA labels, hash routing so Android back works | Classic screens still use the older style |
| §10.7 | Data providers | 🟡 | `data_provider_syncs` + duplicate-safe import endpoint | Live connector to a licensed provider (key must be set on Render) |
