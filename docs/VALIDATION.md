# v0.3 validation — 10 October 2026

## Current continuous research release

- **107 automated checks passed** in one final combined run with actual isolated PostgreSQL enabled (99 default-suite checks plus 8 PostgreSQL checks). One nonblocking Starlette/httpx test-client deprecation warning.
- Temporal checks cover ordinary positive arrival delay, future measurement quarantine, backfill, reordering, actual-issued-only adaptation, missing native slots, unsupported cadence, target expiry and separate delayed event-window completion.
- Durable jobs/outbox, source-event and issuance idempotency, expired leases, a five-attempt cap including crashed owners, explicit failed-job retry, source revocation and server-driven native wall-clock generators are tested.
- Two-reviewer conflicts, cookie CSRF, throttling, encrypted TOTP, pre-enrollment session revocation, concurrent single-use invitation activation, clinic/patient isolation, approved sharing and own-record exports are tested.
- Actual local PostgreSQL 16.14 migration/upgrades reached schema 7 / Alembic 20261010_02. API cookie sign-in, eight synthetic arrivals and actual-model worker drain produced one immutable receipt; private/live data remained disabled.
- Fifty synthetic streams with ten concurrent intake threads accepted 400 readings/jobs. Actual model drain: 4.081 seconds; 400 completed, 50 immutable receipts and 50 reviews, 0 failed. All receipts clinical eligibility false. This short local batch is not sustained capacity or clinical performance evidence. See operational_validation.json.
- Full research database encrypted backup/offline restore: integrity ok, schema 7, manifest SHA verified and existing database preserved. Trusted artifact rollback restored exact original bytes in an isolated drill without changing the active model. Off-host/private hosting remains unverified. See recovery_validation.json.

## Model boundaries

The legacy five-fold internal benchmark remains 9.606 versus 9.812 mg/dL MAE. It is not a new-device result. In 20 sampled patients with sparse synthetic actual issuances, population 12.550 versus hybrid 12.676 mg/dL on 40 endpoints; no arrival personalization improvement established. Population stays primary. Native scheduled target semantics and an unverified source timezone remain explicit. Full event confidence intervals are in arrival_stress.json/LIVE_MODEL.md.

## Current interface and artifact checks

Current targeted browser/viewport evidence is recorded separately in `ui_validation_v3.json`; this is distinct from the final 107-check automated run. Legacy browser checks below apply only to the previous release. Current reports and slides retain clinic/source/doctor gates as pending. The 21-slide v3 video is a narrated editable presentation with actual UI screenshots and synthesized macOS Samantha speech; it is not an interactive browser recording. Its metadata reports 1,837.9 seconds (30 minutes 37.9 seconds). Accessibility targets are not conformance certification.

Fresh committed-source clone, separate virtual environment, pinned Python installation, npm ci and production build passed. A second isolated fresh database verified authentication, automatic source issuance, recorded captures and both PDFs after model startup warming. See clean_checkout_validation_v3.json.

No genuine CGM connection, completed doctor review, prospective study, hosted private deployment, off-host recovery or clinical approval is established.

---

# Legacy v0.2 validation — 10 October 2026

## Current clinic release

The upgraded clinic release supersedes the original replay-only demo. The legacy benchmark and its limitations remain in `data/processed/legacy_benchmark.json` and `backend/MODEL.md`. New model identities and exact evidence boundaries are in [EVIDENCE.md](EVIDENCE.md).

