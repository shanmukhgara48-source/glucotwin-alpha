# v0.3 evidence additions

The current continuous release adds real server-received **synthetic** arrivals, automatic durable processing, immutable evidence, patient-scoped companion and administration. Clinic source/access remains pending. See LIVE_MODEL.md, operational_validation.json, recovery_validation.json, OPERATIONS.md and VALIDATION.md for exact evidence.

The old five-fold model result below is retained; it does not transfer to the arrival adapter. Sparse arrival adaptation was worse (12.676 versus12.550mg/dL MAE); primary forecasts remain population-based and adaptation experimental. Clinical eligibility is disabled. An immutable endpoint outcome is separate from the complete-window event outcome.

---

# GlucoTwin evidence ledger — 10 October 2026

This ledger distinguishes implemented software, measured internal research, and
work that has not yet been established. Model results come from the saved clinic
benchmark; local engineering tests do not establish clinical readiness.

## Evidence status

| Area | Evidence and current boundary |
|---|---|
| Clinic workflow | Authenticated reviewer/admin accounts; clinic-scoped access; SQLite persistence, audit actions, immutable forecast records, appended outcomes, staffed-window configuration, review lifecycle, and consultation PDF export implemented. |
| Intake | Anonymized CSV, simulated streaming, and a limited local FHIR R4 adapter implemented. Identity, units, duplicate/conflicting readings, availability times, and transactional rollback checked. Official ABDM conformance and hospital integration are unestablished. |
| Forecasts and patient adaptation | Context-aware boosting plus bounded, shrunk patient residual correction; correction updates only when a previous exact target becomes observable. Engineering state and correction history are visible. No physiological or treatment-effect simulation. |
| Doctor workflow and operating point | **Pending.** The doctor-review packet is a review template, not completed clinical feedback or approval. The alert budget is a provisional engineering target. |
| Live-device monitoring | **Pending.** Public recorded playback and explicitly simulated intake do not establish authorized vendor access or measured end-to-end sensor latency. |
| Clinical/Indian applicability | **Pending.** No independent external cohort, prospective shadow evaluation, Indian-clinic validation, clinical effectiveness, or applicable deployment approval has been established. |
| Deployment operations | Local authentication, access tests, persistence, and consistent backup/restore checked. Encrypted hosting/storage, privacy/retention procedures, production monitoring, operational staffing, and clinical-release gates require further work. |

## Measured internal retrospective prediction results

The inspected ShanghaiT2DM archive contains **100 patients, 109 recordings, and
112,462 measured observations** at native 15-minute cadence. Eleven gaps remain;
no observations were interpolated. Thirteen invalid source rows were excluded.
The legacy holdout and this public cohort had already been inspected, so this
upgrade is explicitly **internal retrospective validation**.

The protocol was saved before training: five outer patient folds, with 64
training, 16 calibration-only, and 20 evaluation patients in each fold. Three
inner grouped folds choose among two predeclared regression configurations.
Repeated recordings from one patient never cross these partitions. All five
models, separate logistic probability calibrators, empirical interval widths,
thresholds, and patient-to-evaluation-fold routing are retained.

| Forecast model | 30-minute MAE, mg/dL | 60-minute MAE, mg/dL |
|---|---:|---:|
| Population + historical context | 9.812 | 17.295 |
| Population + matured patient correction | **9.606** | **16.620** |
| Population without historical context | 9.780 | 17.160 |
| Persistence | 11.983 | 20.186 |
| OLS linear trend | 15.385 | 27.988 |

There are **111,747** scored 30-minute and **111,509** scored 60-minute
out-of-fold predictions. The paired 30-minute hybrid minus identical population
MAE is **−0.206 mg/dL**, with patient-bootstrap 95% CI **[−0.336, −0.110]**.
That passes the frozen selection gate for a **small internal retrospective**
adaptation improvement. It does not establish external or clinical superiority.
Historical-context accuracy benefit is unestablished: context-free MAE is
slightly lower and the paired uncertainty interval includes zero.

| Dedicated excursion classifier | 30 minutes | 60 minutes |
|---|---:|---:|
| Alert-episode precision | 62.96% | 65.63% |
| Overall observed-onset recall | 76.06% | 79.04% |
| Reachable-onset recall | 76.57% | 79.57% |
| False-alert episodes / 24 eligible forecast hours | 0.919 | 0.852 |
| Brier score | 0.0248 | 0.0525 |
| Median of fold-median warning leads | 15 min | 15 min |

