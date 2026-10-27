"""Model metadata writer.

Every trained model writes a sibling JSON file describing its target, features,
evaluation metrics, dataset fingerprint, and lifecycle status. The backend reads
these files to expose honest ML status to the UI.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.paths import models_dir

VALID_STATUSES = {
    "planned",
    "data_preparation",
    "training",
    "testing",
    "integration",
    "available",
    "failed",
}


def dataset_fingerprint(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        if p.exists():
            h.update(p.name.encode())
            h.update(str(p.stat().st_size).encode())
            h.update(p.read_bytes()[:65536])
    return h.hexdigest()[:16]


def write_metadata(
    name: str,
    *,
    target: str,
    features: list[str],
    metrics: dict[str, Any],
    status: str,
    algorithm: str,
    dataset_files: list[Path] | None = None,
    notes: str = "",
    artifact: str | None = None,
) -> Path:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    meta = {
        "name": name,
        "version": "0.1.0",
        "target": target,
        "algorithm": algorithm,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset_fingerprint": dataset_fingerprint(dataset_files or []),
        "features_schema": features,
        "metrics": metrics,
        "status": status,
        "artifact": artifact,
        "notes": notes,
    }
    path = models_dir() / f"{name}.metadata.json"
    # Preserve the reviewed inference contract when an administrator explicitly
    # retrains a model. Uploading datasets never invokes these training scripts.
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if "contract" in previous:
            meta["contract"] = previous["contract"]
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path
