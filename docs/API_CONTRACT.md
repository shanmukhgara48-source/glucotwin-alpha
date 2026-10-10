# GlucoTwin care platform API contract — v0.3

Public anonymized ShanghaiT2DM, explicitly synthetic arrivals and pending clinic access are separate modes. JSON succeeds with {success:true,data:...} and fails with {error:...} plus an appropriate HTTP status. Reports return PDF bytes. Clinical validation and identifiable intake remain gated.

## Authentication and roles

The UI uses POST /api/v2/auth/login with {username,password,otp?}. It sets an HttpOnly, SameSite=Strict session cookie and returns user, expiry and csrf_token. Cookie mutations send X-CSRF-Token. GET /api/v2/auth/me restores user/token; POST /api/v2/auth/logout revokes the session. Configure GLUCOTWIN_COOKIE_SECURE=true on HTTPS.

Cookie sessions have eight-hour absolute expiry and 30-minute API-inactivity expiry. Five failed username/client sign-ins in 15 minutes produce 429. POST /api/v2/auth/mfa/setup and /confirm enable TOTP; enabled accounts supply otp at sign-in. Secrets are encrypted locally. Legacy /api/auth/login, /me and /logout bearer sessions remain for CLI compatibility; the current UI does not persist bearer tokens.

Fresh installations use environment-supplied or random admin/reviewer/clinician/coordinator/patient research credentials, privately written with mode 0600. Invitations are one-use and time-limited, returned for private manual handover; no external message is sent.

- Care-team roles access clinic-scoped records. Admin manages sources, intake, monitoring configuration, accounts and audit.
- Clinician/admin/reviewer can publish patient-visible notes/follow-up. Coordinator can coordinate, but cannot publish clinical instructions.
- Patient accounts access only their bound companion record, without clinic queues, model receipts, other patients or private clinician notes.
- X-Connection-Key grants only its bound synthetic-source intake. Hashed keys are returned once and grant no clinic-read capability.

GET /api/health, login pages and compiled assets are public. Runtime databases, credentials, encryption keys and backups are never served as static assets.

## Operational sources, receipts and reviews

All routes in this table have **/api/v2** prefix. See [backend/OPERATIONAL.md](../backend/OPERATIONAL.md) for the complete pipeline contract.

| Route | Contract |
|---|---|
| GET/POST /connections | Scoped list/create {name,source_type,patient_id?,device_id?,cadence_minutes,source_timezone}. Synthetic source binds SIM-*; clinic source stays pending with no key. |
| PATCH /connections/{id} | Admin {status:enabled/paused/revoked}; only synthetic sources enable. Revoked sources cannot resume. |
| POST /connections/{id}/rotate-key | One replacement scoped key; old key stops working. |
| POST /connections/{id}/observations | {source_event_id,timestamp,glucose_mg_dl,available_at?}. Server owns receipt time; returns accepted/duplicate event and durable job. |
| POST /connections/{id}/generator | Admin {enabled,seed?}; returns enabled state, next reading time, cadence and model compatibility. |
| GET /patients/{id}/receipts | {items,total}; clinic-scoped recorded/arrival receipts. |
| GET /receipts/{id} | Canonical immutable receipt below. |
| POST /replay/capture/{id} | {cursor,scenario,current_time?}; canonical recorded receipt. |
| PATCH /reviews/{id} | {expected_revision,reason,status?,note?,assigned_reviewer?,next_review_at?,disposition?}; stale revision returns 409. |
| GET /queue?at=ISO | Review items/counts/monitoring/server time; separate source freshness, revision and latest receipt. Future replay episodes excluded. |
| GET /operations | Persisted job/review/quarantine/receipt counts, sources and worker heartbeat. |
| GET /events?after=N | Authenticated scoped metadata-only SSE; session revalidated. No health values or notes. |
| GET /readiness | DB/schema/model checksum/version/worker gate; 503 if unavailable, clinical_ready=false. |
| POST /jobs/{id}/retry | Admin bounded retry of a failed job. |

Source creation returns connection_key once; lists omit both key and hash. Identical source-event retries reuse original receipt time. Conflicts enter quarantine with 409 and preserve accepted evidence. Observation, event and outbox job commit together.

~~~text
receipt:
  {id,forecast_id,patient_id,patient,issued_at,input_cutoff,model_version,
   source_connection_id,input_digest,clock_kind,snapshot,outcomes,event_outcomes,
   review_id}
snapshot:
  {patient,current_time,observations,quality,clinic_model,scenario,clock_kind}
clinic_model:
  {quality,forecasts:{population:[],hybrid:[]},event_risks,adaptation,model,
   temporal,research_review_eligible,clinical_queue_eligible,suppression_reasons}
temporal:
  {issued_at,data_cutoff_at,measurement_age_minutes,target_anchor,
   original_event_target_times,source_timezone,clock_compatibility}
~~~

forecast_id aliases id. Point outcomes retain horizon/target/actual/availability. Separate event outcomes resolve completed native windows after late readings without rewriting point outcomes. Compact arrival receipts retain the latest 96 input readings and full input count/digest; original measurements remain stored.

Arrival forecasts target latest measurement plus 30/60 minutes, with actual remaining lead displayed. Population is primary; correction is experimental in this mode. A passed event target suppresses its probability. Synthetic 30-minute research review requires ten minutes to the earliest scheduled target. clinical_queue_eligible is always false; retrospective scores do not transfer. See [LIVE_MODEL.md](LIVE_MODEL.md).

Generator runs independently of the browser on wall time. Seed imports eight labelled synthetic past readings into a new source, all received now; it creates no earlier issuances. Native ticks stop on revocation and leave gaps after outages. One-minute feed is display-only for the 15-minute model.

