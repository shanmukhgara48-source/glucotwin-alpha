"""Causal clinic forecasts: boosted population model plus matured residual adaptation.

Engineering prediction only. Updates use observed outcomes of earlier forecasts;
never future values, untimed labs, medication advice, or a physiological claim.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from backend.twin import HORIZONS, extract_features, observation_quality, parse_time as _parse_time

ROOT = Path(__file__).resolve().parents[1]
ADAPTATION = {"prior_weight": 24.0, "decay": .98, "max_correction": 20.0, "residual_clip": 60.0}


def parse_time(value):
    """Normalize aware imports to UTC; naive source timestamps stay a virtual clock."""
    parsed = _parse_time(value)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


@lru_cache(maxsize=1)
def load_clinic_bundle(path: str | None = None) -> dict:
    target = Path(path) if path else ROOT / "data/processed/clinic_model.joblib"
    return joblib.load(target) if target.exists() else {}


def context_at(profile: dict, timestamp: str) -> dict:
    """Reconstruct historical context as it existed at the forecast issue time."""
    issue=parse_time(timestamp)
    baseline=profile.get("baseline_context",profile)
    available=baseline.get("available_at") or baseline.get("context_available_at")
    context=dict(baseline) if not available or parse_time(available)<=issue else {}
    entries=sorted(profile.get("context_entries",[]),key=lambda entry:entry.get("available_at",entry.get("observed_at",timestamp)))
    for entry in entries:
        if entry.get("kind")!="historical" or not isinstance(entry.get("value"),dict):
            continue
        arrived=parse_time(entry.get("available_at") or entry.get("observed_at") or timestamp)
        observed=parse_time(entry.get("observed_at") or entry.get("available_at") or timestamp)
        if max(arrived,observed)<=issue:
            context.update({key:value for key,value in entry["value"].items()
                            if key in {"age","sex","bmi","diabetes_duration_years"}})
    return context


def causal_corrections(rows: list[dict], population: np.ndarray, observations: list[dict],
                       horizon: int, parameters: dict | None = None) -> tuple[np.ndarray, list[dict]]:
    """One-pass corrections; each origin updates only once its exact target arrives."""
    args = {**ADAPTATION, **(parameters or {})}
    lookup = {parse_time(row["timestamp"]): float(row["glucose_mg_dl"]) for row in observations}
    pending: dict[Any, list[tuple[float, str]]] = {}
    residual_sum = weight = 0.0
    samples = 0
    corrections, states = [], []
    events = sorted([(max(parse_time(row["timestamp"]), parse_time(row.get("available_at") or row.get("arrived_at") or row["timestamp"])), parse_time(row["timestamp"])) for row in observations])
    event_index = 0
    history = []
    for row, base in zip(rows, population):
        issued = parse_time(row["timestamp"])
        while event_index < len(events) and events[event_index][0] <= issued:
            available_at, observed_at = events[event_index]
            for old_base, old_issue in pending.pop(observed_at, []):
                residual = float(np.clip(lookup[observed_at] - old_base, -args["residual_clip"], args["residual_clip"]))
                residual_sum = args["decay"] * residual_sum + residual
                weight = args["decay"] * weight + 1
                samples += 1
                correction = float(np.clip(residual_sum / (weight + args["prior_weight"]), -args["max_correction"], args["max_correction"]))
                history.append({"timestamp": available_at.isoformat(), "observed_at": observed_at.isoformat(), "forecast_issued_at": old_issue,
                                "residual_mg_dl": residual, "correction_mg_dl": correction,
                                "matured_samples": samples, "horizon_minutes": horizon})
            event_index += 1
        correction = float(np.clip(residual_sum / (weight + args["prior_weight"]), -args["max_correction"], args["max_correction"]))
        corrections.append(correction)
        states.append({"correction_mg_dl": correction, "matured_samples": samples,
                       "effective_weight": weight, "history": list(history[-24:])})
        target = issued + timedelta(minutes=horizon)
        pending.setdefault(target, []).append((float(base), row["timestamp"]))
    return np.asarray(corrections), states


def calibrated_probabilities(model, calibrator, features: np.ndarray) -> np.ndarray:
    probabilities = model.predict_proba(features)[:, 1]
    if calibrator is None:
        return probabilities
    logits = np.log(np.clip(probabilities, 1e-6, 1 - 1e-6) / np.clip(1 - probabilities, 1e-6, 1))
    return calibrator.predict_proba(logits.reshape(-1, 1))[:, 1]


def _available_observations(observations: list[dict], current_time=None) -> list[dict]:
    cutoff = parse_time(current_time) if current_time is not None else None
    rows = []
    for row in observations:
        observed = parse_time(row["timestamp"])
        arrived = parse_time(row.get("available_at") or row.get("arrived_at") or row["timestamp"])
        if cutoff is not None and (observed > cutoff or arrived > cutoff):
            continue
        rows.append({**row, "timestamp": observed.isoformat()})
    rows.sort(key=lambda item: parse_time(item["timestamp"]))
    # Identity and duplicate validation is performed at intake; avoid double adaptation.
    return list({row["timestamp"]: row for row in rows}.values())


def clinic_forecast(observations: list[dict], profile: dict | None = None,
                    current_time=None, bundle: dict | None = None) -> dict:
    """Pure prefix-only interface used by replay and imported observation streams."""
    profile = profile or {}
    bundle = load_clinic_bundle() if bundle is None else bundle
    rows = _available_observations(observations, current_time)
    quality = observation_quality(rows, parse_time(current_time) if current_time is not None else None)
    patient_id = str(profile.get("patient_id") or profile.get("id") or "")
    patient_fold = bundle.get("patient_folds", {}).get(patient_id)
    if patient_fold in bundle.get("fold_bundles", {}):
        bundle = bundle["fold_bundles"][patient_fold]
    metadata = bundle.get("metadata", {})
    model_info = {"version": metadata.get("version", "clinic-model-unavailable"),
                  "primary": metadata.get("primary", "population"),
                  "personalization_status": metadata.get("personalization_status", "experimental"),
                  "evidence": "internal retrospective validation; no prospective clinical validation",
                  "clock_policy": "Naive Shanghai timestamps are a recorded virtual clock; aware imports normalize to UTC for comparison. No source timezone is verified."}
    result = {"forecasts": {"population": [], "hybrid": []}, "event_risks": [],
              "quality": quality, "model": model_info, "forecast_history": [],
              "adaptation": {"matured_samples": 0, "correction_mg_dl": 0.0,
                             "maturity": "warming_up", "history": [], "engineering_state": {}}}
    if not rows or not bundle.get("models"):
        return result
    candidates, features = [], []
    for index in range(4, len(rows)):
        prefix = rows[index - 4:index + 1]
        issue_time = parse_time(rows[index]["timestamp"])
        arrived_in_time = all(parse_time(row.get("available_at") or row.get("arrived_at") or row["timestamp"]) <= issue_time for row in prefix)
        if observation_quality(prefix)["status"] == "ok" and arrived_in_time:
            candidates.append({"index": index, "timestamp": rows[index]["timestamp"]})
            features.append(extract_features(prefix, context_at(profile, rows[index]["timestamp"])))
    if not features:
        return result
    x = np.vstack(features)
    primary = model_info["primary"]
    all_adaptation, forecast_history = [], []
    with threadpool_limits(limits=1):
        for horizon in HORIZONS:
            regressor = bundle["models"].get(horizon)
            if regressor is None:
                continue
            base = regressor.predict(x)
            correction, states = causal_corrections(candidates, base, rows, horizon, bundle.get("adaptation"))
            predictions = {"population": base, "hybrid": base + correction}
            all_adaptation.append({"horizon_minutes": horizon, **states[-1]})
            if quality["status"] == "ok" and candidates[-1]["index"] == len(rows) - 1:
                now = parse_time(rows[-1]["timestamp"])
                for name, values in predictions.items():
                    width = bundle.get("intervals", {}).get(name, {}).get(horizon)
                    center = float(values[-1])
                    result["forecasts"][name].append({
                        "timestamp": (now + timedelta(minutes=horizon)).isoformat(), "issued_at": now.isoformat(),
                        "horizon_minutes": horizon, "glucose_mg_dl": center,
                        "lower": max(0, center - width) if width is not None else None,
                        "upper": center + width if width is not None else None,
                        "nominal_coverage": .90, "interval_method": "separate_patient_empirical_residual_quantile",
                        "model_version": model_info["version"], "correction_mg_dl": float(correction[-1]) if name == "hybrid" else 0.0})
                classifier = bundle.get("classifiers", {}).get(horizon)
                if classifier is not None:
                    p = float(calibrated_probabilities(classifier, bundle.get("probability_calibrators", {}).get(horizon), x[-1:])[0])
                    threshold = float(bundle.get("alert_thresholds", {}).get(horizon, 1.01))
                    eligible = float(rows[-1]["glucose_mg_dl"]) <= 180
                    result["event_risks"].append({"horizon_minutes": horizon, "probability": p,
                        "threshold": threshold, "exceeds_threshold": bool(eligible and p >= threshold),
                        "event_eligible": eligible, "ongoing_high": not eligible,
                        "target": "any native glucose >180 mg/dL within horizon, current glucose <=180",
                        "probability_method": "separate_patient_logistic_calibration"})
            available = {row["timestamp"]: float(row["glucose_mg_dl"]) for row in rows}
            for candidate, original, corrected in zip(candidates[-32:], base[-32:], predictions["hybrid"][-32:]):
                target = (parse_time(candidate["timestamp"]) + timedelta(minutes=horizon)).isoformat()
                outcome = available.get(target)
                forecast_history.append({"issued_at": candidate["timestamp"], "target_at": target,
                    "horizon_minutes": horizon, "population_mg_dl": float(original), "hybrid_mg_dl": float(corrected),
                    "actual_mg_dl": outcome, "absolute_error_mg_dl": abs(float(predictions[primary][candidates.index(candidate)]) - outcome) if outcome is not None else None,
                    "model_version": model_info["version"]})
    latest = next((item for item in all_adaptation if item["horizon_minutes"] == 30), all_adaptation[0] if all_adaptation else {})
    recent = np.asarray([float(row["glucose_mg_dl"]) for row in rows[-5:]])
    result["adaptation"] = {**latest, "maturity": "adapted" if latest.get("matured_samples", 0) >= 24 else "warming_up",
        "parameters": bundle.get("adaptation", ADAPTATION), "by_horizon": all_adaptation,
        "engineering_state": {"level": float(recent[-1]), "trend_mg_dl_per_15_minutes": float(recent[-1] - recent[-2]) if len(recent) > 1 else 0,
                              "volatility_mg_dl": float(recent.std()), "readings": len(rows)},
        "message": "Correction learns only when an earlier forecast target is observed; engineering state is not a metabolic simulation."}
    result["forecast_history"] = sorted(forecast_history, key=lambda item: (item["issued_at"], item["horizon_minutes"]))
    return result
