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

## Accounts (SH SOCIAL) — added in Batch 04
Sessions are `Authorization: Bearer <token>` from `/auth/login`. Passwords: PBKDF2-SHA256, 10+ characters with upper, lower and a digit.
Codes (email verification, password reset) are 6 digits, stored hashed, valid 15 minutes, sent only by email; **the API never returns them** (except when the developer-only flag `SH_DEV_EXPOSE_CODES=1` is set for automated tests). Five wrong passwords lock the account for 15 minutes. Phone-number login is disabled in production (`/auth/generate` answers 410).

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `username`, `email`, `password`, `display_name?` → 201; verification email sent (or queued in the outbox if SMTP is not configured) |
| POST | `/auth/verify-email` | `login`, `code` |
| POST | `/auth/resend-verification` | `login` |
| POST | `/auth/login` | `login` (username or email), `password` → `token` |
| POST | `/auth/logout` | ends this session |
| POST | `/auth/request-password-reset` | `login`; same answer whether or not the account exists |
| POST | `/auth/reset-password` | `login`, `code`, `new_password`; signs out every session |
| GET | `/me` | own account |
| POST | `/me/profile` | `display_name`, `bio`, `private_profile`, `avatar_media_id`, `cover_media_id` |
| POST | `/me/password` | `current_password`, `new_password` |
| POST | `/me/delete` | `password`; removes profile, posts and media; locked prediction records stay, anonymised |
| POST | `/me/tipster-application` | viewer → pending tipster (admin approves) |
| GET | `/me/notifications`, POST `/me/notifications/read` | `ids` list or `"all"` |
| GET | `/me/dashboard` | creator analytics: posts, views, watch time, completion rate, likes, comments, shares, saves, followers, daily/monthly trends, prediction performance |
| GET | `/me/blocked` | |

## Media uploads (resumable)
| Method | Path | Notes |
|---|---|---|
| POST | `/media/uploads` | `kind` image/video, `purpose` post/reel/avatar/cover, `mime`, `bytes`, `filename` → `media_id`, signed `upload_url` (1 h), `chunk_bytes` |
| PUT | `/media/uploads/{id}?exp&sig` | raw bytes with `Content-Range: bytes a-b/total`; resume from `received_bytes` |
| GET | `/media/uploads/{id}` | status `uploading/processing/ready/failed/removed`, renditions, fresh `upload_url` |
| POST | `/media/uploads/{id}/complete` | type check by file signature, virus-scan hook, queues processing |
| GET | `/media/{id}/{file}` | served with Range support; only ready media of public posts, or to owner / followers / admin |

Limits: image 15 MB, video 200 MB, post video 180 s, reel 90 s (admin settings). Processing: photos → EXIF removed, 1080 px + 320 px JPEG; videos → H.264 MP4 (faststart), thumbnail, HLS 360p/720p; reels → 720×1280.

## Social
| Method | Path | Notes |
|---|---|---|
| GET | `/social/feed` | `feed=for_you|following|latest|trending|reels|match|hashtag|user|saved|search`, with `match_id`, `tag`, `username`, `q`, paging |
| GET | `/social/hashtags/trending`, `/social/leaderboard?board=accuracy|volume|recent|followers|engagement`, `/social/search/users?q=` | |
| GET | `/social/posts/{id}`, `/social/posts/{id}/comments`, `/social/posts/{id}/edits` | |
| GET | `/social/users/{username}`, `/followers`, `/following`, `/predictions` | accuracy is computed from locked picks only |
| POST | `/social/posts` | `kind` text/analysis/pitch_report/playing_xi/fantasy/photo/video/reel/poll/prediction/toss_prediction; `body`, `media_ids`, `match_id`, `options` (poll), `prediction_type`, `predicted_team_id`, `confidence`. Needs a verified email. Prediction posts: tipsters only, pre-match only, create a separate locked pick |
| POST | `/social/posts/{id}/view|watch|like|unlike|save|unsave|share|comments|vote|edit|delete` | view = one per viewer per post per UTC day, own views excluded; watch `watched_ms` (≥90% = completed) |
| POST | `/social/users/{username}/follow|unfollow|block|unblock` | |
| POST | `/social/reports` | `target_type` post/comment/user, `target_id`, `reason` |
| GET | `/matches/{id}/community` | SH AI (separate) + tipster picks + verified result + match posts |
| GET | `/matches/{id}/replay` | real recorded deliveries as animation directives, labelled reconstruction |
| GET | `/matches/{id}/stream` | Server-Sent Events: `ball`, `probability`, `status`; resumes with `Last-Event-ID` |
| POST | `/game/simulate` | `format` T10/T20/ODI, optional teams, `seed`; virtual result, never mixed with real data |
| GET | `/game`, `/game/{id}` | |

## Admin (SH SOCIAL)
| Method | Path | Notes |
|---|---|---|
| GET | `/admin/social/users?q=`, `/admin/social/reports`, `/admin/social/posts`, `/admin/social/spam`, `/admin/social/moderation-log` | |
| POST | `/admin/social/moderate` | `action` remove_post/restore_post/remove_comment/suspend_user/unsuspend_user/approve_tipster/reject_tipster/verify_expert/unverify_expert/verify_creator/unverify_creator/dismiss_report, `target_type`, `target_id`, `reason` (required, logged) |
| POST | `/admin/users/{id}/verify-email` | manual verification when email cannot be delivered |
| GET | `/admin/media/jobs`, `/admin/media/storage` (includes which server tools are installed), `/admin/mail/outbox` (no message bodies) | |
| POST | `/admin/media/cleanup`, `/admin/media/retry` | |
| POST | `/admin/owner-master` | loads the owner's Abu Dhabi T10 results master (30 rows) as user-supplied; `start_utc` required, `dry_run` |

## Cricket data (SH Universal Cricket Data Bridge) — Batch 05
Every match object now carries `data_status` (`upcoming`, `live_ball_by_ball`, `live_score_only`, `delayed`, `unavailable`, `historical_ball_by_ball`, `result_only`, `demo`), `data_status_label`, `sources`, `listed_order`, `home_away_verified`, `home_away_note` and, when a score-only source covers it, `live_score {source, status_text, innings[{r,w,o,inning}], fetched_at, ball_by_ball:false}`. `match_results.result_type` adds `draw`.

| Method | Path | Notes |
|---|---|---|
| GET | `/cricket/matches`, `/cricket/matches/{id}`, `/cricket/matches/{id}/scorecard`, `/commentary`, `/predictions` | same as `/matches/...` |
| GET | `/cricket/matches/{id}/deliveries` | paged ball events with batter/bowler names and source |
| GET | `/cricket/matches/{id}/statistics` | per innings: runs, wickets, legal balls, extras, wides, no-balls, 4s, 6s, run rate, `deliveries_match_total` cross-check |
| GET | `/cricket/matches/{id}/playing-xi`, `/cricket/matches/{id}/squads` | recorded XI with player identity status |
| GET | `/cricket/sources/status` | public: implemented sources, licence, last run, match counts; no keys |
| GET | `/admin/bridge` | admin: jobs, last 5 results each, CricketData budget, matches per source, duplicate suspects |
| POST | `/admin/bridge/jobs/{job}/run`, `/enable`, `/disable`, `/config` (`interval_minutes` 5–43200, `daily_budget`) | admin; audited |
| GET | `/admin/registry/countries`, `/admin/registry/competitions?q=`, `/admin/registry/sources` | admin |

Jobs: `owner_sheets_sync`, `registry_index_sync`, `cricketdata_matches`, `cricketdata_live`, `cricsheet_recent`, `cricsheet_backfill`.
