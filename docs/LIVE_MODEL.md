# Arrival-aware model contract

This release adds an **arrival-time research adapter**, not a validated live CGM
model. The existing Shanghai model, legacy/five-fold benchmarks and model
artifacts are preserved. A clinic/device source, permitted access and measured
delivery latency are still prerequisites for live validation.

## What changed

`backend.arrival_model.arrival_forecast` accepts available measurements, an actual
server issuance time, dated context and a flattened ledger of actual prior
issuances/outcomes. It predicts once at that clock; it does not invent historical
forecasts at measurement time. All supplied timestamps require offsets or `Z`.

The adapter's primary forecast is **population**. The bounded matured residual
correction remains a separately visible **experimental hybrid**. The legacy
hybrid's small internal improvement does not transfer to this adapter. A saved
model version includes `:arrival-research-v1`, with the original trained-model
version separately recorded.

No external provider or additional model dependency is needed. Reproduce:

```sh
.venv/bin/python -m pytest tests/test_arrival_model.py -q
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/evaluate_arrivals.py --patients 20 --origins 3 --bootstrap 1000
```

## Clock and cadence policy

- `timestamp` is the actual sensor measurement time; `available_at` is the
  application's first trusted receipt time. `server_received_at`, if supplied,
  takes precedence. Measurement after issuance or receipt after issuance cannot
  enter its features. Receipt before measurement is rejected.
- `issued_at` is actual issuance time. `data_cutoff_at` is the latest available
  measurement time. A forecast target remains `data_cutoff_at + 30/60 minutes`.
  `remaining_lead_minutes` is target minus actual issuance time, not the saved
  model's measurement-anchored horizon.
- Five actual native 15-minute readings are required, with at most one second of
  interval tolerance. A 5-minute source returns `unsupported_cadence`. Native
  missing-slot gaps return `gap`. No interpolation, averaging or automatic
  resampling occurs. Measurements older than 20 minutes pause the adapter.
- Endpoint research estimates require at least 10 minutes of remaining lead.
  This provisional engineering policy is not a clinical standard.
- Raw times normalize to UTC. An explicitly supplied IANA source timezone sets
  the local hour features; otherwise a visible unverified UTC fallback is used.
  Either choice remains unvalidated against the source cohort's unverified
  dataset-local training clock. This prevents a misleading clock-compatibility
  claim; it does not establish time-of-day generalization.

Example: a reading measured at 10:00 and received/issued at 10:01 yields a
10:30 endpoint estimate with **29 minutes remaining**. It is never described as
an exact 30-minute-from-now prediction.

## Event probabilities and queue eligibility

The saved 30-minute classifier concerns native readings at `cutoff+15` and
`cutoff+30`; the 60-minute classifier concerns four such native targets. These
target lists are retained in the returned temporal metadata.

- If **any** original target is at/before actual issuance, the entire corresponding
  event probability is suppressed. The adapter does not drop a past target and
  reuse its probability as a different future event.
- When all targets remain future, the probability is labelled research risk at
  those scheduled readings, ending at the explicit target time. It is not the
  next 30/60 minutes from actual issuance and does not identify continuous
  physiological onset.
- Synthetic 30-minute research review requires latest measured glucose <=180,
  probability exceeding the preserved threshold, and **earliest** native target
  lead >=10 minutes. At strict native cadence, this permits delay up to five
  minutes. A 60-minute-only signal cannot create a primary research review.
- `clinical_queue_eligible` is always false. Clinic/public data cannot become
  clinically actionable through this adapter. Original calibration widths and
  probabilities are disclosed as unvalidated for arrival mode.

For a 20-minute delivery delay, the 30-minute endpoint still has 10 minutes
remaining, but the first original event target is past. Endpoint research
estimates remain possible; both event probabilities are suppressed.

## Actual-issuance adaptation

The authenticated caller supplies these flattened records from immutable
issuance/outcome storage:

| Input | Required fields |
|---|---|
| Reading | `timestamp`, `available_at` or `server_received_at`, `glucose_mg_dl` |
| Issued forecast | `forecast_id`, `patient_id`, `issued_at`, `target_at`, `horizon_minutes`, `population_mg_dl`, `model_version` |
| Outcome | `forecast_id`, `patient_id`, `target_at`, `horizon_minutes`, `glucose_mg_dl`, `available_at`; optional `observed_at` must equal target |

