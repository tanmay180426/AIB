"""Shared paths for ML code.

Raw data lives outside the repo at %USERPROFILE%/Downloads/olist (or OLIST_DIR).
Processed datasets and model artifacts are written under ml/ and gitignored.
"""

from __future__ import annotations

import os
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]


def olist_dir() -> Path:
    env = os.getenv("OLIST_DIR")
    if env:
        return Path(env)
    return Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Downloads" / "olist"


def processed_dir() -> Path:
    p = ML_ROOT / "data" / "processed"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = ML_ROOT / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def reports_dir() -> Path:
    p = ML_ROOT / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p
