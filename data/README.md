# Research data and measured benchmark

GlucoTwin uses the public ShanghaiT2DM cohort in this first prototype. It includes
100 source patients, 109 recordings and 112,462 observed CGM readings in the
checksum-verified Figshare version 5 archive. All 109 recordings match one
historical-summary row. Thirteen rows without a valid timestamp/glucose value
are excluded. Eleven gaps longer than 15 minutes remain visible. No readings
are synthesized, interpolated or resampled.

The archive and derived data carry **CC BY 4.0** independently of the software
license. See [LICENSE.txt](LICENSE.txt) and `processed/manifest.json` for the
attribution, links, checksums, exclusions and recording audit.

## Reproduce

From the repository root after installing `requirements.txt`:

```bash
python scripts/prepare_data.py
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python scripts/evaluate.py
python -m pytest tests/test_data.py -q
```

`python scripts/prepare_data.py --offline` reuses the downloaded archive and
metadata, still checking the source MD5 checksum. Preparation alone rewrites
profiles; run evaluation afterward to restore test-partition and demo metadata.

## Inputs and exclusions

`processed/observations.csv` contains measured glucose in mg/dL and original
source timestamps. Source timestamps lack timezone offsets; local clock values
are preserved. A recording's native CGM cadence is 15 minutes. Missing readings
remain gaps. The UI chooses the longest recording per source patient; evaluation
uses every appropriate recording, including repeated recordings.

Only age, sex, BMI and diabetes duration from the matched summary are allowed as
historical context. Exact collection timestamps for those fields are not supplied,
so baseline availability is an explicit prototype assumption. All laboratory
values, medication/free-text entries, complications and retrospective
hypoglycemia outcomes are excluded. Labs may have been collected after monitoring
and cannot be safely used without an availability audit.

## Benchmark protocol

Patients are shuffled once with NumPy seed 2026 into 70 training, 15 calibration
and 15 evaluation patients. All recordings from a source patient stay in one
partition. Forecasts require five consecutive prior readings. Targets at 30 and
60 minutes must have exact native future timestamps with no intervening gap.
The gradient-boosted models and shared filter parameters use training patients
only. Model-specific 90% interval widths use absolute residuals from separate
calibration patients. Test patients update their filter using only their own past
measurements; the first 24 hours are labeled online warm-up and later origins
are labeled adapted. The filter resets for each recording.

`processed/benchmark.json` contains actual metrics, protocol, phase results,
patient-bootstrap MAE confidence intervals and paired comparisons, failure
examples, interval calibration and the curated held-out demo. Windows overlap;
the bootstrap resamples patients rather than treating windows as independent.
Event precision/recall refer to forecast windows. An excursion is current
glucose <=180 mg/dL and at least one future native observation >180 within the
horizon. Predicted alerts use endpoint forecasts >180. False-alert episodes use
a 30-minute cooldown; their denominator is eligible native prediction time in
patient-days. These are research labels, not diagnoses or treatment advice.

## Honest first-build result

At 30 minutes, held-out MAE is 12.76 mg/dL for persistence, 10.53 for gradient
boosting with baseline context, 14.81 for the pooled filter and 14.48 for the
personalized filter. At 60 minutes these are 21.16, 18.76, 22.55 and 22.33.
Personalization slightly improves the same filter, while persistence and the
population model perform better overall. Removing baseline context improves
population MAE to 10.26 and 17.69; a context benefit is not established. The
personalized warning rule has low recall (6.9% at 30 minutes). These limitations
are shown in the benchmark instead of being concealed.

This is one modest held-out cohort and an engineering state model. It has no
prospective, Indian-cohort or clinical validation. It does not model treatment
effects or recommend medication changes. CGMacros is not included. The selected
demo patient/episode is chosen retrospectively for clarity, separately from
fitting, test metrics and runtime inference.

## Clinic upgrade: frozen five-fold internal retrospective evaluation