- **43 automated tests passed** after the final backend revision: native-data audit, causal/arrival boundaries, patient isolation, matured-only adaptation, 30-minute warning policy, unsupported-warning suppression, auth/revocation/roles, clinic checks, persistent transitions, immutable forecasts/outcomes, atomic/idempotent CSV/FHIR ingestion, units and report restrictions.
- TypeScript and Vite production build passed. The compiled UI is served with the API on one local origin; development proxy remains available.
- Reviewer and administrator roles are enforced server-side. Unauthorized access is rejected; imports and monitoring changes require admin. Runtime credentials, SQLite state, backups and sessions are excluded from the release.
- 100 Shanghai patients / 109 recordings / 112,462 native measured observations. Thirteen missing rows excluded; eleven gaps retained.
- One completed frozen five-fold clinic evaluation with grouped inner parameter selection and separate calibration patients. This is internal retrospective validation; the cohort was previously inspected.
- Runtime recorded-demonstration forecasts match the patient's out-of-fold result. Warning case 2072 / cursor 853 is retrospectively selected, within a virtual weekday 09:00–17:00 window. Historical staffing and timezone are unverified.
- SQLite backup and offline restore passed: integrity `ok`, schema 3, permissions 0600; users, reviews, actions, forecasts and outcomes matched exactly. Restore over an existing destination was refused without changing it.
- Frontend checked at 1440px and 390px: no page errors or document-level horizontal overflow across queue, patient, monitoring, intake and model evidence. Tables scroll inside their containers.

## Predictive results

Thirty-minute population MAE 9.812 mg/dL; hybrid MAE 9.606. Hybrid-minus-population paired difference −0.206, patient-bootstrap 95% CI [−0.336, −0.110]. This supports a small internal adaptation improvement. Historical-context benefit is inconclusive.

Thirty-minute episode precision 62.96%; overall observed episode recall 76.06%, including 13 onsets without eligible preceding forecast origins. Reachable-event recall is 76.57%. False alerts 0.919 per 24 eligible forecast hours; median warning lead 15 minutes; nominal 90% interval coverage 89.68%. All eligible forecast time is the denominator, not verified staffed hours. The clinical operating point awaits doctor review.

Sixty-minute evidence is evaluated separately and shown as supplementary; it does not trigger the primary review workflow. Outcomes have the native 15-minute timing resolution. Negative findings and large-error cases remain visible.

## Evidence boundaries

No completed doctor workflow review, clinical-use approval, hosted deployment, live CGM connection, prospective Indian validation, validated physiological simulation, medication advice or causal treatment evidence. FHIR support is a limited local adapter; no ABDM conformance certificate is claimed. TLS, encrypted storage, consent/retention operations and authorized integration latency are future pilot gates.

The nonblocking Vite bundle-size notice and Starlette/httpx test-client deprecation warning remain. Neither caused a runtime/build failure.

## Compiled browser demonstration

Three consecutive runs against separate fresh SQLite databases passed. Each served the compiled frontend and API on one origin, signed in, opened the staffed warning, saved and reviewed it, planned follow-up, reloaded and verified action history, compared the outcome, closed the original episode, exported a matching PDF, checked gap/stable/off-hours behavior and opened model evidence. The third run also exercised synthetic CSV, dated FHIR and streaming. No page or console errors occurred. The actual third run was recorded with sign-in credentials excluded.

## Submission artifact checks

Strategy: 8 A4 pages / 16 clickable references; doctor packet: 2 pages; original architecture: 1 page. All pages rendered and visually reviewed. Presentation: 21 slides; editable native text, architecture and quantitative chart with embedded workbook. Package, font/layout geometry and first-party import checks passed. The companion PDF contains exact rendered slides plus selectable captions and clickable primary references; its 21 pages were rendered and inspected. The 28-minute video includes disclosed synthetic speech and the actual authenticated local browser journey. Duration, audio levels and representative beginning/model/demo/end frames were checked. A one-page consultation example was regenerated after the PDF layout improvement.

## Public clean-checkout check

Cloned the public GitHub repository into a separate directory, created a new Python virtual environment, installed pinned requirements, ran npm ci and built the frontend through scripts/setup.sh. No model retraining was required. The compiled production launcher started on an alternate port with newly generated private accounts. An unauthenticated patient request returned 401; a fresh reviewer login opened Patient 2072 and the real 30-minute warning without browser errors. The verification service was stopped after the check; the working demonstration remained running.
