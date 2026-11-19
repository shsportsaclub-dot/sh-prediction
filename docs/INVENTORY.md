# SH PREDICTION — inventory against Master Development Script V1.0

Baseline audited: commit `8166499` (Python stdlib server + SQLite + single-file web app + Android WebView shell).
This batch: **Batch 02 — V1 foundation** (normalized schema, `/api/v1`, engines, Hub screens, tests).

Batch 03 (local, not pushed): own platform per "SH PREDICTION — FINAL OWN PLATFORM DEVELOPMENT INSTRUCTIONS".

Batch 04 (local, not pushed): Final Integration & Security directive, Tipster Social Network module, SH SOCIAL photos/videos/Reels.

Legend: ✅ done and tested · 🟡 works, limited by data or not fully tested · ⬜ not started

| Module | Status | Notes |
|---|---|---|
| Website frontend (viewer, `/`) | ✅ | Home, Matches, 15-section Match Center, Expert Tips, AI, Assistant, Accuracy, Settings; dark/light; offline cache |
| Android-compatible frontend | 🟡 | Same responsive site in the WebView APK; not run on a physical phone this batch |
| Backend API | ✅ | Viewer / user / admin layers, backend-enforced |
| Prediction engine | 🟡 | Explainable baseline: winner, toss (fair coin), 1st/2nd innings projection, venue/form/H2H; player projections need verified player stats |
| Live prediction engine | ✅ | Ball-by-ball probability, over-by-over, phases, wicket impact, partnership, momentum, turning points |
| Statistics engine | ✅ | Toss, batting first vs chasing, home/away, day, venue, team, player, calibration backtest |
| Fantasy engine | ✅ | Configurable rule sets, eligibility from XI/squad, roles, C/VC, 3 risk levels, history; free-to-play |
| Cricket AI Assistant | ✅ | Grounded answers from our database + Laws (2026 edition); replaceable model interface; says when data is missing |
| Expert tips engine | ✅ | Profiles, verification, private submissions, publishing, ranking on published tips |
| Accuracy & audit engine | ✅ | ICC settlement, superseded evaluations, full audit log |
| Admin management system | ✅ | 12 admin screens (`/admin-panel`) |
| Notification engine | 🟡 | In-app notifications (follows, likes, comments, mentions, new posts from followed users, video ready, moderation, tipster approval); email for verification/reset. Push notifications to phones not built (needs a free channel decision) |
| Cricsheet historical import | ✅ | Free (ODC-By 1.0), allow-listed downloads, own parser, results/toss/innings/ball-by-ball/scorecards/XI, dedupe by Cricsheet id, attribution shown; limited-overs only; not live; tested with synthetic files (this workspace cannot reach cricsheet.org) |
| Data ingestion gateway | 🟡 | Contract, cache, validation, dedupe, retry, adapters (manual, demo, licensed placeholder); no licensed feed connected |
| Multilingual system | ✅ | 9 languages complete; 15 more with honest partial coverage |
| Master List (results, admin only) | ✅ | Matches the approved sample exactly |
| Migration safety | ✅ | Explicit, backed-up, verified |
| Accounts (register, email verification, login, reset, delete, privacy) | ✅ | Phone-code login removed from production; email via SMTP or admin outbox + manual verification |
| Tipster network (apply, approve, verified expert, profiles, badges, computed accuracy, leaderboards) | ✅ | Prediction posts create separate locked picks; late/void/pending excluded |
| Social posts (text, analysis, photo multi-image, video, reel, poll, prediction, toss prediction) | ✅ | Edit history, delete (pick kept), hashtags, mentions, match tagging |
| Feeds (For You, Following, Latest, Trending, Reels, Saved, hashtag, match, search) | ✅ | Own ranking: engagement, freshness, interests, match relevance, watch completion, max 2 per creator |
| Engagement (follow, like, comment/reply, share, save, vote, report, block, views, watch time) | ✅ | Views deduplicated per viewer per day; own views excluded |
| Media pipeline (resumable uploads, Pillow, FFmpeg MP4 + HLS + thumbnails, worker, cleanup, retry) | ✅ locally | Needs FFmpeg on the server (Dockerfile added); media on the persistent disk, object storage not built |
| Reels player (vertical swipe, autoplay/pause, mute, actions) | ✅ | Proven in Chrome (E2E) |
| Creator dashboard | ✅ | Views, watch time, completion, likes, comments, shares, saves, followers, daily/monthly, prediction performance |
| Match Center Community tab | ✅ | SH AI shown separately from tipster picks |
| Live updates (SSE) + original multilingual commentary | ✅ | en/hi/te commentary; other languages say English is used |
| Admin: social users, moderation, spam signals, media/storage, mail outbox | ✅ | Every action needs a reason and is logged |
| Cricket game: virtual simulation + real-match replay | 🟡 | Simulation with Laws checks and 2D field; interactive play/3D not built |
| Owner Abu Dhabi T10 master (30 matches) | ✅ | Admin → Master List → Load; user-supplied, dates needed from you |
| Android app | 🟡 | Same site in the WebView APK; uploads use the phone's file picker; not tested on a physical phone |
| Malware scanning | ⬜ | ClamAV hook only; not installed |
| Object storage / CDN / Postgres | ⬜ | Option D in DEPLOYMENT.md |
| Authorized live data feed | ⬜ | None connected (none bought, no scraping) |