Only same-patient, same-arrival-model-version pairs contribute. The exact target
measurement and its receipt must have occurred by the current issuance clock.
Its previous forecast must have been issued before its target. Unknown,
unmatched, unavailable, different-patient or legacy-model pairs do not update.
Repeated deliveries and repeated forecasts for one horizon/target contribute
once, in receipt order. Conflicting outcomes require intake resolution.

Each horizon has its own accumulator. Residuals clip at +/-60 mg/dL, decay by
0.98, shrink with prior weight 24, and correction bounds are +/-20 mg/dL. These
are the existing engineering settings, not newly validated device physiology.
With no actually issued ledger, correction is zero regardless of how much CGM
history is supplied. Untimed baseline EHR context is excluded for clinic sources;
public/synthetic baseline availability remains a disclosed assumption.

## Measured synthetic stress evidence

`data/processed/arrival_stress.json` records seed 20261010, 20 sampled public
patients, three sparse synthetic issuances per patient and delays 0/1/5/20 minutes.
The source's printed times are assigned UTC **only for the experiment**. No
actual source timezone, device latency or live connection is claimed.

| Delay | Issuances | 30-minute event probabilities | Research reviews | Clinical queue items | Endpoint lead |
|---|---:|---:|---:|---:|---:|
| 0 minutes | 60 | 60 | 4 | 0 | 30 minutes |
| 1 minute | 60 | 60 | 4 | 0 | 29 minutes |
| 5 minutes | 60 | 60 | 4 | 0 | 25 minutes |
| 20 minutes | 60 | 0 | 0 | 0 | 10 minutes |

Each scenario passed 60 reordered-prefix checks and 60 unavailable-backfill
invariance checks. Forty exact 30-minute targets per scenario were scoreable.
On this sparse functional sample, population MAE was **12.550 mg/dL** and the
actual-issuance hybrid **12.676 mg/dL**. The hybrid did worse; this sample neither
establishes a representative accuracy estimate nor transfers the legacy gain.
Population remains primary by the declared adapter policy.

A sampled clock sensitivity check produced population forecasts 203.252
(UTC features) and 203.480 mg/dL (Asia/Kolkata features) at the same target time.
This demonstrates feature-clock sensitivity; neither assigned zone is verified
for the source cohort.

## Separate uncertainty on unchanged legacy evidence

The same report adds percentile patient-cluster bootstrap intervals to the
**unchanged full legacy out-of-fold prediction ledgers**. One thousand draws
resample the 100 patients with their fixed per-patient episode statistics. This
does not incorporate model-training/selection uncertainty and is not arrival
adapter performance.

| Legacy 30-minute event statistic | Point | Patient-bootstrap 95% interval |
|---|---:|---:|
| Episode precision | 62.96% | 59.51–66.38% |
| Overall observed-onset recall | 76.06% | 73.82–78.67% |
| Reachable-onset recall | 76.57% | 74.37–79.15% |
| False alerts / 24 eligible forecast hours | 0.919 | 0.787–1.059 |

The upper false-alert interval exceeds the provisional one-alert calibration
budget, so the report cannot promise that operating burden. Queue workload,
staffed hours and clinical usefulness require separate measurement. The
supplementary 60-minute intervals are also in the report.

Preserved trained-artifact SHA-256:
`dbbdf717605fa9cd8779a932a22dede2aac23f75fef2bd2418147e6bd9310d85`.
The report includes exact model and OOF-ledger checksums.

## Gate for a genuine issuance-anchored model

Obtain a permitted clinic/device source and measure its cadence, timezone,
identity, missingness and end-to-end receipt delay. Freeze a new protocol that
uses data available at actual issuance, age/delay features, and future native
labels strictly inside `(issued_at, issued_at+30 minutes]`. Explicitly distinguish
the most recent measured state from an unobservable instantaneous glucose state.

Chart estimates should target actual future sensor slots. An exact endpoint at
`issued_at+30` requires grid-aligned issuance or a separately established
continuous-model evaluation; a nearby or interpolated measurement cannot stand
in silently. Calibrate and validate the exact deployed artifact, then complete
clinician operating-point, privacy/operations and applicable clinical-release
gates before actionable live alerts. Until then, clinic source access remains a
dependency and this adapter remains research-only.
