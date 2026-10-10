# GlucoTwin — an auditable patient model and care workflow

A continuous diabetes care research platform for the Digital Twin Challenge 2026: **identify a patient → inspect the evolving twin → review a forecast → document follow-up → compare the observed outcome → export a consultation summary**.

**Team alpha · vnrvjiet · Shanmukh sai gara · registered size 1.** Delivery is organized into four workstreams: data/evaluation, model/backend, product/design, and research/submission.

## Run locally

Python 3.12+ and Node 20+ are required. The tested local runtime is Python 3.12.14 / Node 24.13.1. No paid services or API keys are needed. Trained artifacts and attributed anonymized data are included; setup does not retrain them unless missing.

```bash
./scripts/setup.sh
./start.sh
```

Open http://127.0.0.1:5173. The API is http://127.0.0.1:8765. On first startup, random local `admin`, `reviewer`, `clinician`, `coordinator` and `patient` passwords are generated in **`.run/clinic-credentials.json`**. Read that private file to sign in; never publish it. Admin can provision staff and synthetic sources; care-team accounts review evidence and publish follow-up. The patient account sees only SIM-COMPANION. New UI sessions use HttpOnly cookies and CSRF protection.

To run the compiled frontend and API on one origin:

```bash
./scripts/start_production.sh
```

Open http://127.0.0.1:8765. This is a local compiled demonstration, not a hosted clinical deployment. Use `GLUCOTWIN_API_PORT=8766` for another port. Development also accepts `GLUCOTWIN_UI_PORT=5174`. `.env.example` documents exported environment variables; it is not automatically loaded.

## Implemented v0.3 platform

- Premium routed clinician review desk and patient workspace with saved forecast selection, input-boundary lens, accessible chart summary/table and adjacent review actions.
- Server-driven synthetic streams, transactional ingestion/jobs, leased worker retries, automatic immutable forecast receipts and deduplicated review episodes.
- Measurement, trusted receipt, issuance and target clocks preserved. Delay reduces remaining lead; unsupported cadence and stale/gap histories abstain visibly.
- Optimistic review revisions, structured dispositions, assigned responsibility, monitoring windows, persistent notes and follow-up.
- Own-record patient companion/PWA: self-reported context, clinician-published tasks and approved notes, completion, consent history, revocation and a patient-safe summary.
- Admin enrollment/source controls, scoped connector keys, CSV row preview, operational briefing, audit access and staff invitation/deactivation.
- Cookie/CSRF sessions, sign-in throttling, optional encrypted TOTP with prior-session revocation, clinic/patient scope checks and append-only evidence paths.
- SQLite schema 7, explicit Alembic/SQLAlchemy PostgreSQL migrations, encrypted local SQLite recovery and checksum-verified model rollback.

**Clinic connection pending.** No CGM or authorized clinic source has been supplied. Synthetic server arrivals are a continuous engineering demonstration, not measured patient data. Recorded Shanghai cases remain separate. The only enabled environment is the public-data/synthetic research release; private clinical intake and patient forecast alerts are disabled.

No clinical or regulatory approval, live wearable integration, doctor feedback, full WCAG conformance, always-on hosting or off-host recovery is claimed. The model is an engineering predictor, not a validated physiological simulator.

## Continuous source demonstration

1. Sign in as admin and open **Operations**. Create a synthetic source with a SIM- patient ID and native 15-minute cadence.
2. Start its server generator. Its initial 8 backfilled native readings arrive now; later readings are generated on the real wall clock, independent of the browser.
3. Open the automatically created review episode and its immutable arrival receipt. Population is primary; adaptation and intervals remain research evidence.
4. Inspect trusted receipt/input cutoff, actual target and remaining lead, then document a review and follow-up.
5. Pause/revoke the source or choose an unsupported cadence to demonstrate prediction eligibility separately from connection status.
6. Sign in as patient to add context and complete an explicitly published follow-up. No research predictions are exposed.

A 15-minute source waits 15 actual minutes between native readings. Accelerated 1-minute streams test transport but correctly show unsupported model cadence. Changing browser speed does not turn synthetic data into a real CGM.

## Measured internal retrospective evidence

The frozen protocol uses five outer patient folds, grouped inner parameter selection, and separate calibration patients. All recordings from each patient stay together. The evaluation is **internal retrospective validation**: earlier patients have been inspected. A curated demo is not a performance estimate.

| Model / evidence | 30 minutes | 60 minutes |
|---|---:|---:|
| Population MAE, mg/dL | 9.812 | 17.295 |
| Hybrid MAE, mg/dL | **9.606** | **16.620** |
| Episode precision | 62.96% | 65.63% |
| Overall observed episode recall | 76.06% | 79.04% |
| False alerts per 24 eligible forecast hours | 0.919 | 0.852 |

The paired 30-minute MAE difference is **−0.206 mg/dL**, patient-bootstrap 95% CI **[−0.336, −0.110]**. This supports a small improvement from bounded residual adaptation over the **identical** population model. Historical-context benefit was inconclusive. Primary 30-minute 90% interval coverage was 89.68%; median warning lead was 15 minutes. False-alert denominators include all eligible forecast time, not only staffed clinic windows. The clinical operating point awaits doctor review.

`data/processed/clinic_benchmark.json` retains every fold, calibration results, cold-start/adapted phases and failures. [CLINIC_MODEL.md](backend/CLINIC_MODEL.md) explains the upgraded model. The legacy 70/15/15 benchmark is preserved separately; its personalized filter MAE of 14.48 is not the current primary model and its scores should not be directly compared across different cohorts.

