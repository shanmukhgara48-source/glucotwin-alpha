# GlucoTwin clinic API contract

Authenticated local research prototype. Public anonymized ShanghaiT2DM and labeled synthetic scenarios; no clinical validation. All JSON responses use `{ "success": true, "data": ... }`; failures use `{ "error": "..." }` and an appropriate HTTP status. Reports return PDF bytes.

## Authentication and clinic access

- `GET /api/health` is public. The compiled login UI at `/` and its `/assets` are public; patient APIs require a session.
- `POST /api/auth/login` accepts `{ "username": "reviewer", "password": "..." }`. Response data contains `token`, `expires_at`, and `user: {id, username, name, role, clinic_id}`.
- Send `Authorization: Bearer <token>` on every protected request. Opaque tokens expire after eight hours; only their SHA-256 hashes are stored.
- `GET /api/auth/me` returns the signed-in user. `POST /api/auth/logout` revokes that session.
- On a fresh database, administrator/reviewer passwords come from `GLUCOTWIN_ADMIN_PASSWORD` / `GLUCOTWIN_REVIEWER_PASSWORD` (minimum 12 characters), or cryptographically random generation. Local bootstrap credentials are written to ignored `.run/clinic-credentials.json` with mode 0600. No production secret is hardcoded.
- Reviewer/admin roles can inspect clinic records, capture forecasts, record reviews/context and export summaries. All CSV/FHIR/simulated-stream intake and monitoring changes require the administrator role. Record lookup is constrained by the authenticated clinic, including patient, review and report access.

## Read APIs

| Route | Response data |
|---|---|
| `GET /api/patients` | Clinic-scoped profile array; source anonymized IDs and separately labeled `SIM-*` or `PUB-*` imports. |
| `GET /api/replay/{patient_id}?cursor=N&scenario=recorded` | Prefix-only snapshot. Cursor is zero based. `scenario=sensor_gap` withholds the last three readings while retaining the virtual clock. |
| `GET /api/benchmarks` | Legacy measured benchmark; retained for comparison. |
| `GET /api/clinic-benchmark` | Five-fold internal retrospective validation, measured metrics, operating points, failure cases and current demo metadata. |
| `GET /api/provenance` | Source manifest, license, archive checksum, observations and exclusions. |
| `GET /api/clinic/queue?at=ISO` | `{items, pending_count, overdue_count, monitoring}`. `at` is optional and selects a virtual clock. |
| `GET /api/clinic/monitoring?at=ISO` | Staffed-window configuration plus `active`, `current_time`, `clock_kind`, and responsibility message. |
| `GET /api/clinic/reviews/{review_id}` | Persistent review record and append-only `actions` array. |
| `GET /api/clinic/timeline/{patient_id}?at=ISO&scenario=recorded` | `{patient, at, events, reviews, quality, scenario, monitoring, doctor_review_status}`. Future-issued episodes are excluded. |
| `GET /api/clinic/report/{patient_id}?at=ISO&scenario=recorded` | Protected consultation PDF; scenario and evidence cutoff match the displayed prefix. |
| `GET /api/clinic/audit` | Administrator-only, latest 200 audit records for that clinic. |

Aliases exist for `/api/clinic/patients/{id}/timeline` and `/summary.pdf`. Historical source timestamps are a labeled dataset-local virtual clock; the actual source timezone is unverified. Import timestamps require explicit offsets or `Z` and are normalized to UTC.

### Snapshot and primary-model contract

A snapshot retains the legacy `forecasts`, `state`, `update_history` and `forecast_history` for reproducibility, and adds `clinic_model` and `monitoring`. New product charts use the primary model declared inside `clinic_model.model`.

```text
clinic_model:
  quality: {status, message, last_reading_at, minutes_since_reading}
  forecasts: {population: [forecast], hybrid: [forecast]}
  event_risks: [{horizon_minutes, probability, threshold, exceeds_threshold,
                 event_eligible, ongoing_high, probability_method}]
  model: {version, primary, personalization_status, evidence, clock_policy}
  adaptation: {correction_mg_dl, matured_samples, maturity, history,
               by_horizon, engineering_state, parameters, message}
  forecast_history: [{issued_at, target_at, horizon_minutes, population_mg_dl,
                      hybrid_mg_dl, actual_mg_dl, absolute_error_mg_dl, model_version}]
forecast:
  {timestamp, horizon_minutes, glucose_mg_dl, lower, upper, interval_method}
```

Only the **30-minute classifier** creates actionable `alerts` and predicted-excursion review episodes. The 60-minute probability is supplementary. An unavailable primary model cannot inherit legacy-filter warnings. Current glucose above 180 mg/dL is an observed `ongoing_high` state, distinguished from a new excursion. Missing/late readings suppress unsupported forecasts. Predictive intervals have measured calibration evidence rather than a clinical guarantee.

Queue items carry `id`, `patient_id`, `patient_name`, `forecast_id`, `type`, `status`, `issued_at`, `cursor`, `scenario`, `assigned_reviewer`, `last_review`, `next_review_at`, `overdue`, `message`, `probability`, and `reading_freshness`. Types are `predicted_excursion`, `ongoing_high`, `missing_data`, and `forecast_review`. Freshness is labeled **at the recorded issue time**, with `clock_kind=recorded_issue`, `age_at_issue_minutes`, and `live_freshness=false`; it is not a live sensor-age claim.

## Persistent forecast/review workflow

`POST /api/clinic/capture/{patient_id}` accepts `{ "cursor": 853, "scenario": "recorded" }` and optional `current_time` for imported streams. Response data is `{forecast_id, review_id, snapshot, monitoring}`. Replay GET requests do not issue persistent forecasts or review episodes. Capture is idempotent for clinic/patient/issue-time/scenario/model-version; a different scenario never overwrites an earlier issuance. An open review of the same patient/type deduplicates repeated warnings.

