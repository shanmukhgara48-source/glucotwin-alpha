# GlucoTwin care platform architecture — v0.3

One workflow: receive labelled synthetic sensor data → preserve what was available → issue an inspectable forecast → coordinate a review → append measured outcomes → export reviewed evidence. Public recorded evaluation remains a separate reproducible mode. Clinic connection, physician workflow review and clinical release are pending.

~~~mermaid
flowchart TD
    A[Public ShanghaiT2DM recordings] --> B[Prefix-only virtual playback]
    C[Dated historical or simulated EHR context] --> D[Identity, units, source and timestamp checks]
    E[Scoped synthetic connection or native generator] --> D
    D --> F[Measurement + source event + durable job transaction]
    F --> G[(SQLite default / tested PostgreSQL)]
    G --> H[Leased worker, retries and input digest]
    H --> I[Actual issue clock and trusted receipt cutoff]
    B --> J[Recorded research model]
    I --> K[Arrival research adapter]
    J --> L[Population and patient-corrected comparison]
    K --> L
    I --> M[Unsupported cadence / stale input abstention]
    L --> N[Immutable issued forecast receipt]
    M --> N
    N --> G
    N --> O[Deduplicated review projection]
    O --> P[Revision-checked owner / review / follow-up action]
    P --> G
    G --> Q[Separate point and completed-window event outcomes]
    Q --> K
    G --> R[Clinician workspace, timeline and PDF]
    S[Own-record patient companion] --> T[Self-reported context / consent]
    T --> G
    P --> U[Clinician-approved patient notes and tasks]
    U --> S
    V[Grouped offline evaluation] --> W[Versioned retrospective evidence]
    W --> J
    W --> R
~~~

## Runtime and separation

React/TypeScript, React Router, Tailwind and Recharts implement the clinician desk, patient workspace, receipts, operations, intake, evidence, settings and patient companion. FastAPI enforces server-side roles, clinic identity and patient bindings. No external AI provider is required.

The compiled UI and API share one origin. FastAPI serves only compiled frontend assets; runtime databases, credentials, encryption keys and backups are excluded. The native source files and fixed evaluation artifacts remain separate from editable clinic context and labelled synthetic operational records.

SQLite WAL is default. GLUCOTWIN_DATABASE_URL selects the tested PostgreSQL compatibility layer with explicit Alembic migrations. Central schema is version 7, with separately initialized identity/platform tables. No implicit SQLite-to-PostgreSQL data copy occurs.

## Two clocks and two evidence modes

**Recorded mode:** Shanghai's native measured 15-minute observations are replayed by prefix. Source timezone is unverified, so naive dates stay an explicitly labelled dataset-local virtual clock. Missing observations remain missing. Untimed labs and treatments are excluded; baseline historical demographics have a documented source-availability assumption. The five-fold model and legacy benchmark remain reproducible.

**Arrival mode:** operational observations require explicit UTC-normalizable measurement times. The server records actual receipt and issue times. Declared source availability is preserved separately; it cannot override app receipt. Context also retains server receipt. Model features include only records available by the actual decision clock.

Arrival targets stay latest measurement plus 30/60 minutes, with remaining lead from actual issuance. The classifier refers to its original scheduled native targets, rather than a new next-30-minute window. Passed targets suppress probability. The research lead policy and source-local time-of-day mapping remain unvalidated. Population is primary in arrival mode; patient correction is experimental. clinical_queue_eligible is always false.

A one-minute synthetic source can show current feed arrivals, but cannot enable the 15-minute model. Unsupported cadence, stale history and gaps visibly abstain. Imports do not establish predictive compatibility or live CGM access.

## Durable ingestion and actual issuances

The source event, accepted measurement and outbox job commit together. Source-event IDs are connection-scoped; identical retries keep original receipt time. Conflicting events/measurements enter quarantine and preserve original evidence.

The worker claims a 60-second lease, excludes stale owners, applies bounded retries and records failure after five attempts. Pending or paused sources do not produce forecasts. Inputs available when the worker actually issues the forecast define the cutoff. Jobs with the same evidence/model digest reuse one receipt.

Each immutable receipt retains clinic/patient/source, issue and cutoff, model identity/checksum, input digest and compact evidence. It stores the latest 96 input readings and full count; original observations remain durable. Versioned receipt values are never refreshed in place when new data arrives.

Actual prior receipts and arrived exact-target outcomes update correction. Hypothetical earlier issuances are never reconstructed. Separate point-outcome and completed-window event-outcome records allow late intermediate measurements to establish an unknown event label without rewriting endpoint evidence.

## Browser-independent synthetic generation

Admin explicitly enables a persistent source generator. Optional seed is eight labelled synthetic past observations, all received at current time; no past issued forecasts are invented. Subsequent scheduled native readings follow real wall time and continue without an open browser.

A two-second tick tolerance represents delivery delay. Longer service interruption leaves a visible gap and schedules the next reading; missed history is not fabricated. Pause, revocation or consent withdrawal prevents collection. Cadence/next reading/source state remain inspectable.

## Care-team and companion workflow

Open episodes retain initiating and latest receipt links, count, owner, revision and disposition. The current feed's freshness is distinct from freshness at the original issue. Queue/timeline replay filtering excludes future-issued evidence.

Operational actions require expected_revision and conflict with 409 if another reviewer or a new projection changed the item. Owner changes can preserve status; review progresses new → reviewed → follow-up planned → closed. Immutable actions preserve reason, note, actor, disposition and audit time. Acknowledgement does not affect model values or benchmark scores.

Staffed windows name a responsible reviewer. Off-hours items persist and monitoring is explicitly inactive. This is no emergency or external notification service.

Patients access only their bound own-record companion. They see observed glucose, self-reported context, clinician-approved notes and published tasks. They cannot read private review notes, queues or model receipts. Predictions/dosing are disabled in the companion. Research consent records append; withdrawal revokes matching source collection. Consent does not satisfy clinical-release gates.

## Identity and operational evidence

Opaque cookie sessions are HttpOnly/SameSite=Strict, have CSRF checks, absolute expiry and API-inactivity expiry. Login rate limiting, locally encrypted TOTP enrollment, one-use invitations, deactivation and session revocation are implemented. Legacy bearer login remains for research tools. Source keys are separately scoped and hashed.

Operational SSE contains clinic-scoped metadata, with session revalidation. Persisted counts and heartbeat expose job/review/quarantine state. Readiness checks required schema, DB, local model/checksum/version and worker; it separately reports clinical readiness false. Worker errors log exception classes, without health payloads.

SQLite backup captures committed WAL; restore is offline into a new destination and verified. SQLite recovery refuses a PostgreSQL configuration. PostgreSQL requires a separately verified database-specific procedure; PostgreSQL recovery remains unverified. Authentication, restrictive permissions and successful local checks do not establish privacy compliance, production encryption or clinical suitability.

## Evidence boundary

The internal retrospective five-fold results remain tied to their original measurement-time protocol. Arrival-delay stress tests and synthetic operation checks establish separate engineering evidence. The short 50-source batch and actual PostgreSQL pipeline validation are recorded in [operational_validation.json](operational_validation.json); neither establishes sustained availability, hardware access or prospective clinical performance.

Before clinical collection/use: confirm an authorized clinic/device source, cadence/timezone/latency and intended use; obtain physician responsibilities/performance review and applicable privacy/ethics/regulatory assessment; validate encrypted deployment, off-host recovery and operational staffing; then perform an approved prospective shadow evaluation before considering supervised clinical release.
