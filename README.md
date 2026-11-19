# SH PREDICTION

Independent cricket research and prediction application. Separate from Scoring Heroes.

## Status
Batch 03 (local): own platform — public viewer site (`/`), private admin panel (`/admin-panel`), published-only predictions,
admin-only actual-results Master List, prediction/live/statistics/fantasy engines, grounded cricket assistant, data gateway
with provider adapters, 9 complete languages, explicit backed-up migrations. See `docs/`.

## Run
`SH_PREDICTION_ADMIN_TOKEN=<secret> python app/main.py`, then open `/admin-panel` and run the migration once.
Tests: `python -m unittest discover -s tests -v`. Browser QA: `python tools/qa_screens.py docs/qa`.
