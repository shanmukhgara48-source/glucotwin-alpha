"""Synthetic arrival stress checks and uncertainty for the fixed legacy OOF ledger.

No model retraining or live-device evidence. Source timestamps are assigned UTC
only for this disclosed clock experiment, not as a claim about their real zone.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.arrival_model import POLICY_VERSION, arrival_forecast, artifact_checksum
from backend.twin import observation_quality
from scripts.evaluate import load_recordings
from scripts.evaluate_clinic import episode_metrics, observed_episode_audit

SEED = 20261010


def iso(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).isoformat()


def stress_samples(recordings, patients, origins_per_patient):
    selected = {}
    for recording in recordings:
        old = selected.get(recording["patient_id"])
        if old is None or len(recording["observations"]) > len(old["observations"]):
            selected[recording["patient_id"]] = recording
    ids = sorted(selected)
    chosen = np.random.default_rng(SEED).choice(ids, min(patients, len(ids)), replace=False)
    samples = []
    for identifier in sorted(chosen):
        recording = selected[identifier]
        valid = [i for i in range(4, len(recording["observations"]))
                 if observation_quality(recording["observations"][i - 4:i + 1])["status"] == "ok"]
        positions = np.unique(np.linspace(0, len(valid) - 1, min(origins_per_patient, len(valid)), dtype=int))
        samples.append((recording, [valid[p] for p in positions]))
    return samples


def stress(samples, delay):
    summary = {"delay_minutes": delay, "n_issuances": 0, "n_native_30_targets_scored": 0,
               "n_event_probabilities_30": 0, "n_research_reviews_eligible": 0, "n_clinical_queue_eligible": 0,
               "sum_matured_sample_counts_at_issuance": 0, "n_reordering_checks": 0, "n_unavailable_backfill_checks": 0,
               "remaining_30_minute_leads": [], "synthetic_sample_population_errors": [], "synthetic_sample_arrival_hybrid_errors": []}
    for recording, indices in samples:
        original = recording["observations"]
        patient_id = recording["patient_id"]
        profile = {**recording["profile"], "patient_id": patient_id}
        ledger, exact_outcomes = [], []
        value_at = {iso(row["timestamp"]): row["glucose_mg_dl"] for row in original}
        for index in indices:
            readings = [{"timestamp": iso(row["timestamp"]), "available_at":
                         (datetime.fromisoformat(iso(row["timestamp"])) + timedelta(minutes=delay)).isoformat(),
                         "glucose_mg_dl": row["glucose_mg_dl"]} for row in original[:index + 1]]
            issuance = readings[-1]["available_at"]
            result = arrival_forecast(readings, profile, issuance, ledger, exact_outcomes, source_timezone="UTC")
            summary["n_issuances"] += 1
            summary["n_clinical_queue_eligible"] += int(result["clinical_queue_eligible"])
            summary["n_research_reviews_eligible"] += int(result["research_review_eligible"])
            summary["n_event_probabilities_30"] += any(r["horizon_minutes"] == 30 for r in result["event_risks"])
            summary["sum_matured_sample_counts_at_issuance"] += result["adaptation"]["matured_samples"]
            reordered = list(reversed(readings))
            assert arrival_forecast(reordered, profile, issuance, ledger, exact_outcomes, source_timezone="UTC") == result
            summary["n_reordering_checks"] += 1
            unavailable = {**readings[max(0, index - 2)], "available_at":
                           (datetime.fromisoformat(issuance) + timedelta(hours=1)).isoformat(), "glucose_mg_dl": 599.0}
            assert arrival_forecast(readings + [unavailable], profile, issuance, ledger, exact_outcomes, source_timezone="UTC") == result
            summary["n_unavailable_backfill_checks"] += 1
            hybrid_at = {p["horizon_minutes"]: p for p in result["forecasts"]["hybrid"]}
            for point in result["forecasts"]["population"]:
                horizon = point["horizon_minutes"]
                identifier = f"stress-{patient_id}-{delay}-{index}-{horizon}"
                ledger.append({"forecast_id": identifier, "patient_id": patient_id, "issued_at": point["issued_at"],
                               "target_at": point["target_at"], "horizon_minutes": horizon,
                               "population_mg_dl": point["glucose_mg_dl"], "model_version": result["model"]["version"]})
                actual = value_at.get(point["target_at"])
                if actual is not None:
                    exact_outcomes.append({"forecast_id": identifier, "patient_id": patient_id, "target_at": point["target_at"],
                        "horizon_minutes": horizon, "glucose_mg_dl": actual,
                        "available_at": (datetime.fromisoformat(point["target_at"]) + timedelta(minutes=delay)).isoformat()})
                if horizon == 30:
                    summary["remaining_30_minute_leads"].append(point["remaining_lead_minutes"])
                    if actual is not None:
                        summary["n_native_30_targets_scored"] += 1
                        summary["synthetic_sample_population_errors"].append(abs(point["glucose_mg_dl"] - actual))
                        summary["synthetic_sample_arrival_hybrid_errors"].append(abs(hybrid_at[30]["glucose_mg_dl"] - actual))
    for name in ["synthetic_sample_population_errors", "synthetic_sample_arrival_hybrid_errors"]:
        values = summary.pop(name)
        summary[name.replace("_errors", "_mae_mg_dl")] = float(np.mean(values)) if values else None
    summary["remaining_30_minute_leads"] = sorted(set(summary["remaining_30_minute_leads"]))
    assert summary["n_clinical_queue_eligible"] == 0
    return summary


def event_intervals(recordings, repetitions):
    grouped_recordings = defaultdict(list)
    for recording in recordings:
        grouped_recordings[recording["patient_id"]].append(recording)
    report = {}
    for horizon in [30, 60]:
        filename = ROOT / f"data/processed/clinic_oof_{horizon}.joblib"
        predictions = joblib.load(filename)
        patients = defaultdict(list)
        for prediction in predictions:
            patients[prediction["patient_id"]].append(prediction)
        sufficient = []
        for identifier in sorted(patients):
            rows = patients[identifier]
            metric = episode_metrics(rows, rows[0]["alert_threshold"])
            onsets, _ = observed_episode_audit(grouped_recordings[identifier])
            sufficient.append([metric["true_alert_episodes"], metric["false_alert_episodes"], metric["matched_event_episodes"],
                               metric["reachable_event_episodes"], len(onsets), metric["eligible_patient_days"]])
        sufficient = np.asarray(sufficient, dtype=float)
        total = sufficient.sum(axis=0)
        draws = np.random.default_rng(SEED).integers(0, len(sufficient), (repetitions, len(sufficient)))
        sampled = sufficient[draws].sum(axis=1)
        ratios = {"episode_precision": (0, None), "reachable_episode_recall": (2, 3),
                  "overall_observed_episode_recall": (2, 4), "false_alerts_per_24_eligible_hours": (1, 5)}
        estimates = {}
        for name, (numerator, denominator) in ratios.items():
            denom = sampled[:, 0] + sampled[:, 1] if denominator is None else sampled[:, denominator]
            point_denom = total[0] + total[1] if denominator is None else total[denominator]
            values = sampled[:, numerator] / np.where(denom > 0, denom, np.nan)
            estimates[name] = {"point": float(total[numerator] / point_denom),
                               "patient_bootstrap_95_ci": [float(v) for v in np.nanquantile(values, [.025, .975])]}
        report[str(horizon)] = {"n_patients": len(sufficient), "ledger_sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
            "estimates": estimates, "counts": {"true_alerts": int(total[0]), "false_alerts": int(total[1]),
                "matched_onsets": int(total[2]), "reachable_onsets": int(total[3]), "all_observed_onsets": int(total[4]),
                "eligible_patient_days": float(total[5])}}
    return report


def evaluate(patients=20, origins=3, bootstrap=1000):
    recordings, manifest, _ = load_recordings()
    samples = stress_samples(recordings, patients, origins)
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "policy_version": POLICY_VERSION,
              "status": "synthetic_arrival_stress_evidence", "artifact_sha256": artifact_checksum(),
              "source_patients": manifest["patients"], "sampled_patients": len(samples), "origins_per_patient_requested": origins,
              "seed": SEED, "stress_scenarios": [stress(samples, delay) for delay in [0, 1, 5, 20]],
              "fixed_legacy_oof_event_uncertainty": event_intervals(recordings, bootstrap),
              "bootstrap_repetitions": bootstrap, "bootstrap_unit": "patient",
              "boundaries": ["No live device, clinician review, new training, or clinical validation.",
                  "UTC assignment is synthetic and preserves printed source hours; actual source timezone is unverified.",
                  "Sparse sampled issuances learn only from these actually generated stress issuances; legacy imaginary forecasts are not used.",
                  "Sampled stress MAE is a functional measurement, not a representative accuracy estimate or transfer of the legacy benchmark.",
                  "Event CIs use the unchanged full legacy out-of-fold ledger, not arrival-mode predictions; training/selection uncertainty is excluded.",
                  "Endpoint targets stay anchored to measurement time; event targets partly in the past are suppressed."]}
    recording, indices = samples[0]
    index = indices[-1]
    readings = [{"timestamp": iso(r["timestamp"]), "available_at": iso(r["timestamp"]), "glucose_mg_dl": r["glucose_mg_dl"]}
                for r in recording["observations"][:index + 1]]
    profile = {**recording["profile"], "patient_id": recording["patient_id"]}
    clocks = [arrival_forecast(readings, profile, readings[-1]["available_at"], source_timezone=zone) for zone in ["UTC", "Asia/Kolkata"]]
    result["source_timezone_stress"] = {"patient_id": recording["patient_id"], "zones": ["UTC", "Asia/Kolkata"],
        "population_30_predictions_mg_dl": [c["forecasts"]["population"][0]["glucose_mg_dl"] for c in clocks],
        "same_target_time": clocks[0]["forecasts"]["population"][0]["target_at"] == clocks[1]["forecasts"]["population"][0]["target_at"],
        "interpretation": "Feature-clock sensitivity only; neither clock assignment is verified for the source cohort."}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients", type=int, default=20)
    parser.add_argument("--origins", type=int, default=3)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/arrival_stress.json")
    args = parser.parse_args()
    if min(args.patients, args.origins, args.bootstrap) < 1:
        parser.error("patients, origins and bootstrap must be positive")
    report = evaluate(args.patients, args.origins, args.bootstrap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"output": str(args.output), "sampled_patients": report["sampled_patients"],
                      "stress_scenarios": report["stress_scenarios"], "source_timezone_stress": report["source_timezone_stress"]}, indent=2))
