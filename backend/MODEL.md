# GlucoTwin model and replay behavior

This implementation is a transparent forecasting research prototype. Its twin is
a damped local-trend state model with a Kalman measurement update. It is an
engineering approximation of CGM trajectories. It does not model insulin,
medication, meals, organ physiology, treatment effects, or clinical outcomes.

The state contains glucose level and change per native 15-minute step. The
transition damps the trend, and each newly available glucose reading corrects the
state through its innovation and Kalman gain. Patient adaptation estimates trend
retention and process volatility from consecutive observed glucose changes,
shrinking toward the training-cohort parameters. The same-filter pooled ablation
keeps those parameters fixed while still updating the state from incoming
observations. Comparing these variants isolates parameter adaptation from the
benefit of filtering the current patient's readings.

The initial held-out benchmark shows a small improvement over the same-filter
pooled variant at 30 minutes, while the personalized filter performs worse than
the persistence and population forecasting baselines. Visible adaptation is
implemented; superior forecasting performance has not been established. Read
the generated `data/processed/benchmark.json` for exact metrics, patient-level
uncertainty and failure cases.

The separate population gradient-boosting model uses five recent native readings,
causal trend/time features, and allowlisted age, BMI, sex and diabetes duration.
Historical demographic context currently enters that population model; it does
not initialize the Kalman twin's parameters. Missing context is passed as missing
values, and untimed laboratory values are excluded by the data workstream.

Predictions target the exact timestamps 30 and 60 minutes after issuance. Native
15-minute observations remain native. Forecasting needs five consecutive recent
readings; stale readings or a gap in that recent window pause predictions. In the
deliberate sensor-gap scenario, the last three readings are hidden and replay
time stays fixed. The API exposes only the available prefix. Older forecasts use
the state at their own issuance time, and their actuals are exposed only when the
target reading has arrived and is available.

An alert is a deterministic research label: current glucose is at or below
180 mg/dL and a future point forecast is above 180 mg/dL. It is not a probability,
diagnosis, emergency assessment, or treatment instruction. Currently high glucose
does not produce an advance-crossing alert. Evaluation defines the observed event
as any native glucose reading above 180 mg/dL within the forecast horizon; a
point-forecast classifier can miss an excursion that resolves before the endpoint.
The alert's displayed crossing time is the forecast endpoint, not an estimated
continuous crossing time.

Intervals target nominal 90% coverage. When a validation residual quantile exists,
the interval uses that fixed half-width separately for each horizon. Otherwise,
the twin uses explicitly uncalibrated Gaussian state-model intervals; the
population interval is unavailable. Empirical test coverage must be read from the
benchmark, and nominal coverage is not a guarantee for an individual patient.

Run backend checks from the app root:

```sh
.venv/bin/python -m pytest backend/tests -q
```

Run the API on a free local port:

```sh
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
```

No shared mutable patient sessions exist. Switching patients creates a fresh
prefix calculation. Alert acknowledgment remains frontend state and cannot alter
the forecast. Local prepared-data and trained-artifact caches are loaded at
server startup; restart the API after regenerating them.