Reproduce the new clinic model separately; it does **not** overwrite the legacy
population model, filter benchmark, or single-holdout demo:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python scripts/evaluate_clinic.py --iterations 80 --bootstrap 1000
python -m pytest tests/test_hybrid.py -q
```

`processed/evaluation_protocol.json` was written before training. Five shuffled
outer patient folds each hold out 20 patients. Of the other 80 patients, 16 are
reserved solely for interval/probability calibration and alert operating-point
selection, and 64 train the models. All recordings belonging to one patient stay
together. Within the 64 training patients, three grouped inner folds choose
between two predeclared gradient-boosting configurations on 30-minute MAE.

The new forecast is the context-enabled population prediction plus a bounded
patient residual correction. The correction learns only when a previous issued
forecast's exact target is observed. It is shrunk toward zero with a prior weight
of 24, decayed by 0.98, clips individual residuals to ±60 mg/dL, and bounds the
correction to ±20 mg/dL. These values were frozen before evaluation. Forecasts
are issued from every past-valid origin even when a later missing target makes
that origin unscorable; future label availability therefore never selects the
online adaptation history.

A separate boosted classifier predicts **any future native glucose >180 mg/dL
within the horizon**, only for origins currently <=180. Logistic probability
calibration uses separate calibration patients. The alert threshold maximizes
reachable-event episode recall subject to at most one false-alert episode per
24 eligible native forecast hours on calibration patients. It remains a
provisional engineering operating point awaiting doctor review. Current glucose
already >180 is shown as ongoing high, not a predicted new excursion.

An event episode is the first above-threshold native reading reachable from an
eligible forecast origin. Repeated alerts are suppressed for one horizon, and
an event onset can be matched once. Event recall uses reachable event onsets;
it does not count unforecastable onsets during gaps/warm-up. The false-alert
rate denominator is below/equal-threshold, native, scoreable forecast time—not
all calendar time, a live clinic's staffed hours, or all events in a patient's
life. Median lead time is 15 minutes at both horizons; this is **not** a claim
of every alert providing a 30- or 60-minute lead.

### Measured out-of-fold results

| Model | 30-minute MAE, mg/dL | 60-minute MAE, mg/dL |
|---|---:|---:|
| Population + historical context | 9.812 | 17.295 |
| Population + matured residual adaptation | **9.606** | **16.620** |
| Population without historical context | 9.780 | 17.160 |
| Persistence | 11.983 | 20.186 |
| OLS linear trend | 15.385 | 27.988 |

The paired patient-bootstrap 95% confidence interval for the 30-minute hybrid
minus population MAE is **[-0.336, -0.110] mg/dL**, with point difference
-0.206 mg/dL. This supports a **small internal retrospective** adaptation
improvement over the identical population model. The hybrid is the prototype's
primary forecast under the predeclared gate. It does not establish external or
clinical superiority. Historical-context fusion does not demonstrate an accuracy
benefit against the context-free ablation.

The 30-minute classifier's out-of-fold episode precision is **62.96%**, reachable
episode recall **76.57%**, and false-alert burden **0.919 per 24 eligible hours**.
At 60 minutes these are **65.63%, 79.57%, and 0.852**. Ninety-percent empirical
interval coverage is approximately 89.7% for the hybrid at 30 minutes. Inspect
all fold results, cold-start/adapted results, Brier scores, reliability bins,
bootstrap intervals, and actual failures in `processed/clinic_benchmark.json`.
Event estimates are descriptive; patient-bootstrap event uncertainty and a
prospective reliability study remain outstanding.

### Artifact and runtime boundaries

- `clinic_model.joblib`: five fold bundles, calibrators, thresholds, interval
  widths, and patient-to-evaluation-fold routing. Known public patients are
  served by the fold that excluded them from training and calibration.
- `clinic_oof_30.joblib` and `clinic_oof_60.joblib`: compressed issued-prediction
  ledgers enabling metric verification without retraining; load only trusted,
  bundled joblib files. They are not upload formats.
- `legacy_benchmark.json`: byte-for-byte snapshot of the original benchmark;
  `benchmark.json` and `population_model.joblib` remain intact.
- New imported patients use the demonstration fold model and are outside the
  evaluated cohort. No performance claim transfers automatically to them.
- The selected demonstration is patient 2072, recording `2072_0_20210706`,
  warning cursor 853 and observed outcome cursor 855. It was selected
  retrospectively from out-of-fold predictions and is explicitly labeled.
- Naive source timestamps remain a recorded virtual clock. Timezone-aware
  imports normalize to UTC for comparisons. This does not verify a real source
  timezone or justify combining unrelated recordings on one timeline.
- Timed historical context is reconstructed as of each forecast issue time.
  Late readings cannot enter earlier feature windows, and late outcomes mature
  only after their arrival. Already persisted forecasts remain immutable.

This entire cohort and its previous holdout had already been inspected before
this upgrade. The five-fold experiment is **internal retrospective validation**,
not a newly untouched test, prospective trial, clinician review, external cohort
study, or authorization for clinical use.

The complete recordings contain **1,942 observed new excursion onsets**; all are
native consecutive-reading transitions. Thirteen lack a scoreable eligible
forecast origin, so they remain missed in the **overall observed episode recall**:
**76.06% at 30 minutes** (1,477/1,942) and **79.04% at 60 minutes**
(1,535/1,942). Reachable-only recall remains a separate metric. Forty-six
recordings start already above threshold; these prevalent states have no observed
onset and are not mislabeled as predictable new events. Forecast availability is
99.576% of native observation timestamps, including initial warm-up in the
abstention denominator; full-horizon label availability is reported separately.
Queue deduplication until review closure differs from the horizon cooldown used
in the predictive benchmark; the benchmark is not a measurement of notification
volume or clinician workload.
