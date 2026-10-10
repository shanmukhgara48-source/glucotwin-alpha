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
