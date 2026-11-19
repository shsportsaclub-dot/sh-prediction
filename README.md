# SH PREDICTION

Independent cricket research and prediction application. Separate from Scoring Heroes.

## Status
Batch 02 (Master Script V1.0 foundation): normalized database, versioned `/api/v1`, settlement + accuracy engine,
explainable baseline model, ball-by-ball live probability, and the SH PREDICTION Hub (`/hub`: Home, Master List,
Match Center, Expert Tips, AI, Accuracy, Settings; dark/light; English/Hindi/Telugu + 21 fallback languages).
See `docs/INVENTORY.md`, `docs/API.md`, `docs/DEPLOYMENT.md`, `docs/qa/QA-REPORT.md`, `research/reference-matrix.csv`.

## Planned functionality
Fixtures, archived results, pre-match toss and match winner predictions, decimal odds price observations, review workflow and prediction accuracy.

## Security
Never commit credentials, API keys, SQLite data or private research records. Public GitHub repositories are visible to everyone even without sharing a link.

## Prediction accuracy rules
Toss and winner are tracked independently. Accuracy = Correct / (Correct + Wrong) x 100, always shown with the settled sample size.
Pending, Void (abandoned / no-result / void match), No Prediction and Ineligible (approved after the match start) are excluded from the denominator.
Approved predictions are immutable (database triggers). Outcome corrections go through /admin/outcomes_revise (reason and source required) and every admin write is stored in audit_logs.
Colour mapping to the original Google Sheets is NOT VERIFIED; labels and symbols always carry the meaning.

## Run
Set `SH_PREDICTION_ADMIN_TOKEN` to a strong secret and run `python app/main.py`.
Tests: `python -m unittest discover -s tests -v`. Screens: `python tools/qa_screens.py docs/qa`.
