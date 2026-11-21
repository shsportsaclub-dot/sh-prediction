# Mobile demo onboarding

Owner explicitly requests an on-screen OTP while testing, before SMS production authentication. Login screen offers existing country/calling-code picker, mobile number, visible demo OTP and Enter demo. The phone/OTP stay in page memory only; no phone is sent to the server or saved by this flow. OTP expires in five minutes and is consumed after success. This is a demonstration, not proof of phone ownership.

The production sample-match list was empty during verification. Entry therefore sets `shp_demo_visit=1` (display only), selects normal public match data with `shp_demo=0`, and opens the public match list. A demo-access banner identifies the guest flow; it is hidden for an authenticated account. It never issues/saves a server credential, calls the legacy phone-auth endpoint, creates an account, or grants write/admin/private access. Existing account login remains available, and backend authentication remains unchanged. Protected actions still require real account authentication. Future SMS integration is separate work.

Validation: `node tests/demo_login_client_test.cjs`, existing timezone client test, inline/external JavaScript syntax, full Python regression. The visible OTP is intentionally public to the person viewing the demo page.
