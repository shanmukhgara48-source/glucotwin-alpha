# Arrival-aware operational research service

The v2 pipeline runs on actual server time and accepts only explicitly synthetic
connections. A `clinic_pending` connection is a planning record, without an
ingestion credential or enabled patient binding. It cannot become a live device
connection through the status API. No clinical warning service is implemented.

## Pipeline and persistence

An accepted source event, measurement and durable forecast job commit in one
transaction. The server owns `received_at`; supplied `available_at` remains
declared source metadata. Stable source-event IDs are scoped to the connection.
Identical retries reuse their original receipt. Conflicting event IDs or
measurement values enter quarantine and preserve the original reading.

The worker claims a 60-second lease, retries with bounded backoff, and marks a job
failed after five attempts, including abandoned leases. Only an explicit admin
retry resets the attempt count. A stale lease owner cannot issue a receipt. It uses
only observations and context available at the actual issue clock. Retries and
queued events sharing identical available inputs/model produce one receipt.
The input digest includes observations, trusted context and matured outcomes.

Issued values, model identity, input cutoff and digest remain immutable. Separate
point-outcome and completed-window event-outcome tables let a late intermediate
reading complete an event label without rewriting an earlier endpoint outcome.
Patient correction consumes the actual issued/outcome ledger; hypothetical past
issuances are not reconstructed. Compact receipts retain the latest 96 input
readings and the full input count/digest; original observations remain in the
clinic store.

The open review projection retains the initiating forecast and links the latest
forecast, occurrence count and revision. Current source freshness is separate
from freshness at issue. Operational review PATCH requires `expected_revision`;
a stale update receives 409. The legacy review route retains compatibility with
the original demo. Queue replay filters exclude future-issued episodes and future
latest receipts. Actions, outcomes and audit events have update/delete guards.

## API contract

All successful JSON responses use `{success:true,data:...}`.

| Route | Capability |
|---|---|
| `GET/POST /api/v2/connections` | List/create synthetic or pending source. Creation returns a scoped key once. |
| `PATCH /api/v2/connections/{id}` | Admin pause/resume/revoke. Revocation cannot be resumed. |
| `POST /api/v2/connections/{id}/rotate-key` | Admin rotates a synthetic scoped key, returned once. |
| `POST /api/v2/connections/{id}/observations` | Bound intake using `X-Connection-Key` or an authenticated synthetic-source admin. |
| `POST /api/v2/connections/{id}/generator` | Admin enables/disables persistent wall-clock generation; optional explicit synthetic seed. |
| `GET /api/v2/patients/{id}/receipts` | Clinic-scoped receipt list, including recorded captures. |
| `GET /api/v2/receipts/{id}` | Immutable snapshot, inputs, point/event outcomes and linked review. |
| `POST /api/v2/replay/capture/{patient}` | Capture a legacy recorded forecast as a canonical receipt. |
| `PATCH /api/v2/reviews/{id}` | Revision-checked status, ownership and disposition change. |
| `GET /api/v2/queue` | Review projections with separate current-feed/recorded statuses. |
| `GET /api/v2/operations` | Real persisted job/review/receipt/quarantine counts and heartbeat. |
| `GET /api/v2/events` | Clinic-scoped metadata-only SSE; session rechecked during streaming. |
| `GET /api/v2/readiness` | DB, schema, required model/checksum and worker readiness; clinical readiness false. |
| `POST /api/v2/jobs/{id}/retry` | Admin requests another bounded run of a failed job. |

Observation body: `{source_event_id,timestamp,glucose_mg_dl,available_at?}`.
Connection body: `{name,source_type,patient_id?,device_id?,cadence_minutes,
source_timezone}`. Only `synthetic` sources receive keys; bind a `SIM-*` patient.
Review body requires `{expected_revision,reason}` and accepts status, note,
next_review_at, assigned_reviewer and disposition. Omitting status changes
ownership without progressing the lifecycle.

## Generator behavior

`{enabled:true,seed:true}` imports eight labelled synthetic past measurements into
a new connection, all received at the current server time. It never creates
historical issued forecasts. The last seeded measurement is one minute old.
Subsequent measurements follow the source's real native cadence and remain
independent of the browser. Scheduled ticks tolerate two seconds of delivery
delay; a longer stopped-service interval leaves a gap and schedules the next
reading, rather than inventing missed values. Paused/revoked sources stop.

A one-minute generator is useful for visibly testing feed arrivals, but cannot
produce 15-minute-model predictions. A 15-minute generator supports the separate,
explicitly unvalidated arrival research adapter. The adapter's probabilities and
scores do not inherit clinical validity from the retrospective source benchmark.

## Runtime boundary

`ForecastWorker.start()`/`.stop()` are attached to the API lifecycle.
`GLUCOTWIN_DISABLE_WORKER=1` disables it for isolated tests. SQLite is the default;
`GLUCOTWIN_DATABASE_URL` selects the separately tested PostgreSQL compatibility
path. Local SQLite recovery uses its backup API; PostgreSQL requires its own
verified backup/restore procedure. `GLUCOTWIN_EXPECTED_MODEL_SHA256` optionally
pins readiness to the reviewed model artifact. No runtime credentials or health
payloads are written to worker error logs.

The local batch check used 50 synthetic sources, 10 intake threads, 400 measured
synthetic observations/jobs and the actual saved arrival research model. It
completed 400 jobs into 50 idempotent receipts with no failed jobs. This establishes
short local pipeline evidence, not hardware access, sustained performance,
production availability, prospective clinical accuracy or deployment approval.
