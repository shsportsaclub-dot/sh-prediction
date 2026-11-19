# SH PREDICTION API v1

Base: `https://sh-prediction.onrender.com/api/v1`

**Who can call what.** Viewer endpoints are public (no login). `/me/*` and follows need a Bearer session.
`POST /predictions` needs a verified expert session or the admin key; the prediction stays private until an admin publishes it.
Everything under `/admin/*` needs `X-Admin-Token` and is checked in the backend on every call.
Before the database migration has been run, every endpoint except `/i18n/*` and `/admin/system/*` answers 503 `MIGRATION_PENDING`.

**Errors.** `{"error":{"code","message"}}` — `VALIDATION_ERROR` 400, `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `NOT_FOUND` 404,
`MATCH_STARTED` / `DUPLICATE` / `ALREADY_RECORDED` / `ALREADY_LOCKED` / `ALREADY_PUBLISHED` / `NOT_LOCKED` / `IMMUTABLE` / `INNINGS_CLOSED` / `HAS_LOCKED_PREDICTIONS` / `NOT_CONFIGURED` / `DISABLED` 409,
`RATE_LIMITED` 429, `MIGRATION_PENDING` 503. **Paging** `limit` 1–100, `offset`. **Rate limit** 300/min/IP.
**Datasets** `dataset=verified` (default) or `dataset=demo`; a response never mixes the two.

## Viewer API (public)
| Method | Path | Notes |
|---|---|---|
| GET | `/matches` | `status=live|upcoming|completed`, `competition_id`, `team_id`, `date`, `q`, paging |
| GET | `/matches/{id}` | info, venue, weather, pitch, toss, result, head-to-head, form, Playing XI, squads |
| GET | `/matches/{id}/predictions` | **published** predictions only, with evaluation |
| GET | `/matches/{id}/signals` | SH AI win probability, public factors (no weights), projections, live probability, over-by-over, phases, wicket impact, turning points |
| GET | `/matches/{id}/scorecard` · `/commentary` · `/partnerships` · `/fall-of-wickets` · `/graphs` · `/result` | Match Center sections |
| GET | `/matches/{id}/fantasy` (`rule_set`) · `/fantasy-history` | free-to-play suggestions |
| GET | `/experts`, `/experts/{id}/history` | ranked on published tips |
| GET | `/analytics/accuracy` · `/toss` · `/home-away` · `/venue` | published predictions only |
| GET | `/competitions`, `/teams`, `/languages`, `/i18n/{code}` | `coverage_percent` is honest |
| GET | `/sources` | data sources, licences and Cricsheet attribution |
| POST | `/assistant` | `{"question","language"}` → grounded answer + sources |
| GET | `/data/fixtures` · `/data/results` · `/data/live` · `/data/history` | Cricket Data Gateway (cached) |
| GET | `/data/scorecards/{id}` · `/data/commentary/{id}` · `/data/squads/{id}` · `/data/playing-xi/{id}` | |
| GET | `/data/players/{id}/stats` · `/data/teams/{id}/stats` · `/data/venues/{id}/stats` | |

## User / expert
| Method | Path | Notes |
|---|---|---|
| GET / PUT | `/me/preferences` | language, theme, favourites |
| POST | `/experts/{id}/follow` | |
| POST | `/predictions` | verified expert (or admin with `expert_id`) |
| POST | `/predictions/{id}/lock` | owner expert or admin, before start |

## Admin API (`X-Admin-Token`)
| Method | Path | Notes |
|---|---|---|
| GET | `/admin/dashboard`, `/admin/monitor`, `/admin/audit` | |
| GET | `/admin/master-list` | actual results master: Match, Home, Away, Toss, Winner |
| GET | `/admin/predictions` | full register incl. drafts, unpublished; filters `status`, `published`, `match_id`, `source_type` |
| POST | `/admin/predictions/{id}/lock` · `/publish` · `/unpublish` | unpublish needs `reason` |
| POST | `/admin/matches` · `/admin/matches/{id}` (edit) · `/squad` · `/playing-xi` · `/scorecard` · `/model-prediction` · `/fantasy` | |
| POST | `/admin/teams`, `/admin/players`, `/admin/player-stats` | |
| POST | `/admin/toss`, `/admin/results`, `/admin/ball-events` | revisions need `reason` |
| POST | `/admin/experts`, `/admin/experts/{id}/verify` | |
| GET / POST | `/admin/users`, `/admin/users/{id}/role` | roles: user, expert |
| GET / POST | `/admin/settings`, `/admin/fantasy/rules`, `/admin/model-versions` | |
| GET / POST | `/admin/providers`, `/admin/providers/{name}`, `/admin/providers/{name}/sync` | keys never stored here |
| POST | `/admin/import` | CSV, dry run unless `commit: true` |
| GET / POST | `/admin/cricsheet`, `/admin/cricsheet/import` | `{"file": "ipl"|"bbl"|"wbb"|"wpl"|"npl"|"ilt"|"t20s"|"recent_2"|"recent_7"|"recent_30"|"all", "limit"}` → 202, runs in the background on our server |
| POST | `/admin/player-stats/rebuild` | career figures per format from stored scorecards |
| GET | `/admin/accuracy`, `/admin/calibration` | all locked predictions; walk-forward backtest |
| GET / POST | `/admin/system/status`, `/admin/system/migrate` | `{"confirm": true}` → verified backup, then migrate |

## Settlement rules (ICC Men's T20I playing conditions, clause 16)
* Winner: `win` / `awarded` → winner; `tie_super_over` → Super Over winner; `tie` (no Super Over), `no_result`, `abandoned`, `canceled` → **void**.
* Toss: settles whenever a toss happened, even if the match later had no result; no toss + abandoned/canceled → void.
* Score projections: correct when within ±10% of the actual innings total.
* A pre-match prediction locked at or after the scheduled start is **ineligible**.
* `Accuracy = Correct / (Correct + Incorrect) × 100`; pending, void and ineligible are excluded.
* Revising a result supersedes the old evaluation (kept with `superseded_at`); predictions themselves never change.
