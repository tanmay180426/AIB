"""Read-only presentation of saved, corrected walk-forward predictions.

This module intentionally does not load model artifacts or call the live
forecasting service. The fixed candidate map prevents request-controlled paths
or model selection.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = REPO_ROOT / "ml" / "experiments" / "olist_seasonal_2024" / "improvement"
REPORTS_DIR = EXPERIMENT_DIR / "reports"
PEAK_EXPERIMENT_DIR = REPO_ROOT / "ml" / "experiments" / "olist_seasonal_2024" / "peak_sensitive"

# Frozen selections from the corrected improvement report. Original invalid
# revenue/profit rows and non-selected models are never used here.
SELECTED = {
    ("revenue", 30): "lightgbm_recursive",
    ("revenue", 90): "ridge_direct",
    ("profit", 30): "lightgbm_recursive",
    ("profit", 90): "lightgbm_recursive",
}
METRIC_TOLERANCE = {"mae": 0.02, "rmse": 0.02, "r2": 0.001}


def _unavailable(target: str, horizon: int, candidate: str, reason: str) -> dict:
    return {
        "target": target,
        "horizon": horizon,
        "model": candidate,
        "available": False,
        "reason": reason,
        "quality_status": "validation_only",
    }


def _read_comparison(path: Path) -> dict[tuple[str, int, str], dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {
            (row.get("target", ""), int(row.get("horizon", "0")), row.get("candidate", "")): row
            for row in csv.DictReader(stream)
        }


def _finite(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite value")
    return result


def _metric_row_matches(saved: str | None, calculated: float | None, tolerance: float) -> bool:
    if calculated is None:
        return saved in (None, "", "nan", "NaN")
    if saved in (None, "", "nan", "NaN"):
        return False
    return abs(_finite(saved) - calculated) <= tolerance


def _load_one(experiment_dir: Path, target: str, horizon: int, candidate: str, comparison: dict[str, str] | None) -> dict:
    if not comparison or comparison.get("status") != "success":
        return _unavailable(target, horizon, candidate, "Matching corrected comparison metrics are unavailable.")

    prediction_path = experiment_dir / "reports" / "validation_predictions" / f"{target}_{horizon}d.csv"
    try:
        with prediction_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        expected = int(comparison["forecasted_points"])
        if not rows or len(rows) != expected:
            raise ValueError("saved prediction count does not match the corrected comparison")

        dates: list[date] = []
        actual: list[float] = []
        predicted: list[float] = []
        origins: list[str] = []
        for row in rows:
            if row.get("target") != target or int(row.get("horizon", "0")) != horizon:
                raise ValueError("prediction row target or horizon does not match the requested result")
            scored_date = date.fromisoformat(row["date"])
            if scored_date.isoformat() != row["date"]:
                raise ValueError("prediction date is not canonical ISO format")
            dates.append(scored_date)
            actual.append(_finite(row["actual"]))
            predicted.append(_finite(row[candidate]))
            origin = row.get("data_origin", "")
            if origin not in {"source_observed", "synthetic_extension"}:
                raise ValueError("prediction provenance is missing or unrecognized")
            origins.append(origin)

        if len(set(dates)) != len(dates) or dates != sorted(dates):
            raise ValueError("prediction dates are duplicated or out of order")
        if any(right - left != timedelta(days=1) for left, right in zip(dates, dates[1:])):
            raise ValueError("saved scored dates contain a calendar gap")

        errors = [pred - truth for truth, pred in zip(actual, predicted)]
        mae = sum(abs(error) for error in errors) / len(errors)
        rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
        mean_actual = sum(actual) / len(actual)
        total_variance = sum((value - mean_actual) ** 2 for value in actual)
        r2 = 1 - sum(error * error for error in errors) / total_variance if total_variance else None
        for key, value in (("mae", mae), ("rmse", rmse), ("r2", r2)):
            if not _metric_row_matches(comparison.get(key), value, METRIC_TOLERANCE[key]):
                raise ValueError(f"recomputed {key.upper()} does not match the corrected comparison")

        synthetic_count = origins.count("synthetic_extension")
        source_count = origins.count("source_observed")
        if target == "profit":
            definition = "Summed item_profit in the experiment series; formula and units are unverified."
            unit = "Unverified experiment units"
            semantic_status = "provisional"
            warnings = [
                "Profit evaluation is provisional: project documentation says the supported warehouse does not derive profit, and the experiment item_profit formula and units are unaudited.",
            ]
        else:
            definition = "Daily sum of item price excluding freight."
            unit = "Item-price units; currency is not independently certified."
            semantic_status = "documented_definition_currency_unverified"
            warnings = ["Revenue currency is not independently certified."]
        if synthetic_count:
            warnings.append(
                f"{synthetic_count:,} of {len(rows):,} scored dates ({synthetic_count / len(rows):.1%}) use generated synthetic targets; these scores do not establish real-world accuracy."
            )
        warnings.append("These are model-selection validation results, not an independent holdout or live forecast.")

        return {
            "target": target,
            "horizon": horizon,
            "model": candidate,
            "available": True,
            "quality_status": "validation_only",
            "semantic_status": semantic_status,
            "target_definition": definition,
            "unit": unit,
            "evaluation_period": {"from": dates[0].isoformat(), "to": dates[-1].isoformat()},
            "points": [
                {"date": scored_date.isoformat(), "actual": truth, "prediction": pred, "data_origin": origin}
                for scored_date, truth, pred, origin in zip(dates, actual, predicted, origins)
            ],
            "metrics": {"mae": mae, "rmse": rmse, "r2": r2},
            "origin_count": int(comparison["origin_count"]),
            "provenance": {"source_observed_points": source_count, "synthetic_extension_points": synthetic_count},
            "warnings": warnings,
        }
    except (OSError, csv.Error, KeyError, TypeError, ValueError, OverflowError):
        return _unavailable(
            target,
            horizon,
            candidate,
            "Saved predictions or their comparison metadata are missing, malformed, or inconsistent; no evaluation is shown.",
        )


def load_offline_evaluations(experiment_dir: Path | None = None) -> dict:
    """Load only the frozen selected results; missing blocks fail closed."""
    root = Path(experiment_dir) if experiment_dir is not None else EXPERIMENT_DIR
    try:
        comparison = _read_comparison(root / "reports" / "improvement_comparison.csv")
    except (OSError, csv.Error, ValueError):
        comparison = {}
    existing_results = [
        _load_one(root, target, horizon, candidate, comparison.get((target, horizon, candidate)))
        for (target, horizon), candidate in SELECTED.items()
    ]
    peak_results = load_peak_sensitive_results() if experiment_dir is None else [
        _unavailable("orders", horizon, "unavailable", "Peak-aware experiment output is unavailable for this isolated evaluation root.")
        for horizon in (30, 90)
    ]
    combined = {(item["target"], item["horizon"]): item for item in existing_results}
    combined.update({(item["target"], item["horizon"]): item for item in peak_results})
    results = [combined[(target, horizon)] for target, horizon in (
        ("orders", 30), ("orders", 90), ("revenue", 30), ("revenue", 90), ("profit", 30), ("profit", 90)
    )]
    return {
        "status": "available" if any(item["available"] for item in results) else "unavailable",
        "label": "Experimental validation results — not live forecasts.",
        "experiment": "olist_seasonal_2024 corrected improvement",
        "validation_protocol": "Chronological expanding-window validation; existing candidate-selection dates; no independent holdout.",
        "results": results,
    }


def load_peak_sensitive_results(experiment_dir: Path | None = None) -> list[dict]:
    """Present the bounded orders/revenue peak experiment in the same offline UI."""
    root = Path(experiment_dir) if experiment_dir is not None else PEAK_EXPERIMENT_DIR
    reports = root / "reports"
    try:
        comparisons = _read_comparison(reports / "model_comparison.csv")
        selected = json_load(reports / "selected_candidates.json")
        with (reports / "validation_predictions.csv").open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, csv.Error, ValueError, TypeError):
        comparisons, selected, rows = {}, {}, []

    allowed_candidates = {
        "seasonal_naive", "lightgbm_recursive", "ridge_direct",
        "peak_weighted_histgradient_recursive", "peak_weighted_direct_ridge",
    }
    results = []
    for target in ("orders", "revenue"):
        for horizon in (30, 90):
            selection = selected.get(f"{target}_{horizon}", {}) if isinstance(selected, dict) else {}
            candidate = selection.get("candidate")
            comparison = comparisons.get((target, horizon, candidate)) if candidate in allowed_candidates else None
            if not comparison or comparison.get("status") != "success":
                results.append(_unavailable(target, horizon, candidate or "unavailable", "Peak-aware saved predictions or comparison metadata are unavailable."))
                continue
            try:
                block = [row for row in rows if row.get("target") == target and int(row.get("horizon", "0")) == horizon]
                expected = int(comparison["forecasted_points"])
                if len(block) != expected:
                    raise ValueError("saved row count mismatch")
                dates, actual, predicted, threshold, trough, origins = [], [], [], [], [], []
                for row in block:
                    scored_date = date.fromisoformat(row["date"])
                    if scored_date.isoformat() != row["date"]:
                        raise ValueError("non-canonical date")
                    dates.append(scored_date)
                    actual.append(_finite(row["actual"]))
                    predicted.append(_finite(row[candidate]))
                    threshold.append(_finite(row["peak_threshold_q90_train"]))
                    trough.append(_finite(row["dip_threshold_q10_train"]))
                    origin = row.get("data_origin", "")
                    if origin not in {"source_observed", "synthetic_extension"}:
                        raise ValueError("unknown provenance")
                    origins.append(origin)
                if dates != sorted(dates) or len(set(dates)) != len(dates):
                    raise ValueError("duplicate or out-of-order dates")
                if any(right - left != timedelta(days=1) for left, right in zip(dates, dates[1:])):
                    raise ValueError("calendar gap in saved predictions")

                errors = [prediction - truth for truth, prediction in zip(actual, predicted)]
                mae = sum(abs(error) for error in errors) / len(errors)
                rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
                mean_actual = sum(actual) / len(actual)
                variance = sum((value - mean_actual) ** 2 for value in actual)
                r2 = 1 - sum(error * error for error in errors) / variance if variance else None
                if not all((
                    _metric_row_matches(comparison.get("mae"), mae, METRIC_TOLERANCE["mae"]),
                    _metric_row_matches(comparison.get("rmse"), rmse, METRIC_TOLERANCE["rmse"]),
                    _metric_row_matches(comparison.get("r2"), r2, METRIC_TOLERANCE["r2"]),
                )):
                    raise ValueError("recomputed metrics do not match candidate comparison")

                synthetic_count = origins.count("synthetic_extension")
                if target == "orders":
                    definition, unit = "Unified daily order count.", "Orders"
                else:
                    definition, unit = "Daily item-price revenue excluding freight.", "Item-price units; currency unconfirmed."
                warnings = [
                    "Peak and dip cutoffs are recomputed from training history available at each forecast origin; validation values do not set thresholds.",
                    "These are chronological model-selection validation results, not an independent holdout or live forecast.",
                ]
                if synthetic_count:
                    warnings.append(f"{synthetic_count:,} of {len(block):,} scored dates ({synthetic_count / len(block):.1%}) are generated synthetic targets; this does not establish real-world accuracy.")

                def optional_metric(name: str) -> float | None:
                    value = comparison.get(name)
                    return _finite(value) if value not in (None, "", "nan", "NaN") else None

                results.append({
                    "target": target, "horizon": horizon, "model": candidate, "available": True,
                    "quality_status": "validation_only", "semantic_status": "documented_definition" if target == "orders" else "documented_definition_currency_unverified",
                    "target_definition": definition, "unit": unit,
                    "evaluation_period": {"from": dates[0].isoformat(), "to": dates[-1].isoformat()},
                    "points": [
                        {"date": day.isoformat(), "actual": truth, "prediction": prediction,
                         "data_origin": origin, "peak_threshold": high, "dip_threshold": low,
                         "prediction_peak": prediction if prediction >= high else None,
                         "prediction_dip": prediction if prediction <= low else None}
                        for day, truth, prediction, origin, high, low in zip(dates, actual, predicted, origins, threshold, trough)
                    ],
                    "metrics": {"mae": mae, "rmse": rmse, "r2": r2},
                    "peak_metrics": {
                        "precision": optional_metric("peak_precision"),
                        "recall": optional_metric("peak_recall"),
                        "magnitude_mae": optional_metric("peak_magnitude_mae"),
                        "normal_period_mae": optional_metric("normal_period_mae"),
                        "timing_mae_days": optional_metric("peak_timing_mae_days"),
                    },
                    "origin_count": int(comparison["origin_count"]),
                    "selection_reason": selection.get("reason"),
                    "peak_definition": "A peak is a forecast/actual at or above its origin's training q90; dips are at or below training q10.",
                    "provenance": {"source_observed_points": origins.count("source_observed"), "synthetic_extension_points": synthetic_count},
                    "warnings": warnings,
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                results.append(_unavailable(target, horizon, candidate, "Peak-aware saved predictions or comparison metadata are missing, malformed, or inconsistent; no evaluation is shown."))
    return results


def json_load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
