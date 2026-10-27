import csv
import shutil
from pathlib import Path

import pytest

from app.services import offline_forecast_evaluation as offline


def _copied_experiment(tmp_path: Path) -> Path:
    destination = tmp_path / "experiment"
    shutil.copytree(offline.EXPERIMENT_DIR / "reports", destination / "reports")
    return destination


def test_saved_predictions_align_and_metrics_reconcile():
    response = offline.load_offline_evaluations()
    assert response["status"] == "available"
    assert response["label"] == "Experimental validation results — not live forecasts."
    expected = {
        ("orders", 30, "peak_weighted_histgradient_recursive"),
        ("orders", 90, "lightgbm_recursive"),
        ("revenue", 30, "lightgbm_recursive"),
        ("revenue", 90, "peak_weighted_direct_ridge"),
        ("profit", 30, "lightgbm_recursive"),
        ("profit", 90, "lightgbm_recursive"),
    }
    assert {(item["target"], item["horizon"], item["model"]) for item in response["results"]} == expected
    for item in response["results"]:
        assert item["available"]
        assert item["points"]
        assert item["evaluation_period"]["from"] == item["points"][0]["date"]
        assert item["evaluation_period"]["to"] == item["points"][-1]["date"]
        assert all(point["date"] and point["actual"] is not None and point["prediction"] is not None for point in item["points"])
        assert item["metrics"]["mae"] >= 0 and item["metrics"]["rmse"] >= 0


def test_peak_results_reconcile_and_expose_origin_threshold_markers():
    response = offline.load_offline_evaluations()
    orders = next(item for item in response["results"] if item["target"] == "orders" and item["horizon"] == 30)
    assert orders["available"]
    assert orders["peak_metrics"]["recall"] is not None
    assert any(point["prediction_peak"] is not None for point in orders["points"])
    assert all(point["peak_threshold"] >= point["dip_threshold"] for point in orders["points"])
    assert any("not an independent holdout" in warning for warning in orders["warnings"])


def test_missing_saved_predictions_fail_closed(tmp_path):
    experiment = _copied_experiment(tmp_path)
    (experiment / "reports" / "validation_predictions" / "revenue_30d.csv").unlink()
    result = offline.load_offline_evaluations(experiment)
    missing = next(item for item in result["results"] if item["target"] == "revenue" and item["horizon"] == 30)
    assert not missing["available"]
    assert "missing" in missing["reason"]
    assert all(item["available"] for item in result["results"] if item["target"] != "orders" and item is not missing)


def test_date_gaps_and_metric_mismatch_are_unavailable(tmp_path):
    experiment = _copied_experiment(tmp_path)
    path = experiment / "reports" / "validation_predictions" / "revenue_30d.csv"
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
        fields = rows[0].keys()
    rows[1]["date"] = "2023-05-05"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    result = offline.load_offline_evaluations(experiment)
    affected = next(item for item in result["results"] if item["target"] == "revenue" and item["horizon"] == 30)
    assert not affected["available"]


def test_provenance_and_profit_semantics_are_explicit():
    response = offline.load_offline_evaluations()
    revenue = next(item for item in response["results"] if item["target"] == "revenue" and item["horizon"] == 30)
    profit = next(item for item in response["results"] if item["target"] == "profit" and item["horizon"] == 30)
    assert revenue["provenance"]["synthetic_extension_points"] > 0
    assert any("synthetic targets" in warning for warning in revenue["warnings"])
    assert profit["semantic_status"] == "provisional"
    assert "unverified" in profit["unit"].lower()
    assert any("formula and units are unaudited" in warning for warning in profit["warnings"])


def test_offline_endpoint_never_calls_live_forecast(monkeypatch):
    from app.api.routes import ml as route

    def forbidden(*args, **kwargs):
        pytest.fail("offline evaluation called live forecast inference")

    monkeypatch.setattr(route.ml_service, "forecast", forbidden)
    response = route.ml_offline_evaluation(user={"username": "test"})
    assert response["status"] == "available"
