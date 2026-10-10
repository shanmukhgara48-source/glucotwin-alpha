# GlucoTwin local research operations

**Release boundary: research only.** The runnable platform accepts synthetic source connections and public recorded research data. Clinic source records remain pending without enabled device intake. The API refuses startup when `GLUCOTWIN_ENV` is anything other than `research`. Patient forecasts, treatment recommendations and a clinical warning service are disabled. Working authentication, a database and operational receipts do not establish clinical readiness.

## Start the compiled local application

Run these commands from the repository root:

```sh
./scripts/setup.sh
export GLUCOTWIN_ENV=research
unset GLUCOTWIN_DATABASE_URL
./scripts/start_production.sh
```

Python 3.12+ and Node 20+ are prerequisites. Setup installs the pinned dependencies, prepares missing public research assets and builds the frontend. Despite the script's name, `start_production.sh` starts a **compiled local research demo**, bound to `127.0.0.1:8765`; it does not publish the application. `GLUCOTWIN_API_PORT` selects another free port. Do not kill an unrelated service to free a port.

The default SQLite database is `.run/clinic.sqlite3`. Initial local account credentials are generated in `.run/clinic-credentials.json`; that private ignored file contains plaintext passwords and has mode `0600`. The local encryption key is `.run/encryption.key`, also private and ignored. Account invitations can replace shared demonstration access with individually assigned accounts. Do not publish credentials, runtime databases, keys, backups or connection keys.

Environment values must be exported before launch; `.env.example` is documentation and is not automatically loaded. Optional path controls are `GLUCOTWIN_DB_PATH`, `GLUCOTWIN_CREDENTIALS_PATH` and `GLUCOTWIN_KEY_PATH`. `GLUCOTWIN_ENCRYPTION_KEY` supplies an explicit Fernet key instead of the generated local key. Keep the key stable across restarts and separately recoverable from backups. Changing it without a recovery plan invalidates encrypted MFA secrets and earlier backups.

The browser uses an HttpOnly SameSite Strict session cookie and a CSRF header for mutations. Cookies have an eight-hour expiry and cookie sessions also have a 30-minute idle timeout. `GLUCOTWIN_COOKIE_SECURE=true` requires HTTPS and should not be set for this loopback HTTP launch. Enabling that flag alone does not create an HTTPS deployment. Legacy bearer authentication exists for compatibility; its expiry and session policy must be reviewed separately before external deployment.

## Database selection and migrations

SQLite remains the default. It automatically upgrades through schema versions 1–7 at initialization. Foreign keys are enabled, the database uses WAL, and issued forecasts, outcomes, actions and audit records have update/delete guards. Back up an existing runtime database before upgrading it. There is no automatic destructive downgrade or automatic SQLite-to-PostgreSQL data import.

For an administrator-provisioned, **empty isolated research PostgreSQL database**, select the database explicitly:

```sh
export GLUCOTWIN_ENV=research
export GLUCOTWIN_DATABASE_URL='postgresql+psycopg:///glucotwin_research'
.venv/bin/python scripts/migrate_database.py
./scripts/start_production.sh
```

The example uses local socket authentication and contains no password. Supply the actual authorized database URL privately. Do not use the existing databases of another application. PostgreSQL 16.14 on the development computer was tested; installing/provisioning PostgreSQL and its production roles is an operator responsibility, not part of the application.

`migrate_database.py` applies Alembic revision `20261010_02`, reports schema version **7**, and imports no runtime rows. Startup uses the same versioned migrations. Revision 01 installs the frozen v6 relational schema, serial integer IDs, indexes, foreign keys and append-only guards. Revision 02 adds the trusted context receipt time. A checksum mismatch or an unknown startup DDL declaration fails instead of silently accepting schema drift.

| Frozen file | SHA-256 |
|---|---|
| `migrations/schema_v6.json` | `2c48ed696443483545dbe2f70ff0f719c9d71021d3424b33ca1f2e264bd5293c` |
| `migrations/schema_v7.json` | `8971cb2bc066e70abcca1291488af97720851c411cd9f099cbbd4f16b8631b9b` |