Review projections retain initiating/latest forecasts, occurrence count, revision and disposition. Current freshness is separate from age at issue; historical playback is never labelled a live sensor. Progression: new → reviewed → follow_up_planned → closed; reviewed can close directly. Omitted status supports assignment without lifecycle progression. Follow-up needs next_review_at. Dispositions: none, reviewed_no_action, context_requested, follow_up_scheduled, technical_issue, closed_after_review.

## Administration and patient companion

Routes below also have **/api/v2** prefix.

| Route | Capability |
|---|---|
| POST /platform/enroll | Synthetic {patient_id:SIM-*,label,timezone} only. |
| GET /platform/patients | Care-team clinic profiles. |
| GET/POST /platform/staff | Admin list/invite {username,name,role,patient_id?}; patient needs binding. |
| POST /auth/activate | One-use invitation code and new password. |
| POST /platform/staff/{id}/deactivate | Disable account and revoke sessions. |
| POST /platform/tasks | Clinician-approved published follow-up or unpublished draft. |
| POST /platform/shared-notes | Clinician-approved patient-visible note. |
| GET /patient/me | Own observations, approved/self-reported context, published tasks, consent and sources. Predictions disabled. |
| POST /patient/context | Own meal/activity/symptom; server availability, no future observation. |
| POST /patient/consents | Append research_collection grant/withdrawal; withdrawal revokes collection keys. Does not activate clinical monitoring. |
| POST /patient/tasks/{id}/complete | Complete own published task. |
| GET /patient/report | Own patient-visible PDF; private notes/model outputs excluded. |
| POST /platform/intake/preview | Admin synthetic CSV row validation without commit. |
| GET /platform/gates | Actual pending source/workflow/privacy/clinical gates. |
| GET /platform/audit | Administrator scoped audit. |

## Recorded research and legacy compatibility

| Route | Response |
|---|---|
| GET /api/patients | Clinic-scoped public and labelled imported profiles. |
| GET /api/replay/{id}?cursor=N&scenario=recorded | Prefix snapshot; zero-based cursor. sensor_gap withholds three readings while retaining clock. |
| GET /api/benchmarks | Original measured benchmark. |
| GET /api/clinic-benchmark | Five-fold internal retrospective validation and failures. |
| GET /api/provenance | Source/license/checksum/audit manifest. |
| GET /api/clinic/queue?at=ISO | Compatibility queue with revision/latest receipt fields. |
| GET /api/clinic/monitoring?at=ISO | Staffed-window state, responsibility and explicit clock. |
| GET /api/clinic/reviews/{id} | Review plus immutable actions. |
| GET /api/clinic/timeline/{patient}?at=ISO&scenario=recorded | Available prefix, forecasts, observable outcomes and reviews. |
| GET /api/clinic/report/{patient}?at=ISO&scenario=recorded | Matching protected consultation PDF. |
| GET /api/clinic/audit | Administrator latest 200 scoped audit entries. |

Legacy capture returns forecast/review IDs and snapshot. Legacy review PATCH accepts new fields but supports older clients without revision; v2 requires concurrency protection. Actions never change model values or evaluation results. Legacy streaming is virtual replay; it does not establish the operational receipt clock.

PUT /api/clinic/monitoring accepts timezone, same-day start/end hours, reviewer and weekdays (Monday=0). Default Asia/Kolkata weekdays 09:00–17:00. Outside hours items persist and monitoring is inactive; no emergency/external notification service exists. POST /api/clinic/context/{patient} accepts dated kind/value/observed/available/provenance and stores server receipt. Only dated allowlisted historical demographics/BMI/duration enter predictions; meal/activity/symptom entries remain evidence context.

## Historical imports and interoperability boundary

Admin /api/clinic/intake/csv and /fhir (aliases /import/*) commit atomically. Required CSV columns: patient_id,timestamp,glucose_mg_dl,available_at; optional source defaults simulated. Identifying extra columns are rejected. Default IDs are SIM-*. Allowlisted PUB-* imports require admin attestation of anonymized ShanghaiT2DM, its Figshare URL and CC BY 4.0 license. Imports remain outside fixed evaluation cohorts; attestation does not independently verify arbitrary files.

Offsets/Z are mandatory and normalize to UTC. Shanghai timezone is unverified; native times remain dataset-local virtual time. No interpolation/imputation or automatic cadence conversion is performed.

Limited FHIR R4 accepts Patient, Condition, glucose/BMI Observation and CarePlan collection/transaction bundles. Synthetic Patient forbids identifiers/name/telecom/address and references resolve inside the bundle. Implemented LOINC/UCUM mappings and timestamps are required; mmol/L converts by 18.0182. meta.lastUpdated is declared source availability, not app receipt or live latency. Laboratory-resource acceptance does not establish CGM-model compatibility. No ABDM certification or hospital connection is claimed.

## Persistence and runtime

Default .run/clinic.sqlite3 uses WAL and central schema **7**, plus identity/platform tables. GLUCOTWIN_DATABASE_URL selects PostgreSQL through explicit Alembic migrations and the tested compatibility layer. Issued forecasts, point/event outcomes, actions and audit have mutation guards. Jobs use leases/retries/idempotency. Consent revocation stops collection while retaining history.

SQLite backup includes committed WAL; restore offline into a new destination. SQLite recovery refuses PostgreSQL configuration. PostgreSQL requires a separately verified database-specific procedure; PostgreSQL recovery remains unverified. Compiled UI/API share one origin; development uses Vite proxy. Authorized source, doctor review, prospective validation and clinical-release gates remain pending.