The target is current glucose ≤180 mg/dL and any measured native glucose
>180 within the horizon. There are **1,942 observed new onsets**; **13** have no
scoreable eligible warning origin and remain missed in overall recall. Forty-six
recordings start already high, with unobserved onset; these are prevalent states,
not predictable new events. Forecast abstention including initial warm-up is
**0.424%** of observation timestamps; unavailable full-horizon labels are reported
separately. These sampling-based numbers do not measure real-device uptime.

False-alert denominators count below/equal-threshold, valid native forecast time,
**not calendar patient-days or staffed clinic hours**. Thresholds are selected on
calibration patients; evaluated burden may exceed a particular fold's target.
Evaluation suppresses repeated alerts for one forecast horizon. The review queue
instead deduplicates an open episode until closure, so benchmark alerts are not
notification-volume or clinician-workload measurements. Event confidence
intervals and prospective operating-point reliability remain outstanding.

Hybrid 90% empirical interval coverage is **89.68% at 30 minutes** and **89.58%
at 60 minutes**. Fixed residual intervals and logistic probability calibration are
methods, not guarantees. Cold start means online adaptation during the first
24 hours of each recording; subsequent origins are labelled adapted. State resets
between recordings. All folds, phase results, reliability bins, and failure cases
are available in `data/processed/clinic_benchmark.json`.

## Runtime and demonstration distinctions

- **30 minutes is actionable:** only the 30-minute classifier creates an excursion
  warning/review item. The 60-minute risk remains separately visible and
  supplementary; a 60-minute-only signal cannot create an actionable warning.
- Records above 180 at the current time are ongoing observed high, rather than a
  prediction of a new event. Missing/unsupported readings suppress forecasts.
- Forecasts are saved explicitly; playback GET requests are read-only. Review
  acknowledgement changes workflow state, never forecast accuracy.
- Matched baseline age, sex, BMI, and duration have assumed baseline availability.
  Untimed labs/medications are excluded. New timed historical context is
  reconstructed at each issue time; late readings cannot enter older feature
  windows and residuals wait for actual arrival. Stored issuance records remain
  immutable. Meals/activity/symptoms stay labelled context.
- Known bundled patients use the outer fold excluding them from training and
  calibration. New imported profiles use a default fold and have unvalidated
  performance; import support is not new clinical evidence.
- Naive Shanghai timestamps are a historical virtual clock. Aware imports normalize
  to UTC for comparison; the source timezone and actual historical staffing are
  unverified. Unrelated patients/records are never treated as a verified match.
- Demonstration patient **2072**, recording `2072_0_20210706`: start **850**,
  warning **853**, observed outcome **855**, stable **96**, sensor-gap **853**.
  The virtual warning occurs Thursday at 12:10, within the default 09–17 window.
  Probability is **61.11%** against threshold **42%**; hybrid forecast **187.506**
  and observed +30-minute value **187.2 mg/dL**. This case was selected
  retrospectively for clarity and is not representative performance evidence.
- Runtime prediction/probability for that case exactly matches its saved
  out-of-fold ledger. Legacy benchmark files and model remain preserved.

## Local automated checks and artifact identity

`python -m pytest backend/tests tests -q`: **43 passed**, one non-blocking
Starlette test-client deprecation warning, in the audit run. Tests cover temporal
causality, availability time, patient folds, bounded/matured adaptation, gaps,
30/60 warning scope, auth/clinic access, review transitions, immutable forecasts
and outcomes, intake validation, recovery, and PDF response generation. This
ledger does not substitute for browser/visual QA or clinical validation.

One complete five-fold clinic experiment was executed. The prior statement about
two independent training runs belongs to the legacy experiment, not this upgrade.
Runtime versions recorded with the clinic results: Python **3.12.14**, NumPy
**2.5.3**, scikit-learn **1.9.1**. Load only trusted bundled joblib artifacts.

SHA-256 checksums at this audit:

- `clinic_model.joblib`: `dbbdf717605fa9cd8779a932a22dede2aac23f75fef2bd2418147e6bd9310d85`
- `population_model.joblib`: `8e43b35a4a77bab3dc1a8beb18e9c742dfefe00a98dc34b50963a7c9459bc46f`
- `evaluation_protocol.json`: `948d7e30e9ad563396c62fbf59119efc9217c9e8c5e7c15e68262433fd32f981`
- `clinic_benchmark.json`: `242af8157077b9d80bd7b214434bf7095af11ceb3bb86a29ec87b476255f8a66`

A changed model, protocol, threshold, or benchmark needs a new recorded identity
and the applicable repeat evaluation. Review the original artifacts and
`backend/CLINIC_MODEL.md`, `data/README.md`, `docs/DOCTOR_REVIEW.md`, and
`docs/PILOT_GATES.md` for the detailed boundaries.