## Current core demonstration: synthetic, recorded and gap evidence

Prepare a seeded 15-minute synthetic source in **Operations** before the short walkthrough; later readings require 15 actual minutes. The current interface uses the controls below, rather than the legacy v2 demonstration buttons.

1. Sign in as a care-team user. Open the seeded synthetic episode from the review desk and inspect its immutable arrival receipt, **What the model knew**, source quality and actual target/remaining lead. This is a synthetic engineering feed.
2. In **Review status**, save a review and then a follow-up with a reason and clearly simulated note. Reload to show the persisted action history and revision. Review state does not change predictions.
3. Open recorded Patient **2072** at cursor **853** in the patient workspace. Choose **Freeze forecast for review** to create the original recorded receipt. Historical timezone and staffing are unverified.
4. Use **Next reading** twice to reach cursor **855**, then **Freeze forecast for review** again to append the later evidence/outcome. Select the original entry under **Issued forecast receipts** and show its unchanged forecast alongside the observed **187.2 mg/dL** outcome.
5. Choose **Demonstrate sensor gap** and show withheld predictions. Choose **Restore recorded sensor** to return to recorded mode.
6. Download **Consultation summary**. Open **Model evidence** to inspect aggregate errors, uncertainty and failures.

The recorded case is retrospectively selected for clarity, not a performance estimate. Public recorded values, server-time synthetic receipts and real-clock review actions remain labelled separately. The v3 video is a narrated presentation with actual UI screenshots; it is not a recording of this complete interactive path. See [VALIDATION.md](docs/VALIDATION.md) for current interface checks and separate legacy browser evidence, and [DOCTOR_REVIEW.md](docs/DOCTOR_REVIEW.md) for pending usability cases.

## Reproduce and verify

```bash
.venv/bin/python scripts/prepare_data.py
.venv/bin/python scripts/evaluate.py          # retained legacy protocol
.venv/bin/python scripts/evaluate_clinic.py   # frozen five-fold clinic protocol
.venv/bin/python -m pytest backend/tests tests
npm --prefix frontend run build
```

Full evaluation can take several minutes. Do not load untrusted joblib/pickle artifacts. Point-in-time features use observation and arrival times; adaptation uses only matured available targets. Acknowledging an alert cannot change model performance. Meals/activity/symptoms remain context until predictive value is evaluated.

## Arrival-aware evidence and operations

The new adapter remains population-primary. In the 20-patient sparse synthetic arrival stress, population MAE was 12.550 mg/dL versus 12.676 experimental hybrid on 40 scored endpoints. No arrival personalization gain is established. Event probabilities retain the saved native target definition and are suppressed when any scheduled target is already past. Source timezone compatibility and real-device calibration are unestablished.

```bash
.venv/bin/python scripts/evaluate_arrivals.py --patients 20 --origins 3 --bootstrap 1000
# PostgreSQL: target only a dedicated research database you provision.
.venv/bin/python scripts/migrate_database.py --url 'postgresql+psycopg:///glucotwin_research'
# Export GLUCOTWIN_DATABASE_URL to the same URL before starting API/worker.
```

See [LIVE_MODEL.md](docs/LIVE_MODEL.md), [OPERATIONS.md](docs/OPERATIONS.md) and [API_CONTRACT.md](docs/API_CONTRACT.md). Actual local PostgreSQL migration, auth, intake and worker smoke tests are verified; PostgreSQL failover and backup recovery remain unverified.

## Backup, restore and model selection

```bash
.venv/bin/python scripts/encrypted_backup.py backup --database .run/clinic.sqlite3 --file .run/recovery.gtbackup
# Stop API and worker; restore into a new destination with the same separately retained key.
.venv/bin/python scripts/encrypted_backup.py restore --database .run/restored.sqlite3 --file .run/recovery.gtbackup --offline
# Select an approved trusted model artifact, preserving the prior bytes for rollback.
.venv/bin/python scripts/model_release.py --candidate /private/approved.joblib --destination data/processed/clinic_model.joblib --sha256 APPROVED_SHA256
```

The research key is generated privately under `.run/` unless supplied by environment. Keep it separate from backup copies. Source SQLite is plaintext; encrypted backups/MFA secrets do not establish encrypted clinical storage. Local recovery and rollback are tested. Off-host arrangements, operational MFA requirements, TLS, privacy/retention procedures and clinical gates remain pending.

## Submission assets

The `docs/submission/` folder contains the refreshed live strategy, continuous architecture, editable presentation, clinical-source packet and explanation video with actual interface captures. The v3 video is a narrated editable presentation with actual UI screenshots and synthesized macOS Samantha speech, not an interactive browser recording. The v0.2 materials remain as legacy reference; use the files marked Live for the current release. [TEAM.md](docs/TEAM.md) contains registration details. Public source: https://github.com/shanmukhgara48-source/glucotwin-alpha. Registration and platform submission remain external steps.

Code: MIT. Shanghai data: CC BY 4.0 with attribution in [DATA_LICENSE.md](DATA_LICENSE.md). No CGMacros data are included. Counts: 100 patients / 109 recordings / 112,462 measured observations; 13 missing rows excluded and 11 gaps preserved. The Chinese hospital cohort does not establish Indian clinical performance.
