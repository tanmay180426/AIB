"""Unit tests for ML feature builders, metrics, and metadata.

These use small synthetic DataFrames and require no external dataset or trained
artifacts. Run: cd ml && python -m pytest -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common import metadata as meta  # noqa: E402
from src.data_processing import build_datasets as bd  # noqa: E402
from src.evaluation.metrics import regression_metrics  # noqa: E402
from src.forecasting.train_forecast import make_features  # noqa: E402


def _orders():
    return pd.DataFrame(
        {
            "order_id": ["o1", "o2", "o3"],
            "customer_id": ["c1", "c1", "c2"],
            "order_purchase_timestamp": ["2018-01-01 10:00:00", "2018-01-02 11:00:00", "2018-01-02 12:00:00"],
        }
    )


def _items():
    return pd.DataFrame(
        {
            "order_id": ["o1", "o1", "o2", "o3"],
            "order_item_id": [1, 2, 1, 1],
            "product_id": ["p1", "p2", "p1", "p2"],
            "price": [10.0, 5.0, 20.0, 8.0],
        }
    )


def _customers():
    return pd.DataFrame(
        {
            "customer_id": ["c1", "c2"],
            "customer_unique_id": ["u1", "u2"],
            "customer_state": ["SP", "RJ"],
        }
    )


def _products():
    return pd.DataFrame(
        {
            "product_id": ["p1", "p2"],
            "product_category_name": ["toys", "books"],
            "product_weight_g": [100.0, 200.0],
        }
    )


def test_regression_metrics_known_values():
    m = regression_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 5.0])
    assert m["mae"] == pytest.approx(0.6667, abs=1e-3)
    assert m["rmse"] == pytest.approx(1.1547, abs=1e-3)


def test_make_features_lags():
    series = pd.Series(range(1, 41), dtype=float)
    df = make_features(series)
    assert {"lag1", "lag7", "lag14", "lag30", "roll7", "roll30"} <= set(df.columns)
    assert df["lag1"].iloc[1] == 1.0
    assert df["lag7"].iloc[7] == 1.0


def test_build_daily_series_with_revenue():
    daily = bd.build_daily_series_with_revenue(_orders(), _items())
    assert daily["orders"].sum() == 3
    assert daily["revenue"].sum() == pytest.approx(43.0)
    assert {"date", "orders", "revenue", "avg_order_value"} <= set(daily.columns)


def test_build_orders_features_has_target():
    feat = bd.build_orders_features(_orders(), _items(), _customers(), _products())
    assert len(feat) == 3
    assert feat.loc[feat["order_id"] == "o1", "item_revenue"].iloc[0] == pytest.approx(15.0)
    assert "customer_state" in feat.columns


def test_build_customer_rfm():
    rfm = bd.build_customer_rfm(_orders(), _items(), _customers())
    row = rfm[rfm["customer_unique_id"] == "u1"].iloc[0]
    assert row["frequency"] == 2
    assert row["monetary"] == pytest.approx(35.0)
    assert row["recency_days"] >= 0


def test_build_product_features():
    prods = bd.build_product_features(_items(), _products())
    p1 = prods[prods["product_id"] == "p1"].iloc[0]
    assert p1["total_qty"] == 2
    assert p1["total_revenue"] == pytest.approx(30.0)


def test_write_metadata_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(meta, "models_dir", lambda: tmp_path)
    path = meta.write_metadata(
        "demo",
        target="y",
        features=["a", "b"],
        metrics={"mae": 1.0},
        status="available",
        algorithm="test",
        notes="unit test",
    )
    data = json.loads(path.read_text())
    assert data["name"] == "demo"
    assert data["status"] == "available"
    assert data["features_schema"] == ["a", "b"]
    assert len(data["dataset_fingerprint"]) == 16


def test_write_metadata_rejects_bad_status(tmp_path, monkeypatch):
    monkeypatch.setattr(meta, "models_dir", lambda: tmp_path)
    with pytest.raises(ValueError):
        meta.write_metadata(
            "bad", target="y", features=[], metrics={}, status="nope", algorithm="x"
        )
