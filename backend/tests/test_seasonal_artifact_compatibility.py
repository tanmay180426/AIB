"""Focused offline checks for frozen peak-sensitive experiment artifacts."""
import importlib.util
import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import datasets as dataset_service
from app.services.daily_forecast_series import load_daily_forecast_series


REPO = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO / "ml/experiments/olist_seasonal_2024/peak_sensitive/seasonal_artifact_validation.py"
SPEC = importlib.util.spec_from_file_location("seasonal_artifact_validation", HARNESS_PATH)
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)
DATA = REPO / "ml/experiments/olist_seasonal_2024/unified/unified_daily_series.csv"


@pytest.fixture(scope="module")
def adapter_series(tmp_path_factory):
    """Resolve and load the canonical experiment CSV via an isolated test DB."""
    db_path = tmp_path_factory.mktemp("seasonal-adapter") / "isolated.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    factory = sessionmaker(bind=engine)
    try:
        with factory() as db:
            dataset = dataset_service.ingest(
                db, {"username": "offline-validator"}, "seasonal validation fixture",
                DATA.read_bytes(), ".csv",
            )
            assert dataset.status == "READY", dataset.error
            dataset_service.resolve(db, {"username": "offline-validator"}, dataset.id)
            yield {target: load_daily_forecast_series(db, dataset, target)
                   for target in ("orders", "revenue")}
    finally:
        engine.dispose()


@pytest.mark.parametrize(("target", "horizon"), list(HARNESS.ARTIFACTS_BY_PAIR))
def test_frozen_artifact_hash_schema_adapter_inference_and_repeatability(adapter_series, target, horizon):
    filename, candidate = HARNESS.ARTIFACTS_BY_PAIR[(target, horizon)]
    path = HARNESS.ARTIFACTS / filename
    bundle, metadata = HARNESS.load_artifact(path, target, horizon)
    assert bundle["candidate"] == metadata["candidate"] == candidate
    assert "data_origin" not in metadata["features"]
    assert "source_data_flag" not in metadata["features"]

    first = HARNESS.forecast(adapter_series[target], path, target, horizon)
    second = HARNESS.forecast(adapter_series[target], path, target, horizon)
    expected_start = date(2025, 1, 1)
    assert len(first) == horizon
    assert first.date.iloc[0].date() == expected_start
    assert first.date.diff().dropna().eq(__import__("pandas").Timedelta(days=1)).all()
    assert np.isfinite(first.prediction.to_numpy()).all()
    assert (first.prediction >= 0).all()
    assert first.prediction.nunique() > 1
    np.testing.assert_array_equal(first.prediction.to_numpy(), second.prediction.to_numpy())


def test_missing_artifact_and_hash_mismatch_are_rejected(tmp_path):
    missing = tmp_path / "absent.joblib"
    with pytest.raises(FileNotFoundError, match="both required"):
        HARNESS.load_artifact(missing, "orders", 90)

    source = HARNESS.ARTIFACTS / HARNESS.ARTIFACTS_BY_PAIR[("orders", 90)][0]
    copied = tmp_path / source.name
    shutil.copyfile(source, copied)
    shutil.copyfile(source.with_suffix(".json"), copied.with_suffix(".json"))
    copied.write_bytes(copied.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="SHA-256"):
        HARNESS.load_artifact(copied, "orders", 90)


def test_feature_schema_and_identity_mismatch_are_rejected(tmp_path):
    source = HARNESS.ARTIFACTS / HARNESS.ARTIFACTS_BY_PAIR[("revenue", 30)][0]
    copied = tmp_path / source.name
    shutil.copyfile(source, copied)
    metadata_path = source.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["features"] = metadata["features"][::-1]
    copied.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="feature schema"):
        HARNESS.load_artifact(copied, "revenue", 30)

    with pytest.raises(ValueError, match="target/horizon mapping"):
        HARNESS.load_artifact(source, "revenue", 90)


def test_invalid_history_wrong_horizon_and_nonfinite_predictions_are_rejected(adapter_series):
    class ShortSeries:
        target = "orders"

        def to_model_frame(self):
            import pandas as pd
            return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=100), "orders": np.ones(100)})

    path = HARNESS.ARTIFACTS / HARNESS.ARTIFACTS_BY_PAIR[("orders", 30)][0]
    with pytest.raises(ValueError, match="at least 365"):
        HARNESS.forecast(ShortSeries(), path, "orders", 30)
    recursive_path = HARNESS.ARTIFACTS / HARNESS.ARTIFACTS_BY_PAIR[("orders", 90)][0]
    with pytest.raises(ValueError, match="target/horizon mapping"):
        HARNESS.forecast(adapter_series["orders"], recursive_path, "orders", 30)
    with pytest.raises(ValueError, match="non-finite"):
        HARNESS.validate_predictions([np.nan] * 30, 30, nonnegative=True)