The SQLAlchemy adapter binds parameters, preserves the small existing row/cursor interface, uses statement savepoints for recoverable constraint errors, and implements `BEGIN IMMEDIATE` through a PostgreSQL transaction advisory lock. That lock deliberately serializes these research worker write transactions. This is not a demonstrated high-throughput, multi-region or highly available service. Pool limits are five connections plus five overflow connections per process.

PostgreSQL does not implement SQLite `PRAGMA integrity_check`. The compatibility readiness probe checks the connection and schema; a returned database status of `ok` is **not a PostgreSQL integrity audit**. PostgreSQL backup, disaster recovery, failover and operational least-privilege roles are not yet verified. The encrypted SQLite recovery script below does not back up PostgreSQL. Unsetting `GLUCOTWIN_DATABASE_URL` returns to the separately preserved SQLite path; it does not copy PostgreSQL records back.

## Worker and readiness controls

The API lifecycle starts one `ForecastWorker` by default. To run it as a separate research process:

```sh
export GLUCOTWIN_DISABLE_WORKER=1
./scripts/start_production.sh
```

In another terminal, export the same database/key/model environment, then run:

```sh
.venv/bin/python -m backend.worker
```

Use one worker arrangement for the local demo. In the administration operations view, inspect database/schema/model checks, heartbeat age, pending/retry/failed jobs and quarantine counts. `/api/v2/readiness` is authenticated. It returns 503 when the worker is disabled or stale, the required model is absent/mismatched, or database checks fail. `clinical_ready` remains false even when local operational readiness passes.

Accepted ingestion, source receipt and durable job commit together. Source event IDs make exact retries idempotent; conflicting values are quarantined. Jobs have 60-second leases, bounded retry delays and a five-attempt failure limit. A stale lease owner cannot issue a second receipt. Admin retry is explicit after inspecting the failure. Worker error records retain exception types rather than health payloads. Pausing/revoking a connection stops collection; revocation invalidates its scoped ingestion credential.

Use a native 15-minute synthetic connection to exercise the saved research forecast model. A faster generator demonstrates intake only and is marked unsupported for prediction. Long interruptions leave a visible gap rather than fabricating missed readings. Browser playback and wall-clock arrival receipts use distinct clocks.

## Model selection and rollback

The saved reference model is `data/processed/clinic_model.joblib`:

```text
dbbdf717605fa9cd8779a932a22dede2aac23f75fef2bd2418147e6bd9310d85
```

Set `GLUCOTWIN_EXPECTED_MODEL_SHA256` to the reviewed hash to pin readiness. Accept only trusted artifacts produced by the reviewed training process: joblib artifacts can execute code when loaded. A checksum establishes artifact identity, not clinical validity or model quality.

Stop the API and worker before selecting a model. For an approved candidate and independently recorded hash:

```sh
.venv/bin/python scripts/model_release.py \
  --candidate work/reviewed-model.joblib \
  --destination data/processed/clinic_model.joblib \
  --sha256 APPROVED_SHA256
```

The script rejects a mismatched hash, archives the previous destination in `data/processed/model-history/<previous-sha256>.joblib`, and atomically selects the candidate. Rollback uses the same command with that archived artifact and its previously recorded hash. Restart **both** API and worker after a change, update the pinned expected hash, and repeat readiness and the exact demonstration flow. Model objects/hashes are cached in each process. The automated rollback test uses harmless stand-in bytes to prove archive/checksum behavior; it does not establish a clinically approved model release.

Arrival mode keeps **population forecasting primary** and patient residual adaptation experimental. Each receipt contains the actual issue clock, measurement anchor, target clock, remaining lead, source quality and model identity. Outcomes update adaptation only after an actually issued forecast matures. The 30-minute target is measurement-anchored; delivery delay reduces remaining lead. It is not relabeled “next 30 minutes from now.” Expired portions suppress the original event classifier. Native cadence, source timezone and actual arrival calibration remain clinic activation gates. See [LIVE_MODEL.md](LIVE_MODEL.md) for the contract and negative stress findings.

