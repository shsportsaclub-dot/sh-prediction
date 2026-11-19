# SH PREDICTION — Viewer Match Center prototype

Open `index.html` in a browser to view the original SH PREDICTION Match Center, Tips and Analytics screens.

## Security / status
This is a **static, offline, viewer-only prototype**. No server API, authentication, AI prediction engine, actual Android APK or live cricket feed is connected. Admin UI intentionally does **not** expose match master records, private predictions, or editing. Do not interpret the static viewer display as a secured production backend.

The first 25 results are user-supplied historical records, not independently verified. Matches 26–30 are deliberately marked pending until verified. All unpublished tips remain hidden; no fabricated win probabilities are shown.

## Architecture for next production phase
- Secure admin-only match master: Match, Home, Away, Toss, Winner
- Role-checked backend endpoints for prediction create, lock, publish, result review and audit
- Public read-only match center shows published predictions only
- Original prediction immutable after lock; result verification and corrections auditable
- Data provider licensing, verified scorecards, prediction engine, localization and mobile QA before release
- Never expose admin tokens in client JavaScript
- No external code/assets from ALLCRIC are copied

## Color contract
Home blue, Away orange, H blue, A orange, winner green, loser red, unknown gray; no dots or bulbs. Public Match Center uses the same colors.
