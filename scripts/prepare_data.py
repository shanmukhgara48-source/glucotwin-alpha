"""Download and audit the attributed ShanghaiT2DM public research dataset.

No glucose imputation, temporal resampling, or laboratory/outcome features.
Run from the repository: python scripts/prepare_data.py
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTICLE_API = "https://api.figshare.com/v2/articles/21600933"
ARTICLE_URL = "https://figshare.com/articles/dataset/diabetes_datasets_zip/21600933"
PAPER_URL = "https://www.nature.com/articles/s41597-023-01940-7"
PROFILE_COLUMNS = {
    "age": "Age (years)",
    "bmi": "BMI (kg/m2)",
    "diabetes_duration_years": "Duration of diabetes (years)",
}


def numeric(value):
    value = pd.to_numeric(value, errors="coerce")
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def base_patient_id(recording_id: str) -> str:
    """Every repeat recording for a source patient shares the first ID field."""
    return str(recording_id).split("_")[0]


def prepare(root: Path = ROOT, download: bool = True) -> dict:
    raw = root / "data" / "raw"
    processed = root / "data" / "processed"
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    archive_path = raw / "diabetes_datasets.zip"
    metadata_path = raw / "figshare_metadata.json"
    if download:
        request = urllib.request.Request(ARTICLE_API, headers={"User-Agent": "GlucoTwin-research/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            metadata = json.load(response)
        source_file = next(item for item in metadata["files"] if item["name"] == "diabetes_datasets.zip")
        if not archive_path.exists():
            urllib.request.urlretrieve(source_file["download_url"], archive_path)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    else:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        source_file = next(item for item in metadata["files"] if item["name"] == "diabetes_datasets.zip")
    archive_bytes = archive_path.read_bytes()
    md5 = hashlib.md5(archive_bytes).hexdigest()
    if md5 != source_file["computed_md5"]:
        raise ValueError("Archive checksum differs from Figshare; remove the archive and download again")

    frames = []
    recordings = []
    recording_profiles = {}
    removed = Counter()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        summary = pd.read_excel(io.BytesIO(archive.read("Shanghai_T2DM_Summary.xlsx")))
        summary["Patient Number"] = summary["Patient Number"].astype(str).str.strip()
        summary = summary.set_index("Patient Number")
        if not summary.index.is_unique:
            raise ValueError("Historical summary contains duplicate recording IDs")
        source_names = sorted(name for name in archive.namelist()
                              if name.startswith("Shanghai_T2DM/") and name.lower().endswith((".xls", ".xlsx")))
        for name in source_names:
            recording_id = Path(name).stem
            patient_id = base_patient_id(recording_id)
            if recording_id not in summary.index:
                raise ValueError(f"No matched historical profile for {recording_id}")
            profile_row = summary.loc[recording_id]
            profile = {key: numeric(profile_row[column]) for key, column in PROFILE_COLUMNS.items()}
            profile["sex"] = {1: "Female", 2: "Male"}.get(numeric(profile_row["Gender (Female=1, Male=2)"]), "Unknown")
            profile.update({"id": patient_id, "recording_id": recording_id, "dataset": "ShanghaiT2DM"})
            raw_frame = pd.read_excel(io.BytesIO(archive.read(name)))
            # Non-CGM event rows stay outside the observation stream; never fill glucose.
            times = pd.to_datetime(raw_frame["Date"], errors="coerce")
            cgm_column = next(column for column in raw_frame.columns if str(column).strip().startswith("CGM"))
            glucose = pd.to_numeric(raw_frame[cgm_column], errors="coerce")
            valid = times.notna() & glucose.notna() & np.isfinite(glucose)
            removed["missing_glucose_or_timestamp"] += int((~valid).sum())
            frame = pd.DataFrame({"timestamp": times[valid], "glucose_mg_dl": glucose[valid].astype(float)})
            valid_range = frame.glucose_mg_dl.between(20, 600)
            removed["outside_20_to_600_mg_dl"] += int((~valid_range).sum())
            frame = frame.loc[valid_range].sort_values("timestamp", kind="stable")
            duplicates = frame.timestamp.duplicated(keep=False)
            conflicting = frame.loc[duplicates].groupby("timestamp").glucose_mg_dl.nunique()
            conflicts = conflicting[conflicting > 1].index
            removed["conflicting_duplicate_rows"] += int(frame.timestamp.isin(conflicts).sum())
            frame = frame.loc[~frame.timestamp.isin(conflicts)]
            before = len(frame)
            frame = frame.drop_duplicates("timestamp", keep="first")
            removed["identical_duplicate_rows"] += before - len(frame)
            intervals = frame.timestamp.diff().dt.total_seconds().div(60).dropna()
            frame.insert(0, "recording_id", recording_id)
            frame.insert(0, "patient_id", patient_id)
            recording = {
                "patient_id": patient_id, "recording_id": recording_id,
                "observation_count": len(frame), "start": frame.timestamp.min().isoformat(),
                "end": frame.timestamp.max().isoformat(),
                "native_15_minute_intervals": int((intervals == 15).sum()),
                "gap_intervals_over_15_minutes": int((intervals > 15).sum()),
                "other_short_intervals": int((intervals < 15).sum()),
            }
            profile.update(recording)
            recording_profiles[recording_id] = profile
            recordings.append(recording)
            frames.append(frame)
        if set(summary.index) != {Path(name).stem for name in source_names}:
            raise ValueError("Summary and sensor recording sets do not match exactly")

    observations = pd.concat(frames, ignore_index=True).sort_values(["patient_id", "recording_id", "timestamp"])
    observations.to_csv(processed / "observations.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S")
    patients = []
    for patient_id, group in observations.groupby("patient_id", sort=True):
        # A long recording supports the UI; all recordings remain in the evaluation.
        counts = group.groupby("recording_id").size().sort_values(ascending=False)
        primary = recording_profiles[str(counts.index[0])].copy()
        primary["display_name"] = f"Patient {patient_id}"
        primary["recording_count"] = len(counts)
        patients.append(primary)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "ShanghaiT2DM", "source_url": ARTICLE_URL,
        "paper_url": PAPER_URL, "article_version": metadata["version"],
        "download_url": source_file["download_url"],
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Zhao et al. A publicly available dataset of continuous glucose monitoring records in patients with diabetes. Scientific Data 10, 35 (2023). doi:10.1038/s41597-023-01940-7. Figshare diabetes_datasets.zip, article 21600933, version 5.",
        "archive_bytes": len(archive_bytes), "archive_md5": md5,
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "patients": len(patients), "recordings": len(recordings),
        "observations": len(observations), "matched_summary_rows": len(summary),
        "spreadsheet_formats": dict(Counter(Path(name).suffix for name in source_names)),
        "published_expected_counts_match": len(patients) == 100 and len(recordings) == 109,
        "units": "mg/dL", "native_sampling_minutes": 15,
        "resampled": False, "imputed": False,
        "removed_rows": dict(removed),
        "native_15_minute_intervals": sum(item["native_15_minute_intervals"] for item in recordings),
        "gap_intervals_over_15_minutes": sum(item["gap_intervals_over_15_minutes"] for item in recordings),
        "other_short_intervals": sum(item["other_short_intervals"] for item in recordings),
        "profile_feature_allowlist": [*PROFILE_COLUMNS, "sex"],
        "excluded_feature_groups": ["Laboratory values with unverified pre-CGM timing", "Hypoglycemia retrospective outcome", "Medication/event fields without verified availability", "Clinical complications and free text"],
        "context_timing": "Age, sex, BMI and duration are matched historical summary context. The source supplies no exact collection timestamp for these fields; this is a prototype baseline-context assumption. All laboratory values and retrospective outcomes are excluded.",
        "limitations": ["Single Chinese clinical cohort; no Indian or prospective clinical validation", "Hospital monitoring and treatment changes may differ from outpatient use", "CGM gaps are retained; no synthetic sensor observations", "First prototype uses ShanghaiT2DM only; CGMacros is not included"],
        "recordings_audit": recordings,
    }
    for filename, value in [("patients.json", patients), ("recording_profiles.json", recording_profiles), ("manifest.json", manifest)]:
        (processed / filename).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ["patients", "recordings", "observations", "matched_summary_rows", "removed_rows", "gap_intervals_over_15_minutes"]}, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Use an already downloaded, checksum-verified archive")
    args = parser.parse_args()
    prepare(download=not args.offline)
