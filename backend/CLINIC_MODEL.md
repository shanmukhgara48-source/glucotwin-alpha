# Clinic forecasting interface

`clinic_forecast(observations, profile=None, current_time=None, bundle=None)` is a
pure, prefix-only function. `load_clinic_bundle()` loads the trusted bundled
`data/processed/clinic_model.joblib` once. It returns:

- `forecasts.population` and `forecasts.hybrid`: timestamp, issue time, horizon,
  glucose, lower/upper empirical bounds, interval method, and model version.
- `event_risks`: calibrated probability, calibration-selected threshold,
  threshold crossing, eligible/ongoing-high flags, target definition.
- `adaptation`: matured sample count, bounded correction, correction history,
  per-horizon state, level/trend/volatility engineering state, and fixed parameters.
- `model`: fold version, selected primary model, retrospective evidence status,
  and virtual-clock policy.
- `forecast_history`: past issue/target timestamps, population and hybrid values,
  observed outcome only when available, and primary forecast absolute error.
- `quality`: fresh/initial-history/gap behavior, compatible with the legacy API.

Observations supply `timestamp` and `glucose_mg_dl`. Optional `available_at` or
`arrived_at` gates availability. Callers must enforce patient identity, allowed
units/range, consistent chronology, and conflict-free duplicate intake. The
function deduplicates timestamp-identical observations to avoid double updates.

A profile can contain `baseline_context` and `context_entries`. Only timed
`kind="historical"` dictionaries with age, sex, BMI, and diabetes duration affect
features. Both observation and availability time must be <= forecast issue time.
Meals, symptoms, and activity notes do not alter predictions. Untimed labs and
medications are excluded. Without availability metadata, matched public cohort
context follows the documented baseline-availability assumption.

Each horizon maintains an independent residual accumulator. An earlier
population forecast contributes one clipped residual only after its exact target
reading arrives. Decay and shrinkage act on matured samples. Missing targets are
not imputed. The absolute correction is bounded. The classifier is separate from
the endpoint regressor and predicts any native excursion during the horizon.
Ongoing high glucose never becomes an advance-warning event.

Every known public patient is routed to their outer evaluation fold, excluding
that patient's recordings from training/calibration. Imported patients use the
default fold model; their performance is unvalidated. Model artifacts retain all
five folds. A single case demonstrates the selected fold; aggregate benchmark
metrics use all out-of-fold predictions, not a model trained on all patients.

Primary model selection is predeclared: hybrid only if the paired 30-minute
patient-bootstrap 95% CI has a negative upper bound. This run meets the gate
with a small retrospective MAE improvement. Scores, uncertainty, all folds,
failures, calibration, and limitations are in `clinic_benchmark.json`; the legacy
engineering Kalman model remains available for comparison.

This model provides research forecasts, not physiological simulation, validated
clinical decisions, medication advice, or causal treatment effects. The alert
operating point has not yet been reviewed by a doctor.
