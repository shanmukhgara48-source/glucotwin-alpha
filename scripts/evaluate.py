"""Reproduce a patient-separated research benchmark, without future leakage.

All overlapping native windows are scored. Uncertainty is bootstrapped by
patient, and intervals are calibrated on a separate patient group.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.twin import (FEATURE_NAMES, HORIZONS, estimate_pooled_parameters,
                          extract_features, observation_quality, predict_stream)

MODELS = ["persistence", "linear_trend", "population", "pooled_filter", "personalized", "population_no_context"]
SEED = 2026
THRESHOLD = 180.0


def split_patients(patient_ids: list[str]) -> dict[str, list[str]]:
    """Repeated recordings never cross train/calibration/test boundaries."""
    ids = np.asarray(sorted(set(patient_ids)), dtype=object)
    shuffled = np.random.default_rng(SEED).permutation(ids)
    ntrain, ncal = int(len(ids) * .70), int(len(ids) * .15)
    return {"train": sorted(shuffled[:ntrain].tolist()), "calibration": sorted(shuffled[ntrain:ntrain + ncal].tolist()),
            "evaluation": sorted(shuffled[ntrain + ncal:].tolist())}


def load_recordings() -> tuple[list[dict], dict, dict]:
    directory = ROOT / "data" / "processed"
    frame = pd.read_csv(directory / "observations.csv", dtype={"patient_id": str, "recording_id": str})
    profiles = json.loads((directory / "recording_profiles.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    recordings = []
    for (pid, rid), group in frame.groupby(["patient_id", "recording_id"], sort=True):
        rows = group[["timestamp", "glucose_mg_dl"]].to_dict("records")
        recordings.append({"patient_id": pid, "recording_id": rid, "profile": profiles[rid], "observations": rows})
    return recordings, manifest, profiles


def examples(recording: dict) -> dict[int, list[dict]]:
    observations = recording["observations"]
    times = [datetime.fromisoformat(row["timestamp"]) for row in observations]
    values = np.asarray([row["glucose_mg_dl"] for row in observations], dtype=float)
    output = {h: [] for h in HORIZONS}
    for index in range(4, len(observations) - 2):
        prefix = observations[index - 4:index + 1]
        if observation_quality(prefix)["status"] != "ok":
            continue
        features = extract_features(prefix, recording["profile"])
        for horizon in HORIZONS:
            steps = horizon // 15
            if index + steps >= len(observations):
                continue
            # Exact native future timestamps: gaps do not become interpolated labels.
            if any(times[index + k] - times[index + k - 1] != timedelta(minutes=15) for k in range(1, steps + 1)):
                continue
            future_values = values[index + 1:index + steps + 1]
            crossing = np.flatnonzero(future_values > THRESHOLD)
            eligible = values[index] <= THRESHOLD
            output[horizon].append({
                "patient_id": recording["patient_id"], "recording_id": recording["recording_id"],
                "index": index, "timestamp": times[index].isoformat(),
                "elapsed_hours": (times[index] - times[0]).total_seconds() / 3600,
                "phase": "cold_start" if times[index] - times[0] < timedelta(hours=24) else "adapted",
                "features": features, "actual": float(values[index + steps]), "current": float(values[index]),
                "event_eligible": bool(eligible), "event": bool(eligible and crossing.size),
                "crossing_minutes": int((crossing[0] + 1) * 15) if eligible and crossing.size else None,
            })
    return output


def train_models(training_examples: dict, iterations: int):
    models, ablation_models = {}, {}
    for horizon in HORIZONS:
        rows = training_examples[horizon]
        x = np.vstack([row["features"] for row in rows])
        y = np.asarray([row["actual"] for row in rows])
        print(f"Training horizon={horizon} on {len(y)} windows", flush=True)
        args = dict(max_iter=iterations, max_leaf_nodes=15, learning_rate=.08,
                    l2_regularization=10, min_samples_leaf=50,
                    early_stopping=False, random_state=SEED)
        models[horizon] = HistGradientBoostingRegressor(**args).fit(x, y)
        x_no_context = x.copy()
        # Constant context columns remove patient information in the ablation.
        x_no_context[:, 10:] = 0
        ablation_models[horizon] = HistGradientBoostingRegressor(**args).fit(x_no_context, y)
    return models, ablation_models


def predict_examples(recordings: list[dict], examples_by_record: dict, models: dict,
                     ablation_models: dict, parameters: dict) -> dict:
    output = {h: {model: [] for model in MODELS} for h in HORIZONS}
    for recording in recordings:
        rid, observations = recording["recording_id"], recording["observations"]
        shared = predict_stream(observations, recording["profile"], adapt=False, pooled_parameters=parameters)
        personalized = predict_stream(observations, recording["profile"], adapt=True, pooled_parameters=parameters)
        for horizon in HORIZONS:
            rows = examples_by_record[rid][horizon]
            if not rows:
                continue
            x = np.vstack([row["features"] for row in rows])
            populations = models[horizon].predict(x)
            x_no_context = x.copy()
            x_no_context[:, 10:] = 0
            ablations = ablation_models[horizon].predict(x_no_context)
            for row, population, ablation in zip(rows, populations, ablations):
                index = row["index"]
                current = row["current"]
                # OLS line through the same five available readings, forecast at h.
                recent = np.asarray([obs["glucose_mg_dl"] for obs in observations[index - 4:index + 1]])
                slope = float(np.dot(np.arange(-2, 3), recent - recent.mean()) / 10)
                predictions = {
                    "persistence": current,
                    "linear_trend": float(recent.mean() + slope * (2 + horizon / 15)),
                    "population": float(population), "population_no_context": float(ablation),
                    "pooled_filter": next(f["glucose_mg_dl"] for f in shared[index]["forecasts"] if f["horizon_minutes"] == horizon),
                    "personalized": next(f["glucose_mg_dl"] for f in personalized[index]["forecasts"] if f["horizon_minutes"] == horizon),
                }
                metadata = {key: value for key, value in row.items() if key != "features"}
                for model, prediction in predictions.items():
                    output[horizon][model].append({**metadata, "prediction": prediction})
    return output


def interval_widths(calibration_predictions: dict) -> dict:
    widths = {model: {} for model in MODELS}
    for horizon, model_rows in calibration_predictions.items():
        for model, rows in model_rows.items():
            errors = np.abs(np.asarray([row["actual"] - row["prediction"] for row in rows]))
            widths[model][horizon] = float(np.quantile(errors, .90, method="higher"))
    return widths


def event_metrics(rows: list[dict]) -> dict:
    eligible = [row for row in rows if row["event_eligible"]]
    tp = sum(row["event"] and row["prediction"] > THRESHOLD for row in eligible)
    fp = sum(not row["event"] and row["prediction"] > THRESHOLD for row in eligible)
    fn = sum(row["event"] and row["prediction"] <= THRESHOLD for row in eligible)
    # Suppress repeated alerts for 30 minutes within a recording; count alert episodes.
    last_alert = {}
    episode_tp = episode_fp = 0
    lead_times = []
    for row in sorted(eligible, key=lambda r: (r["recording_id"], r["timestamp"])):
        if row["prediction"] <= THRESHOLD:
            continue
        timestamp = datetime.fromisoformat(row["timestamp"])
        last = last_alert.get(row["recording_id"])
        if last is not None and (timestamp - last).total_seconds() / 60 < 30:
            continue
        last_alert[row["recording_id"]] = timestamp
        if row["event"]:
            episode_tp += 1
            lead_times.append(row["crossing_minutes"])
        else:
            episode_fp += 1
    # Each unique eligible forecast origin contributes one native 15-minute interval.
    days = len(eligible) * 15 / 1440
    return {
        "precision": float(tp / (tp + fp)) if tp + fp else None,
        "recall": float(tp / (tp + fn)) if tp + fn else None,
        "event_windows": tp + fn, "alert_windows": tp + fp,
        "true_positive_windows": tp, "false_positive_windows": fp, "false_negative_windows": fn,
        "true_alert_episodes": episode_tp, "false_alert_episodes": episode_fp,
        "false_alerts_per_patient_day": float(episode_fp / days) if days else None,
        "warning_lead_time_minutes": float(np.median(lead_times)) if lead_times else None,
        "eligible_patient_days": days,
    }


def metric_row(rows: list[dict], model: str, horizon: int, phase: str,
               width: float, bootstrap: int) -> dict:
    selected = rows if phase == "all" else [row for row in rows if row["phase"] == phase]
    if not selected:
        raise ValueError(f"No examples for {model}/{horizon}/{phase}")
    actual = np.asarray([row["actual"] for row in selected])
    prediction = np.asarray([row["prediction"] for row in selected])
    absolute = np.abs(actual - prediction)
    patient_sums = defaultdict(lambda: [0.0, 0])
    for row, error in zip(selected, absolute):
        patient_sums[row["patient_id"]][0] += float(error)
        patient_sums[row["patient_id"]][1] += 1
    aggregate = np.asarray(list(patient_sums.values()))
    indices = np.random.default_rng(SEED).integers(0, len(aggregate), size=(bootstrap, len(aggregate)))
    bootstrap_mae = aggregate[indices, 0].sum(axis=1) / aggregate[indices, 1].sum(axis=1)
    lower = np.maximum(0, prediction - width)
    upper = prediction + width
    return {
        "model": model, "horizon_minutes": horizon, "phase": phase,
        "n_predictions": len(selected), "n_patients": len(patient_sums),
        "mae": float(absolute.mean()), "rmse": float(np.sqrt(np.mean((actual - prediction) ** 2))),
        "mae_ci": [float(v) for v in np.quantile(bootstrap_mae, [.025, .975])],
        "interval_coverage": float(np.mean((actual >= lower) & (actual <= upper))),
        "mean_interval_width": float(np.mean(upper - lower)),
        "interval_level": .90, **event_metrics(selected),
    }


def paired_comparison(predictions: dict, left: str, right: str, horizon: int, bootstrap: int) -> dict:
    left_rows = predictions[horizon][left]
    right_rows = predictions[horizon][right]
    aggregates = defaultdict(lambda: [0.0, 0])
    for a, b in zip(left_rows, right_rows):
        if (a["recording_id"], a["index"]) != (b["recording_id"], b["index"]):
            raise ValueError("Paired models must use identical forecast origins")
        aggregates[a["patient_id"]][0] += abs(a["prediction"] - a["actual"]) - abs(b["prediction"] - b["actual"])
        aggregates[a["patient_id"]][1] += 1
    values = np.asarray(list(aggregates.values()))
    sampled = np.random.default_rng(SEED).integers(0, len(values), size=(bootstrap, len(values)))
    difference = values[sampled, 0].sum(axis=1) / values[sampled, 1].sum(axis=1)
    ci = [float(value) for value in np.quantile(difference, [.025, .975])]
    return {"model": left, "reference": right, "horizon_minutes": horizon,
            "mae_difference": float(values[:, 0].sum() / values[:, 1].sum()),
            "mae_difference_ci": ci, "bootstrap_unit": "patient",
            "direction": "negative favors model", "inconclusive_at_95_percent": ci[0] <= 0 <= ci[1]}


def select_demo(predictions: dict, profiles: dict) -> dict:
    # Curate a measured held-out example, never a model input or validation claim.
    twin_rows = predictions[30]["personalized"]
    pop_by_key = {(row["recording_id"], row["index"]): row for row in predictions[30]["population"]}
    primary_ids = {p["recording_id"] for p in json.loads((ROOT / "data/processed/patients.json").read_text())}
    candidates = [row for row in twin_rows if row["recording_id"] in primary_ids and row["event"]
                  and row["prediction"] > THRESHOLD and row["phase"] == "adapted" and row["crossing_minutes"] == 30]
    if not candidates:
        candidates = [row for row in twin_rows if row["recording_id"] in primary_ids and row["event"] and row["prediction"] > THRESHOLD]
    if not candidates:
        candidates = [row for row in twin_rows if row["recording_id"] in primary_ids]
    selected = min(candidates, key=lambda row: abs(row["actual"] - row["prediction"]))
    rid = selected["recording_id"]
    stable = next((row for row in twin_rows if row["recording_id"] == rid and row["phase"] == "adapted"
                   and 90 < row["current"] < 145 and not row["event"] and row["prediction"] < 160), selected)
    # Give the UI a starting point a few observations before the curated warning.
    return {
        "patient_id": selected["patient_id"], "recording_id": rid,
        "cursor": max(5, selected["index"] - 3), "warning_cursor": selected["index"],
        "outcome_cursor": selected["index"] + 2, "stable_cursor": stable["index"],
        "gap_cursor": selected["index"], "issued_at": selected["timestamp"],
        "current_glucose_mg_dl": selected["current"], "twin_forecast_mg_dl": selected["prediction"],
        "population_forecast_mg_dl": pop_by_key[(rid, selected["index"])]["prediction"],
        "actual_at_30_minutes_mg_dl": selected["actual"],
        "curation_note": "Held-out recording chosen retrospectively for a clear demonstration. This selection does not affect model fitting, test metrics or runtime inputs.",
    }


def evaluate(iterations: int = 100, bootstrap: int = 1000) -> dict:
    recordings, manifest, profiles = load_recordings()
    partitions = split_patients([recording["patient_id"] for recording in recordings])
    by_partition = {name: [recording for recording in recordings if recording["patient_id"] in ids]
                    for name, ids in partitions.items()}
    print("Patient split:", {name: len(ids) for name, ids in partitions.items()}, flush=True)
    examples_by_record = {recording["recording_id"]: examples(recording) for recording in recordings}
    training_examples = {h: [row for recording in by_partition["train"] for row in examples_by_record[recording["recording_id"]][h]] for h in HORIZONS}
    with threadpool_limits(limits=1):
        models, ablations = train_models(training_examples, iterations)
        parameters = estimate_pooled_parameters([recording["observations"] for recording in by_partition["train"]])
        print("Predicting calibration patients", flush=True)
        calibration_predictions = predict_examples(by_partition["calibration"], examples_by_record, models, ablations, parameters)
        widths = interval_widths(calibration_predictions)
        print("Predicting evaluation patients", flush=True)
        evaluation_predictions = predict_examples(by_partition["evaluation"], examples_by_record, models, ablations, parameters)
    metrics = [metric_row(evaluation_predictions[h][model], model, h, phase, widths[model][h], bootstrap)
               for h in HORIZONS for model in MODELS for phase in ["all", "cold_start", "adapted"]]
    failures = []
    all_rows = {(row["model"], row["horizon_minutes"]): row for row in metrics if row["phase"] == "all"}
    comparisons = [paired_comparison(evaluation_predictions, model, reference, horizon, bootstrap)
                   for horizon in HORIZONS for model, reference in [("personalized", "pooled_filter"),
                                                                  ("personalized", "persistence"),
                                                                  ("population", "population_no_context")]]
    for horizon in HORIZONS:
        personal, pooled = all_rows[("personalized", horizon)], all_rows[("pooled_filter", horizon)]
        delta = personal["mae"] - pooled["mae"]
        if delta >= 0:
            failures.append(f"At {horizon} minutes, personalization worsens pooled-filter MAE by {delta:.2f} mg/dL on this held-out split.")
        else:
            failures.append(f"At {horizon} minutes, personalization reduces pooled-filter MAE by {-delta:.2f} mg/dL; one split does not establish general superiority.")
        context, no_context = all_rows[("population", horizon)], all_rows[("population_no_context", horizon)]
        failures.append(f"At {horizon} minutes, baseline-context fusion changes population MAE by {context['mae'] - no_context['mae']:+.2f} mg/dL versus removing age, sex, BMI and duration.")
        failures.append(f"At {horizon} minutes, personalized-filter MAE is {personal['mae'] - all_rows[('persistence', horizon)]['mae']:.2f} mg/dL worse than persistence and {personal['mae'] - context['mae']:.2f} mg/dL worse than the population model.")
        failures.append(f"At {horizon} minutes, personalized warning recall is {personal['recall']:.1%} and precision is {personal['precision']:.1%}; this warning rule is not ready for clinical use.")
    worst = sorted(evaluation_predictions[30]["personalized"], key=lambda row: abs(row["prediction"] - row["actual"]), reverse=True)[:3]
    failure_cases = [{key: row[key] for key in ["patient_id", "recording_id", "timestamp", "index", "current", "prediction", "actual"]} for row in worst]
    demo = select_demo(evaluation_predictions, profiles)
    bundle = {
        "models": models, "feature_names": FEATURE_NAMES, "training_patient_ids": partitions["train"],
        "calibration_patient_ids": partitions["calibration"], "evaluation_patient_ids": partitions["evaluation"],
        "calibration": {h: {"residual_quantile": widths["population"][h]} for h in HORIZONS},
        "twin_parameters": parameters,
        "twin_calibration": {h: {"residual_quantile": widths["personalized"][h]} for h in HORIZONS},
        "pooled_filter_calibration": {h: {"residual_quantile": widths["pooled_filter"][h]} for h in HORIZONS},
        "metadata": {"seed": SEED, "iterations": iterations, "nominal_interval_coverage": .90,
                     "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__, "scikit_learn": sklearn.__version__},
                     "interval_method": "Separate-patient 90th percentile absolute residual; empirical, no distribution-free coverage guarantee"},
    }
    benchmark = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": "measured",
        "protocol": {
            "split": "Single reproducible 70/15/15 patient-separated holdout; seed 2026. All recordings for a base patient remain together.",
            "training_patients": len(partitions["train"]), "calibration_patients": len(partitions["calibration"]),
            "evaluation_patients": len(partitions["evaluation"]), "patient_ids": partitions,
            "primary_horizon_minutes": 30, "secondary_horizon_minutes": 60,
            "target": "Observed native CGM at exactly origin + horizon; future gaps excluded, no interpolation",
            "event_definition": "Current CGM <=180 mg/dL and at least one observed future value >180 within horizon. An alert is issued if endpoint forecast >180. Precision/recall are overlapping forecast-window metrics, not diagnosis metrics.",
            "false_alert_definition": "Predicted high alert without a true future crossing; suppress alerts within 30 minutes of the previous alert per recording. Denominator is eligible native forecast time in patient-days.",
            "adaptation_rule": "Causal state updates begin immediately. cold_start = first24h of each held-out recording; adapted = origins >=24h. No future values are used; personalization resets for each recording.",
            "interval_level": .90, "interval_method": "90th percentile absolute residual from 15 separate calibration patients, per model and horizon; applied as a fixed symmetric width",
            "bootstrap_unit": "patient", "bootstrap_repetitions": bootstrap,
            "confidence_interval": "95% percentile interval for pooled window MAE, resampling evaluation patients and retaining all their windows",
            "training_windows": {str(h): len(training_examples[h]) for h in HORIZONS},
            "feature_names": FEATURE_NAMES, "hyperparameters": {"max_iter": iterations, "max_leaf_nodes": 15, "learning_rate": .08, "l2_regularization": 10, "min_samples_leaf": 50},
        },
        "cohort": {"patients": manifest["patients"], "recordings": manifest["recordings"],
                   "observations": manifest["observations"], "evaluation_patients": len(partitions["evaluation"]),
                   "evaluation_recordings": len(by_partition["evaluation"])},
        "model_labels": {"persistence": "Last observed glucose", "linear_trend": "OLS trend on last five readings", "population": "Gradient boosting + baseline context", "pooled_filter": "Shared-parameter Kalman filter", "personalized": "Adapted patient Kalman filter", "population_no_context": "Gradient boosting without baseline context"},
        "metrics": metrics, "comparisons": comparisons, "failures": failures, "failure_cases": failure_cases,
        "limitations": [
            "No prospective or clinical validation; alerts are research glucose-excursion labels, not emergencies or treatment advice.",
            "A single random patient holdout of 15 test patients is modest; repeated group splits and external-cohort validation remain future work.",
            "Windows overlap; only the MAE confidence interval is patient-bootstrapped. Event and interval estimates also need patient-level uncertainty in a larger study.",
            "First24h is an online warm-up phase, not a frozen zero-shot model. Every recording resets the patient state.",
            "Fixed residual intervals are empirical calibration; temporal and cohort dependence invalidate an unconditional coverage guarantee.",
            "Baseline context timing is assumed from matched historical summaries. All laboratory, medication and outcome fields are excluded.",
            "The twin is a damped-trend engineering state model, not a mechanistic metabolism or counterfactual treatment simulator.",
            "The evaluated alert cooldown is not a promise of clinical notification performance. Demo alerts are recalculated at the current replay cursor.",
            "CGMacros and native-timing recovery are not included in this first prototype.",
        ],
        "demo": demo, "interval_calibration_half_widths": {model: {str(h): width for h, width in hs.items()} for model, hs in widths.items()},
        "pooled_parameters": parameters,
    }
    output = ROOT / "data" / "processed"
    joblib.dump(bundle, output / "population_model.joblib", compress=3)
    (output / "benchmark.json").write_text(json.dumps(benchmark, indent=2, allow_nan=False))
    (output / "evaluation_split.json").write_text(json.dumps(partitions, indent=2))
    # Demo metadata helps the UI; it never participates in feature generation.
    patients = json.loads((output / "patients.json").read_text())
    for profile in patients:
        profile["evaluation_partition"] = next(name for name, ids in partitions.items() if profile["id"] in ids)
        if profile["id"] == demo["patient_id"]:
            profile["demo_cursor"] = demo["cursor"]
            profile["demo_patient"] = True
    (output / "patients.json").write_text(json.dumps(patients, indent=2, allow_nan=False))
    for row in metrics:
        if row["phase"] == "all":
            print(f"{row['horizon_minutes']:2}m {row['model']:22} MAE={row['mae']:.2f} RMSE={row['rmse']:.2f} coverage={row['interval_coverage']:.3f}")
    print("Demo:", demo)
    return benchmark


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args()
    evaluate(args.iterations, args.bootstrap)
