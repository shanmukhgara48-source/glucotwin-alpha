"""Checksum-verified local model selection; restart API and worker after any selection."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def select_model(candidate: Path, destination: Path, expected_sha256: str) -> dict:
    approved_bytes = candidate.read_bytes()
    checksum = hashlib.sha256(approved_bytes).hexdigest()
    if len(expected_sha256) != 64 or checksum != expected_sha256:
        raise ValueError("Candidate does not match the approved artifact checksum.")
    if candidate.resolve() == destination.resolve():
        return {"sha256": checksum, "changed": False, "restart_required": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / "model-history"
    archive.mkdir(exist_ok=True)
    if destination.exists():
        previous = hashlib.sha256(destination.read_bytes()).hexdigest()
        preserved = archive / f"{previous}.joblib"
        if not preserved.exists():
            shutil.copy2(destination, preserved)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".model-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(approved_bytes)
    temporary.replace(destination)
    return {"sha256": checksum, "changed": True, "restart_required": True,
            "clinical_release_authorized": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps({"success": True, "data": select_model(args.candidate, args.destination, args.sha256)}, indent=2))
