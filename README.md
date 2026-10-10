# GlucoTwin — watch the patient model learn

A working clinic monitoring research prototype for the Digital Twin Challenge 2026: **identify a patient → inspect the evolving twin → review a forecast → document follow-up → compare the observed outcome → export a consultation summary**.

**Team alpha · vnrvjiet · Shanmukh sai gara · registered size 1.** Delivery is organized into four workstreams: data/evaluation, model/backend, product/design, and research/submission.

## Run locally

Python 3.12+ and Node 20+ are required. The tested local runtime is Python 3.12.14 / Node 24.13.1. No paid services or API keys are needed. Trained artifacts and attributed anonymized data are included; setup does not retrain them unless missing.

```bash
./scripts/setup.sh
./start.sh
```

Open http://127.0.0.1:5173. The API is http://127.0.0.1:8765. On first startup, random local `admin` and `reviewer` passwords are generated in **`.run/clinic-credentials.json`**. Read that private file to sign in; never publish it. Admin can import data and set monitoring hours; reviewer can inspect evidence, record follow-up and export reports.

To run the compiled frontend and API on one origin:

```bash
./scripts/start_production.sh
```

Open http://127.0.0.1:8765. This is a local compiled demonstration, not a hosted clinical deployment. Use `GLUCOTWIN_API_PORT=8766` for another port. Development also accepts `GLUCOTWIN_UI_PORT=5174`. `.env.example` documents exported environment variables; it is not automatically loaded.

## Implemented care workflow

- Patient review queue with episode deduplication, assigned reviewer, status, overdue follow-up and freshness **at issue**.
- Native recorded CGM replay, patient context, forecast intervals and visible outcome-based adaptation.
- Primary 30-minute excursion probability; separate 60-minute evidence; ongoing high glucose and missing-data items distinguished.
- Configurable staffed windows. Outside hours, forecasts are retained for later review and inactive monitoring is visible.
- Persistent `new → reviewed → follow-up planned → closed` actions with reason, note, reviewer and audit history.
- Consultation PDFs reflecting the evidence displayed at the selected replay time, including sensor-gap restrictions.
- Administrator intake of synthetic CSV, administrator-attested anonymized Shanghai CSV, limited local FHIR R4 bundles, and simulated readings.
- Authenticated reviewer/admin roles, clinic checks, SQLite migrations, immutable forecast records and consistent backup/recovery tooling.

This is an engineering patient model, not a validated physiological simulator. Public/simulated demonstration data only. Doctor workflow review and clinical-use approvals remain pending. There is no autonomous medication recommendation or live wearable connection.

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

## Exact three-minute demonstration

1. Sign in; choose **Start demonstration**. The app selects Patient 2072 at warning cursor 853: Thursday 12:10 on the recorded clock, within the example 09:00–17:00 weekday window.
2. Inspect current glucose, calibrated 30-minute event probability, population/hybrid forecasts, maturity and input freshness.
3. **Save forecast for review**; enter a clearly simulated demonstration note; mark reviewed and plan follow-up.
4. **Reveal recorded outcome** at cursor 855; compare forecast with measured glucose 187.2 mg/dL. Save evidence at the later cursor to persist matured outcomes.
5. Show **Sensor gap** and suppressed forecasts; return to recorded mode.
6. Export the consultation PDF. Open **Model evidence** to show aggregate performance and unsuccessful predictions.

The case is retrospectively selected for understandable demonstration; historical timezone/staffing were not verified. Stored human actions use the real audit clock, which is displayed separately from recorded observation time. See [DOCTOR_REVIEW.md](docs/DOCTOR_REVIEW.md) for five pending clinician usability cases.

## Reproduce and verify

```bash
.venv/bin/python scripts/prepare_data.py
.venv/bin/python scripts/evaluate.py          # retained legacy protocol
.venv/bin/python scripts/evaluate_clinic.py   # frozen five-fold clinic protocol
.venv/bin/python -m pytest backend/tests tests
npm --prefix frontend run build
```

Full evaluation can take several minutes. Do not load untrusted joblib/pickle artifacts. Point-in-time features use observation and arrival times; adaptation uses only matured available targets. Acknowledging an alert cannot change model performance. Meals/activity/symptoms remain context until predictive value is evaluated.

## Backup and restore

```bash
.venv/bin/python scripts/backup_restore.py backup --file .run/backup.sqlite3
.venv/bin/python scripts/backup_restore.py verify --database .run/backup.sqlite3
# Stop the application before restoring; the destination must not already exist.
.venv/bin/python scripts/backup_restore.py restore --database .run/restored.sqlite3 --file .run/backup.sqlite3 --offline
# Then launch with GLUCOTWIN_DB_PATH pointing to the restored database.
```

Private runtime files and backups are excluded from the release. File permissions and hashed credentials are implemented; TLS, encryption at rest, retention/consent procedures, authorized device latency, external clinical validation and applicable approvals remain pilot gates. [PILOT_GATES.md](docs/PILOT_GATES.md) records them.

## Submission assets

The `docs/submission/` folder contains the strategy, original architecture, editable presentation, presentation PDF, doctor-review packet and explanation/demo video. Synthetic narration is disclosed; the recording includes the actual local application. [TEAM.md](docs/TEAM.md) contains registration details. Public source: https://github.com/shanmukhgara48-source/glucotwin-alpha. Registration and platform submission remain external steps.

Code: MIT. Shanghai data: CC BY 4.0 with attribution in [DATA_LICENSE.md](DATA_LICENSE.md). No CGMacros data are included. Counts: 100 patients / 109 recordings / 112,462 measured observations; 13 missing rows excluded and 11 gaps preserved. The Chinese hospital cohort does not establish Indian clinical performance.