`PATCH /api/clinic/reviews/{review_id}` (alias `POST .../actions`) accepts:

```json
{
  "status": "reviewed",
  "reason": "Inspected the forecast evidence",
  "note": "Care-team note",
  "next_review_at": null,
  "assigned_reviewer": "reviewer"
}
```

Allowed progression is `new → reviewed → follow_up_planned → closed`; a reviewed episode may also close directly. Follow-up needs a timezone-explicit `next_review_at`; reviewer assignment must remain inside the clinic. Reasons, notes, actor and audit timestamps are persisted. Actions never modify predictions or displayed evaluation scores.

`PUT /api/clinic/monitoring` accepts `{timezone, start_hour, end_hour, reviewer_id, days}`. Defaults are `Asia/Kolkata`, 09:00–17:00, reviewer `reviewer`, weekdays `[0,1,2,3,4]` (Monday zero). Same-day windows are supported. Outside staffed hours items remain queued; no automatic notification or emergency-response service is implied.

`POST /api/clinic/context/{patient_id}` (alias `/patients/{id}/context`) accepts `{kind, value, observed_at, available_at, provenance}`. Kinds: meal/activity/symptom/note/historical/condition/care_plan. Provenance: self_reported/simulated/measured. Only dated `historical` objects containing age/sex/BMI/diabetes_duration_years enter the model; other entries remain timeline context. Historical values are reconstructed at every prior forecast origin. `available_at` defaults to arrival wall-clock time and cannot precede `observed_at`.

## Intake: synthetic and allowlisted public data

Intake is administrator-only. Imported observations preserve their cadence; they are neither interpolated nor resampled. Conflicting duplicate timestamps return 409; identical duplicates are idempotent. Bulk CSV/FHIR requests commit atomically, including profiles, context and audit records.

### CSV

`POST /api/clinic/intake/csv` (alias `/import/csv`) accepts `{ "csv": "..." }`. Required header:

```csv
patient_id,timestamp,glucose_mg_dl,available_at,source
SIM-001,2026-10-10T10:00:00Z,140,2026-10-10T10:00:00Z,simulated
```

Default intake accepts pseudonymous `SIM-*` patients and `source=simulated`. Extra identifying columns are rejected; glucose must be finite and 20–600 mg/dL. Public measured CSV intake instead requires all of:

```json
{
  "csv": "patient_id,timestamp,glucose_mg_dl,available_at,source\n...",
  "attested_anonymized_public": true,
  "source_url": "https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933",
  "source_license": "CC BY 4.0"
}
```

Those rows require `PUB-*` patient IDs and `source=anonymized_public`. Provenance is administrator-attested and allowlisted to ShanghaiT2DM; it is not independent verification of arbitrary uploaded data. Imports are separate from the fixed evaluation cohorts. Explicit import timezone is required; any mapping of unverified historical source timezone must remain labeled virtual-clock replay.

Response data: `{accepted, duplicates, patients, errors: []}`.

### Simulated stream

`POST /api/clinic/stream/{SIM-patient_id}` (alias `/patients/{id}/observations`) accepts `{timestamp, glucose_mg_dl, available_at, source: "simulated"}`. Response data: `{accepted, duplicates, snapshot}`. Each reading is genuinely ingested and produces a new prefix-based snapshot; native quarter-hour demo readings are not fabricated performance results. Arrival latency can produce a gap and suppress forecasts.

### Limited FHIR R4 adapter

`POST /api/clinic/intake/fhir` (alias `/import/fhir`) accepts `{bundle: {...}}`. Supports collection/transaction bundles of Patient, Condition, Observation and CarePlan. It does not implement general transaction methods or certify ABDM conformance.

- Patient IDs must be `SIM-*`; name/telecom/address/identifier fields are rejected. Clinical subjects must resolve to a Patient in the same bundle via `Patient/id` or an entry `fullUrl`.
- Gender and full synthetic birthDate can produce dated historical sex/age. `meta.lastUpdated` is mandatory when demographics are present; age is calculated at that availability date.
- Glucose Observation: LOINC `2339-0`, `2345-7`, or `41653-7`; UCUM `mg/dL` or `mmol/L` (converted using 18.0182 mg/dL per mmol/L); `effectiveDateTime` and `meta.lastUpdated` required.
- BMI Observation: LOINC `39156-5`, UCUM `kg/m2`, finite 10–80; timestamps determine when the historical context becomes usable.
- Condition uses `recordedDate`, CarePlan uses `created`; both need `meta.lastUpdated`. Their descriptive text is context, not a treatment simulator.
- Repeat context resources are idempotent by kind/value/observation/availability/provenance. Malformed references, quantities and timestamps reject the complete bundle.

## Persistence and evidence boundaries

`GLUCOTWIN_DB_PATH` defaults to ignored `.run/clinic.sqlite3`. SQLite WAL and numbered `user_version` migrations currently reach **3**. Tables persist profiles, imported observations, context, users/sessions, monitoring, issued forecasts, review episodes, actions, audit records and eventual outcomes. Source CGM remains in the audited immutable data files.

Issued forecasts are immutable. Append-only `forecast_outcomes` are matured on explicit capture or stream ingestion only when exact target observations are available; event labels require the complete native horizon. Reads reveal actuals only within the current available prefix, even if a later outcome was already persisted. SQLite backup API captures committed WAL content; stop the service before restore.

Compiled deployment serves `/` and `/assets` from `frontend/dist`; development uses the Vite `/api` proxy. Identifiable-record intake, live vendor CGM integration, prospective validation, clinician workflow approval, encryption at rest and supervised clinical release remain gated. Doctor review is pending.
