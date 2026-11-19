# SH PREDICTION API v1

Base: `https://sh-prediction.onrender.com/api/v1`

**Auth.** `Authorization: Bearer <session token>` (from `/auth/generate` + `/auth/verify`) for reads.
`X-Admin-Token: <SH_PREDICTION_ADMIN_TOKEN>` for `/admin/*`. Verified experts (or admin) may `POST /predictions`.
Public: `GET /languages`, `GET /i18n/{code}`.

**Errors.** `{"error":{"code":"VALIDATION_ERROR","message":"..."}}`. Codes: `VALIDATION_ERROR` 400, `UNAUTHENTICATED` 401,
`FORBIDDEN` 403, `NOT_FOUND` 404, `MATCH_STARTED` / `DUPLICATE` / `ALREADY_RECORDED` / `ALREADY_LOCKED` / `IMMUTABLE` / `INNINGS_CLOSED` 409, `RATE_LIMITED` 429.

**Paging.** `limit` 1–100 (default 50), `offset` ≥ 0. Responses carry `items`, `total`, `limit`, `offset`.
**Rate limit.** 300 requests / minute / client IP.
**Demo data.** Rows with `data_origin = "demo"` are hidden unless `include_demo=1` is passed, and never count in headline accuracy.

## Read
| Method | Path | Notes |
|---|---|---|
| GET | `/matches` | `status=live|upcoming|completed`, `competition_id`, `team_id`, `date=YYYY-MM-DD`, `q`, paging |
| GET | `/matches/{id}` | match info, toss, result, venue, weather, pitch, head-to-head, last-5 form, playing XI, squads |
| GET | `/matches/{id}/scorecard` | innings with overs, target, player figures, fall of wickets |
| GET | `/matches/{id}/commentary` | ball events newest first, paging |
| GET | `/matches/{id}/predictions` | locked predictions + current evaluation + live versions |
| GET | `/matches/{id}/signals` | pre-match model (probabilities + factors), first-innings projection, live probability, live history, turning points |
| GET | `/master-list` | approved 5-column list; `competition_id` |
| GET | `/competitions`, `/teams` | teams return `short_code` only when approved |
| GET | `/experts` | ranked; accuracy per expert |
| GET | `/experts/{id}/history` | summary + every tip with its evaluation |
| GET | `/analytics/accuracy` | overall, by type, league, expert, model, team; `prediction_type` filter |
| GET | `/analytics/toss` | toss winner vs match winner, batting first vs chasing |
| GET | `/analytics/home-away` | home vs away, day of week (UTC) |
| GET | `/analytics/venue` | per-venue batting-first record |
| GET / PUT | `/me/preferences` | `language_code`, `theme`, `favorite_team_ids`, `favorite_competition_ids` |
| GET | `/languages`, `/i18n/{code}` | public |

## Write
| Method | Path | Who | Body |
|---|---|---|---|
| POST | `/predictions` | verified expert, admin (with `expert_id`) | `match_id`, `prediction_type` (`toss`, `winner`, `first_innings_score`, `second_innings_score`, `live_winner`), `predicted_team_id` or `predicted_value`, `confidence` 0–100, `explanation`, `lock` (default true) |
| POST | `/predictions/{id}/lock` | owner expert, admin | `{}` — only before the scheduled start |
| POST | `/experts/{id}/follow` | user | `{"follow": true|false}` |
| POST | `/admin/teams` | admin | `name`, `short_code` (2–5 A–Z/0–9, unique), `approve_code` |
| POST | `/admin/matches` | admin | `competition`, `home`, `away`, `start_utc` (with timezone), `source`, optional `season`, `venue`, `city`, `match_no`, `format`, `weather`, `pitch_report`, `data_origin`, `provider` + `provider_id` |
| POST | `/admin/matches/{id}/model-prediction` | admin | `{}` — stores the locked model prediction once per model version |
| POST | `/admin/toss` | admin | `match_id`, `winner_team_id`, `decision` (`bat`/`bowl`), `source`, `reason` (required to revise) |
| POST | `/admin/results` | admin | `match_id`, `result_type` (`win`, `tie_super_over`, `tie`, `no_result`, `abandoned`, `canceled`, `awarded`), `winner_team_id` (only for win / tie_super_over / awarded), `margin`, `method` (e.g. DLS), `source`, `reason` to revise |
| POST | `/admin/ball-events` | admin | `match_id`, `innings_no`, `seq`, `runs_bat`, `extras`, `extra_type`, `is_wicket`, `wicket_kind`, `batting_team_id` + `target` on the first ball of an innings, `commentary` |
| POST | `/admin/experts` | admin | `display_name`, `phone`, `country`, `language_code`, `bio`, `contact_url` (https) |
| POST | `/admin/experts/{id}/verify` | admin | `{"verified": true|false}` |
| POST | `/admin/demo-seed` | admin | creates labelled DEMO data |
| GET | `/admin/audit`, `/admin/monitor` | admin | audit trail; table counts and migrations |

## Settlement rules (ICC Men's T20I playing conditions, clause 16)
* Winner: `win` / `awarded` → winner; `tie_super_over` → Super Over winner; `tie` (no Super Over), `no_result`, `abandoned`, `canceled` → **void**.
* Toss: settles whenever a toss happened, even if the match later had no result; no toss + abandoned/canceled → void.
* Score projections: correct when within ±10% of the actual innings total.
* A pre-match prediction locked at or after the scheduled start is **ineligible**.
* `Accuracy = Correct / (Correct + Incorrect) × 100`; pending, void and ineligible are excluded.
* Revising a result supersedes the old evaluation (kept with `superseded_at`); predictions themselves never change.
