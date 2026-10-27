"""Load-only seasonal forecasting service for the isolated local demo artifacts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = REPO_ROOT / "ml/experiments/olist_seasonal_2024/integrated_seasonal_v1"
ARTIFACT_DIR = EXPERIMENT / "artifacts"
DATA_PATH = EXPERIMENT / "data/daily_working_series.csv"
METRICS_PATH = EXPERIMENT / "reports/model_comparison.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _runtime_forecast(bundle: dict, horizon: int) -> tuple[list[float], int]:
    runtime_path = EXPERIMENT / "runtime.py"
    spec = importlib.util.spec_from_file_location("abi_integrated_seasonal_runtime", runtime_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Shared seasonal inference code is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.forecast_bundle(bundle, horizon)


def _metric_row(frame: pd.DataFrame):
    if frame.empty:
        return None
    result = {}
    for key, value in frame.iloc[0].items():
        if pd.isna(value):
            result[str(key)] = None
        elif hasattr(value, "item"):
            result[str(key)] = value.item()
        else:
            result[str(key)] = value
    return result


def forecast(target: str, horizon: int) -> dict:
    if target not in {"orders", "revenue"}:
        raise ValueError("target must be orders or revenue")
    if horizon not in {30, 90, 365}:
        raise ValueError("horizon must be 30, 90, or 365 days")
    # This fitted LightGBM is a recursive one-step estimator. Its forecast
    # length is supplied at inference, so use the longest evaluated artifact
    # for a clearly marked, unvalidated 365-day extension.
    artifact_horizon = 90 if horizon == 365 else horizon
    artifact = ARTIFACT_DIR / f"{target}_{artifact_horizon}d.joblib"
    metadata_path = ARTIFACT_DIR / f"{target}_{artifact_horizon}d.json"
    if not artifact.is_file() or not metadata_path.is_file() or not DATA_PATH.is_file():
        raise FileNotFoundError(f"Seasonal demo artifact or working series is missing for {target}/{horizon}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("artifact_sha256") != _sha256(artifact):
        raise RuntimeError("Seasonal model artifact hash does not match its metadata")
    if metadata.get("dataset_sha256") != _sha256(DATA_PATH):
        raise RuntimeError("Working dataset hash does not match the frozen model metadata")
    if metadata.get("target") != target or metadata.get("horizon_days") != artifact_horizon:
        raise RuntimeError("Artifact target or horizon does not match the request")
    if horizon == 365 and (metadata.get("model_name") != "lightgbm_recursive" or
                           metadata.get("configuration", {}).get("strategy") != "recursive one-step except fixed seasonal/ETS baselines"):
        raise RuntimeError("The saved artifact is not compatible with recursive 365-day extension")
    bundle = joblib.load(artifact)
    if bundle.get("target") != target or bundle.get("horizon") != artifact_horizon:
        raise RuntimeError("Loaded artifact schema does not match the request")
    if bundle.get("training_cutoff") != metadata.get("training_cutoff") or bundle.get("feature_schema") != metadata.get("feature_schema"):
        raise RuntimeError("Loaded artifact metadata is inconsistent")
    history_values = np.asarray(bundle.get("history", []), dtype=float)
    history_dates = pd.to_datetime(bundle.get("history_dates", []), errors="coerce")
    if len(history_values) != len(history_dates) or len(history_values) < 365 or not np.isfinite(history_values).all():
        raise RuntimeError("Artifact history is missing, misaligned, or non-finite")
    if history_dates.hasnans or history_dates.is_monotonic_increasing is False or history_dates.has_duplicates:
        raise RuntimeError("Artifact history dates are invalid")
    if history_dates[-1].strftime("%Y-%m-%d") != metadata.get("training_cutoff"):
        raise RuntimeError("Artifact history cutoff does not match metadata")
    predictions, clipped = _runtime_forecast(bundle, horizon)
    if len(predictions) != horizon or not np.isfinite(predictions).all():
        raise RuntimeError("Seasonal model returned invalid forecasts")
    dates = pd.date_range(history_dates[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    data = pd.read_csv(DATA_PATH, parse_dates=["date"])
    # Keep the display window independent of the requested forecast horizon.
    # The artifact is fitted through the final working-series date, so this is
    # the latest 365 observed-in-series rows ending exactly at its cutoff.
    historical = data.tail(365)[["date", target, "data_source"]]
    metrics = pd.read_csv(METRICS_PATH)
    validation = metrics[(metrics.period.eq(2023)) & metrics.target.eq(target) & metrics.horizon.eq(artifact_horizon) & metrics.candidate.eq(metadata["model_name"])]
    benchmark = metrics[(metrics.period.eq(2024)) & metrics.target.eq(target) & metrics.horizon.eq(artifact_horizon) & metrics.candidate.eq(metadata["model_name"])]
    return {
        "target": target, "horizon": horizon, "artifact_horizon": artifact_horizon,
        "model": {"name": metadata["model_name"], "algorithm": metadata["algorithm"], "version": "integrated_seasonal_v1"},
        "training_cutoff": metadata["training_cutoff"],
        "forecast": [{"date": d.strftime("%Y-%m-%d"), target: float(value)} for d, value in zip(dates, predictions)],
        "history": [{"date": row.date.strftime("%Y-%m-%d"), "actual": float(getattr(row, target)), "data_source": row.data_source} for row in historical.itertuples(index=False)],
        "validation_metrics": _metric_row(validation),
        "benchmark_metrics": _metric_row(benchmark),
        "provenance": {"working_series": True, "synthetic_backcast_and_extension_included": True,
                       "generated_days_in_final_benchmark_pct": 100.0,
                       "note": "Forecast and metrics use the explicitly generated working series; these are not independently verified real-sales results."},
        "warnings": ["Experimental local demonstration only; not registered in production.",
                     "2023 validation and 2024 benchmark use generated working-series targets; they do not establish real-world accuracy.",
                     "Revenue is item-price sum; source currency is unverified."] +
                    (["365-day output recursively extends the saved 90-day LightGBM artifact; 365-day performance has not been evaluated."] if horizon == 365 else []) +
                    ([f"{clipped} negative raw outputs were clipped to zero."] if clipped else []),
    }
