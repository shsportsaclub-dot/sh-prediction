# SH PREDICTION

Independent cricket research and prediction application. Separate from Scoring Heroes.

## Status
Repository initialization in progress. The Python API and HTML dashboard are not yet committed; do not deploy until both exist.

## Planned functionality
Fixtures, archived results, pre-match toss and match winner predictions, decimal odds price observations, review workflow and prediction accuracy.

## Security
Never commit credentials, API keys, SQLite data or private research records. Public GitHub repositories are visible to everyone even without sharing a link.

## Prediction accuracy rules
Toss and winner are tracked independently. Accuracy = Correct / (Correct + Wrong) x 100, always shown with the settled sample size.
Pending, Void (abandoned / no-result / void match), No Prediction and Ineligible (approved after the match start) are excluded from the denominator.
Approved predictions are immutable (database triggers). Outcome corrections go through /admin/outcomes_revise (reason and source required) and every admin write is stored in audit_logs.
Colour mapping to the original Google Sheets is NOT VERIFIED; labels and symbols always carry the meaning.

## Run (once app files are committed)
Set `SH_PREDICTION_ADMIN_TOKEN` to a strong secret and run `python app/main.py`.
