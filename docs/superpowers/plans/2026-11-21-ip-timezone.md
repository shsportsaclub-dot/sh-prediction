# Automatic display timezone

Goal: Explicit saved timezone first; mobile calling-code then IP country, then device timezone. Format every match time with AM/PM. UTC remains authoritative for scoring and deadlines.

- Add standard-library GeoIP range importer/lookup using DB-IP Country Lite (CC BY 4.0) and an offline SQLite database, downloaded once in a background startup task. No visitor IP sent to a third party. Preserve attribution/source/version, bound downloads, atomic replacement and old-good-database fallback.
- Country-only lookup selects a timezone only if IANA zone.tab lists exactly one zone. Multi-zone countries need device/profile timezone; do not pretend a country identifies a city. Shared phone codes likewise remain unresolved.
- Add presentation-only timezone endpoint; do not use geolocation for authentication, prediction locks or legal eligibility. Forwarded address is used only on Render; socket IP elsewhere. Phone fallback is a display hint, not ownership proof.
- Add a shared browser formatter used by hub and match center. Resolve timezone asynchronously, rerender when it arrives; use hour12 true everywhere modified. Link DB-IP attribution on the hub.
- Regress IPv4/IPv6 range boundaries, unknown/private IPs, ambiguous country/phone, database failure fallback, AM/PM and cross-day conversions. Run full existing suite. Deploy only after checks pass.

Limit: IP country estimates cannot establish a precise timezone inside multi-zone countries or physical presence behind VPNs. Mobile login in current production is email based; legacy on-screen phone OTP is disabled. Do not turn it on to obtain a phone number.

Owner steering: a user-selected timezone is saved locally and overrides automatic estimates. Mobile country code is preferred over IP when available. Country-code fallback is still limited to the four documented codes; no production mobile-code field was invented.
