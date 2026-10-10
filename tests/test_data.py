"""Causality, patient grouping and observed-data audit checks."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.evaluate import examples, split_patients
from scripts.prepare_data import base_patient_id

ROOT = Path(__file__).resolve().parents[1]


def recording(gap=False):
    start = datetime(2021, 1, 1)
    rows = [{"timestamp": (start + timedelta(minutes=15 * i)).isoformat(), "glucose_mg_dl": 100 + i} for i in range(12)]
    if gap:
        rows.pop(6)
    return {"patient_id": "2000", "recording_id": "2000_0_20210101", "profile": {}, "observations": rows}


def test_repeated_recordings_share_base_patient_and_disjoint_partition():
    assert base_patient_id("2001_0_20201102") == base_patient_id("2001_1_20201117") == "2001"
    partitions = split_patients([str(2000 + i) for i in range(100)] + ["2001", "2001"])
    sets = [set(values) for values in partitions.values()]
    assert [len(values) for values in sets] == [70, 15, 15]
    assert not sets[0] & sets[1] and not sets[0] & sets[2] and not sets[1] & sets[2]
    assert len(set.union(*sets)) == 100


def test_future_values_change_labels_but_never_features():
    original = recording()
    changed = recording()
    changed["observations"][6]["glucose_mg_dl"] = 250
    before = next(row for row in examples(original)[30] if row["index"] == 4)
    after = next(row for row in examples(changed)[30] if row["index"] == 4)
    np.testing.assert_array_equal(before["features"], after["features"])
    assert before["actual"] != after["actual"]
    assert not before["event"] and after["event"]


def test_gap_is_not_interpolated_into_future_target():
    assert any(row["index"] == 4 for row in examples(recording())[30])
    assert not any(row["index"] == 4 for row in examples(recording(gap=True))[30])


def test_processed_archive_audit_and_profile_allowlist():
    directory = ROOT / "data" / "processed"
    manifest = json.loads((directory / "manifest.json").read_text())
    profiles = json.loads((directory / "recording_profiles.json").read_text())
    observations = pd.read_csv(directory / "observations.csv")
    assert manifest["matched_summary_rows"] == manifest["recordings"] == len(profiles)
    assert manifest["patients"] == observations.patient_id.nunique()
    assert manifest["observations"] == len(observations)
    assert not observations.duplicated(["recording_id", "timestamp"]).any()
    assert not manifest["imputed"] and not manifest["resampled"]
    assert observations.glucose_mg_dl.notna().all()
    assert set(manifest["profile_feature_allowlist"]) == {"age", "sex", "bmi", "diabetes_duration_years"}
    assert all("HbA1c" not in profile and "Hypoglycemia" not in profile for profile in profiles.values())


def test_saved_benchmark_partitions_are_disjoint_and_metrics_measured():
    benchmark = json.loads((ROOT / "data/processed/benchmark.json").read_text())
    partitions = benchmark["protocol"]["patient_ids"]
    assert not set(partitions["train"]) & set(partitions["evaluation"])
    assert not set(partitions["calibration"]) & set(partitions["evaluation"])
    assert benchmark["demo"]["patient_id"] in partitions["evaluation"]
    assert benchmark["status"] == "measured"
    for row in benchmark["metrics"]:
        assert row["n_predictions"] > 0 and row["mae"] > 0
        assert 0 <= row["interval_coverage"] <= 1
        assert row["mae_ci"][0] <= row["mae"] <= row["mae_ci"][1]
