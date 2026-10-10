# GlucoTwin implementation contract

Local research prototype. Recorded ShanghaiT2DM observations only. No clinical validation.

## Data files (owned by data workstream)

- `data/processed/patients.json`: array of objects, required `id`, `display_name`, `age`, `sex`, `bmi`, `diabetes_duration_years`, `recording_id`, `dataset`, `observation_count`. One primary recording per patient for the UI; the full evaluation may use all recordings. IDs are anonymized source base IDs.
- `data/processed/observations.csv`: `patient_id,recording_id,timestamp,glucose_mg_dl` with ISO timestamps and native 15-minute observations; sorted within each recording. Retain gaps; no future imputation.
- `data/processed/manifest.json`: provenance, source URL/license, counts, exclusions, units and audit information.
- `data/processed/benchmark.json`: populated evaluation results, never placeholder scores.
- `data/processed/population_model.joblib`: scikit-learn trained model bundle with `model`, `feature_names`, training patient IDs and interval calibration if available.

## Forecast model (owned by backend workstream)

`backend/twin.py` provides a pure prefix-only forecasting function. Coordinate directly with data workstream on the Python API and population feature contract. Same-filter pooled/adapted parameter ablation is required. No model may consume observations after the replay cursor.

## API

All responses use `{ "success": true, "data": ... }` (errors use `{ "error": "..." }`).

- `GET /api/health`
- `GET /api/patients` -> data is profiles array.
- `GET /api/replay/{patient_id}?cursor=100&scenario=recorded` -> snapshot below. `sensor_gap` omits the most recent three observations, preserving current replay time to demonstrate stale-reading behavior. Acknowledgement is frontend-only state.
- `GET /api/benchmarks` -> data is benchmark.json including protocol, cohort counts, metric rows, uncertainty, limitations and failures.
- `GET /api/provenance` -> data is manifest.json.

Replay snapshot fields:

```json
{
  "patient": {"id":"...","display_name":"Patient ...","age":50,"sex":"Female","bmi":25,"diabetes_duration_years":8,"recording_id":"...","dataset":"ShanghaiT2DM"},
  "cursor":100,
  "total_observations":300,
  "current_time":"2020-01-01T12:00:00",
  "observations":[{"timestamp":"...","glucose_mg_dl":150}],
  "forecasts": {
    "twin":[{"timestamp":"...","horizon_minutes":30,"glucose_mg_dl":160,"lower":130,"upper":190}],
    "population":[{"timestamp":"...","horizon_minutes":30,"glucose_mg_dl":155,"lower":125,"upper":185}]
  },
  "quality":{"status":"ok","message":"Native 15-minute recorded readings","last_reading_at":"...","minutes_since_reading":0},
  "state":{"level":150,"trend":2,"innovation":4,"updates":100,"adaptation_samples":96,"uncertainty":12,"parameters":{}},
  "update_history":[{"timestamp":"...","observed":150,"predicted_before_update":146,"innovation":4,"gain":0.5,"level":148,"trend":2}],
  "alerts":[{"id":"...","type":"high_glucose","message":"...","horizon_minutes":30,"predicted_crossing_at":"...","threshold":180}],
  "forecast_history":[{"issued_at":"...","target_time":"...","horizon_minutes":30,"twin":160,"population":155,"actual":158}],
  "scenario":"recorded"
}
```

Intervals are 90% predictive intervals, with provenance/calibration limitations visible. `warming_up` and `gap` states return empty forecast arrays where unsupported. Forecast history actuals are revealed only when their target time is <= current replay time. Server has no shared mutable patient session.

## UI (owned by frontend workstream)

Vite React + TypeScript + Tailwind + Recharts. Proxy `/api` to `http://127.0.0.1:8765` (or `GLUCOTWIN_API_URL`). Dashboard and benchmark/provenance views. Patient selection, play/pause/step/reset, cursor scrubber, sensor-gap toggle, visible adaptation, uncertainty and population comparison. Label recorded playback and research-only status. No fake performance metrics, fabricated patient names or causal/clinical benefit claims. Empty/error/loading states should remain functional.

## Working boundaries

Data agent owns `scripts/prepare_data.py`, `scripts/evaluate.py`, `data/`, related tests. Backend agent owns `backend/`, backend tests and `requirements.txt`. Frontend agent owns `frontend/`. Root owns README, launcher, license, packaging, integration and browser validation. Avoid editing another owner's files without coordination.