## Batch 04 file-by-file changes
| File | Change |
|---|---|
| `app/auth.py` (new) | Accounts, password hashing, email codes, sessions, lockout, reset, deletion |
| `app/media.py` (new) | Signed resumable uploads, type sniffing, scan hook, Pillow/FFmpeg processing, HLS, storage, cleanup, worker, tool check |
| `app/social.py` (new) | Posts, feeds and ranking, engagement, views/watch, tipster stats, leaderboards, dashboard, notifications, spam signals, moderation |
| `app/api_social.py` (new) | REST routes for auth, me, media, social, game, community/replay and social admin |
| `app/commentary.py` (new) | Original commentary generator (en/hi/te) |
| `app/game.py` (new) | Virtual cricket simulation, Laws validation, replay directives |
| `app/live.py` (new) | Live event publishing and Server-Sent Events stream |
| `app/hub_social.js` (new) | Viewer screens: Social, Reels, post, profile, compose, notifications, dashboard, leaderboard, account, game, replay, live SSE |
| `app/data/owner_master_abu_dhabi_t10.json` (new) | The 30-row owner master copied from the prototype `index.html` |
| `app/schema.py` | Migration 004 (accounts, media, jobs, posts…, live and game tables) |
| `app/api_v1.py` | Account identity, social routing, own-scoring live updates, owner-master import |
| `app/main.py` | Media upload/serving, SSE route, worker start, `/auth/generate` → 410, WAL mode |
| `app/hub.html` | 6-item nav (Home, Matches, Social, Reels, Expert Tips, More), Community tab, live SSE, commentary language, account link replaces phone login |
| `app/admin.html` | Social Users, Moderation, Media & Storage sections; owner-master loader |
| `app/i18n.py` | 57 new strings, 9 languages complete (140 keys) |
| `Dockerfile`, `requirements.txt`, `render.yaml` | Docker build with FFmpeg + Pillow; media signing key; media dir on disk |
| `tests/test_social.py`, `tests/test_owner_master.py` (new), `tests/test_v1.py`, `tests/test_api.py` | Account-based helpers; social, media, live, game, admin sweep, owner master |
| `tools/e2e_social.py` (new) | Mandatory end-to-end acceptance proof |
| `docs/*` | API, SECURITY, DEPLOYMENT, CRICKET-DATA-ENGINE, GAME-ENGINE, QA report, this inventory |

## Batch 05 — automatic cricket data (local, not pushed)
| Feature | Status | Notes |
|---|---|---|
| Owner Google Sheets auto-sync (6 leagues, every 30 min) | ✅ built, tested with stand-ins | Sheets must be shared "Anyone with the link: Viewer" |
| League Index → competition registry | ✅ | Loaded as unverified |
| Cricsheet: Tests/first-class, draws, listed order, corrections, scorecard check, catalogue discovery, scheduled backfill | ✅ built, tested with Cricsheet-format files | Real IPL download runs on the server |
| CricketData.org adapter (fixtures, live score, toss, result) | ✅ built, tested with provider-format JSON | Needs `CRICKETDATA_API_KEY`; free 100 hits/day shared |
| Scheduler (24/7, retries, log, admin controls) | ✅ | Stops while a free Render instance sleeps |
| Honest data status on every match | ✅ | |
| Global registry: countries (12 Full + 16 Associates so far), sources with permissions, competitions | 🟡 | 83 associates and all sub-national research still pending |
| Permitted website parser / authorized streaming feed | ⬜ | No permitted source identified yet |
| Live ball-by-ball for non-SH matches | ⬜ | Needs a paid or licensed feed (not activated) |

Files: `app/registry.py`, `app/gsheets.py`, `app/cricketdata.py`, `app/scheduler.py` (new); `app/schema.py` (migration 005: adds tables/columns and rebuilds match_results to allow "draw", copying every row), `app/cricsheet.py`, `app/api_v1.py`, `app/main.py`, `app/hub.html`, `app/admin.html`, `requirements.txt`, `tests/test_bridge.py` (new), `tests/test_v1.py`, `docs/CRICKET-DATA-BRIDGE.md`, `docs/SOURCE-REGISTRY.md` (new), docs updates.