## Encrypted SQLite backup and verified offline restore

Back up SQLite using its consistent backup API rather than copying only its main file while WAL writes are active:

```sh
.venv/bin/python scripts/encrypted_backup.py backup \
  --database .run/clinic.sqlite3 \
  --file work/backups/research-checkpoint.gtbackup
```

Choose a new filename for every checkpoint. The script refuses an existing destination, packages a schema version and plaintext SHA-256 manifest, encrypts the snapshot using Fernet, and creates the backup with mode `0600`. The application database itself is **not encrypted at rest by this feature**. Key custody, a separate encrypted off-host copy and a recovery exercise on another computer remain operator tasks; `off_host_copy_verified` is false.

Stop **all** API/worker writers before restore. Restore into a new file so the original remains preserved:

```sh
.venv/bin/python scripts/encrypted_backup.py restore \
  --database work/recovery/recovered.sqlite3 \
  --file work/backups/research-checkpoint.gtbackup \
  --offline
```

Use the original encryption key. Wrong keys, unexpected archive contents and checksum mismatches fail. The candidate is checked with SQLite's integrity check before being copied to a new destination. `--offline` is an operator assertion; the script does not prove that every writer was stopped. After successful verification, select the restored path explicitly using `GLUCOTWIN_DB_PATH`, restart and compare expected synthetic receipts/review records. Do not overwrite the old database as a shortcut. Plain snapshots produced by `backup_restore.py` are private intermediates, not encrypted backups.

## Evidence recorded on 10 October 2026

| Check | Measured result | Boundary |
|---|---|---|
| Arrival helper temporal and policy tests | 25 passed | Synthetic/unit inputs; no device validation |
| Arrival + original hybrid/data regression | 43 passed | Includes those same 25 tests; do not add the counts |
| Actual PostgreSQL adapter/migrations | 7 passed | Isolated PostgreSQL 16.14 database; foreign keys, guards, binds, row/cursor behavior, rollback, startup allowlist and advisory lock |
| PostgreSQL startup/intake/worker integration | Cookie login; 8 accepted synthetic events; 8 completed jobs; 1 idempotent receipt using the actual saved model | Fresh v7 schema inside the same isolated validation database; clinical eligibility false |
| Encrypted SQLite recovery/model rollback | 2 passed | Disposable synthetic SQLite records and stand-in model bytes; wrong key/hash and overwrite refusal checked |

Both an existing v6 PostgreSQL schema upgraded to v7 and a fresh schema through both revisions were exercised. Only the explicitly isolated validation database was used. No clinical data was copied.

Reproduce checks from the repository root:

```sh
.venv/bin/python -m pytest tests/test_arrival_model.py tests/test_hybrid.py tests/test_data.py -q
.venv/bin/python -m pytest backend/tests/test_recovery.py -q
GLUCOTWIN_TEST_PG_URL='postgresql+psycopg:///glucotwin_validation_20261010_v3' \
  .venv/bin/python -m pytest tests/test_postgres.py -q
```

PostgreSQL tests are opt-in, leave synthetic validation rows, and reject database names without the `glucotwin_validation_` prefix. The URL above names the already authorized local validation database; provision another isolated validation database before using these tests elsewhere. These checks are not additive coverage percentages or production availability evidence.

## Activation work still pending

An authorized clinic/device partnership must establish lawful access, consent/identity binding, intended use and a doctor-reviewed workflow before private patient ingestion is considered. A supported integration must verify measurement cadence, source timezone, receipt latency and missing-data behavior. The model then needs frozen prospective validation at the real issuance clock, calibration, an agreed alert operating point and staffing/escalation procedures. Retention/deletion policy, clinical approvals, HTTPS hosting, encrypted storage, secret rotation, off-host recovery and recovery drills remain pending. No configuration switch in this release authorizes clinical use.
