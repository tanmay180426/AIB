import json
import sys
from pathlib import Path
from datetime import date, timedelta

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml/experiments/olist_seasonal_2024/integrated_seasonal_v1"))

from app.services import integrated_seasonal_forecast as service
from app.api.routes.ml import ml_seasonal_demo
from fastapi import HTTPException


@pytest.mark.parametrize("target", ["orders", "revenue"])
@pytest.mark.parametrize("horizon", [30, 90, 365])
def test_registered_demo_artifact_loads_and_returns_aligned_finite_forecast(target, horizon):
    result = service.forecast(target, horizon)
    assert result["target"] == target
    assert result["horizon"] == horizon
    assert result["model"]["name"] == "lightgbm_recursive"
    assert len(result["forecast"]) == horizon
    assert len(result["history"]) == 365
    assert result["history"][0]["date"] == "2024-01-02"
    assert result["history"][-1]["date"] == result["training_cutoff"] == "2024-12-31"
    assert [row["date"] for row in result["history"]] == [
        (date(2024, 1, 2) + timedelta(days=i)).isoformat() for i in range(365)
    ]
    assert result["forecast"][0]["date"] == "2025-01-01"
    assert result["forecast"][-1]["date"] > result["forecast"][0]["date"]
    expected_dates = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(horizon)]
    assert [row["date"] for row in result["forecast"]] == expected_dates
    assert np.isfinite([row[target] for row in result["forecast"]]).all()
    assert all(row[target] >= 0 for row in result["forecast"])
    assert result["provenance"]["generated_days_in_final_benchmark_pct"] == 100.0
    assert result["benchmark_metrics"] is not None
    if horizon == 365:
        assert result["artifact_horizon"] == 90
        assert any('not been evaluated' in warning for warning in result['warnings'])
    else:
        assert result['artifact_horizon'] == horizon


def test_rejects_invalid_target_and_horizon():
    with pytest.raises(ValueError, match="target must be"):
        service.forecast("profit", 30)
    with pytest.raises(ValueError, match="horizon must be"):
        service.forecast("orders", 14)


def test_missing_artifact_fails_explicitly(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "ARTIFACT_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="artifact or working series is missing"):
        service.forecast("orders", 30)


def test_hash_mismatch_blocks_loading(monkeypatch, tmp_path):
    source = service.ARTIFACT_DIR
    (tmp_path / "orders_30d.joblib").write_bytes((source / "orders_30d.joblib").read_bytes())
    metadata = json.loads((source / "orders_30d.json").read_text(encoding="utf-8"))
    metadata["artifact_sha256"] = "bad-hash"
    (tmp_path / "orders_30d.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(service, "ARTIFACT_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="artifact hash"):
        service.forecast("orders", 30)


def test_incompatible_artifact_target_blocks_loading(monkeypatch, tmp_path):
    source = service.ARTIFACT_DIR
    (tmp_path / "orders_30d.joblib").write_bytes((source / "orders_30d.joblib").read_bytes())
    metadata = json.loads((source / "orders_30d.json").read_text(encoding="utf-8"))
    metadata["target"] = "revenue"
    (tmp_path / "orders_30d.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(service, "ARTIFACT_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="target or horizon"):
        service.forecast("orders", 30)


def test_api_handler_returns_validation_error_for_invalid_request():
    with pytest.raises(HTTPException) as error:
        ml_seasonal_demo(target="orders", horizon=14, user={"username": "demo"})
    assert error.value.status_code == 422


@pytest.mark.parametrize("target", ["orders", "revenue"])
@pytest.mark.parametrize("horizon", [30, 90, 365])
def test_api_handler_serves_json_forecast_for_both_targets_and_all_horizons(target, horizon):
    import json

    payload = ml_seasonal_demo(target=target, horizon=horizon, user={"username":"test"})
    assert payload["target"] == target
    assert payload["horizon"] == horizon
    assert payload["model"]["name"] == "lightgbm_recursive"
    assert payload["training_cutoff"] == "2024-12-31"
    assert len(payload["forecast"]) == horizon
    assert payload["forecast"][0]["date"] == "2025-01-01"
    json.dumps(payload, allow_nan=False)


def test_api_handler_keeps_invalid_request_errors():
    with pytest.raises(HTTPException) as error:
        ml_seasonal_demo(target="profit", horizon=30, user={"username":"test"})
    assert error.value.status_code == 422


def test_api_handler_does_not_expose_artifact_paths_on_inference_failure(monkeypatch):
    import app.services.integrated_seasonal_forecast as serving

    def fail(_target, _horizon):
        raise OSError(r"access denied: D:\private\models\sales.joblib")

    monkeypatch.setattr(serving, "forecast", fail)
    with pytest.raises(HTTPException) as error:
        ml_seasonal_demo(target="orders", horizon=30, user={"username": "test"})
    assert error.value.status_code == 503
    assert "D:\\private" not in error.value.detail
    assert "sales.joblib" not in error.value.detail
