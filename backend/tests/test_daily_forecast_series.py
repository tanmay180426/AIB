"""Focused tests for the non-serving daily aggregate contract."""
from datetime import date, timedelta
import hashlib
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analytics.filters import Filters
from app.analytics.tabular import TabularSource
from app.services import datasets as dataset_service
from app.services.daily_forecast_series import (
    load_daily_forecast_series,
    validate_daily_frame,
)


@pytest.fixture
def isolated_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'daily-series.db').as_posix()}")
    factory = sessionmaker(bind=engine)
    try:
        with factory() as db:
            yield db
    finally:
        engine.dispose()


def contract_frame():
    return pd.DataFrame({
        'date': ['2024-09-03', '2024-09-04', '2024-09-05'],
        'data_origin': ['source_observed', 'source_observed', 'synthetic_extension'],
        'source_data_flag': [1, 1, 0],
        'orders_unified': [2, 0, 3],
        'revenue_unified': [10.0, 0.0, 25.5],
        'profit_unified': [-2.0, -1.0, 4.5],
    })


def test_valid_series_keeps_provenance_outside_model_frame_and_has_no_order_ids():
    frame = contract_frame()
    assert 'order_id' not in frame.columns
    series = validate_daily_frame(frame, 'orders')
    assert series.dates == (date(2024, 9, 3), date(2024, 9, 4), date(2024, 9, 5))
    assert series.values == (2.0, 0.0, 3.0)
    assert series.provenance_counts == {'source_observed': 2, 'synthetic_extension': 1}
    assert series.source_provenance_independently_certified is False
    assert any('not independently certified' in warning for warning in series.warnings)
    model_frame = series.to_model_frame()
    assert list(model_frame.columns) == ['date', 'orders']
    assert 'data_origin' not in model_frame.columns


@pytest.mark.parametrize(('mutation', 'message'), [
    (lambda f: f.assign(date=['2024-09-04', '2024-09-03', '2024-09-05']), 'strictly chronological'),
    (lambda f: f.assign(date=['2024-09-03', '2024-09-03', '2024-09-05']), 'Duplicate daily date'),
    (lambda f: f.assign(date=['2024-09-03', '2024-09-05', '2024-09-06']), 'Missing daily date'),
    (lambda f: f.assign(date=['2024-09-03', 'not-a-date', '2024-09-05']), 'Invalid ISO calendar date'),
    (lambda f: f.drop(columns=['orders_unified']), 'missing required columns'),
    (lambda f: f.assign(orders_unified=['2', 'bad', '3']), 'must be numeric'),
    (lambda f: f.assign(orders_unified=[2.5, 0, 3]), 'whole daily counts'),
    (lambda f: f.assign(orders_unified=[2, -1, 3]), 'cannot be negative'),
    (lambda f: f.assign(source_data_flag=[1, 1, 1]), 'conflicts with data_origin'),
])
def test_invalid_series_fails_explicitly(mutation, message):
    with pytest.raises(ValueError, match=message):
        validate_daily_frame(mutation(contract_frame()), 'orders')


def test_required_fields_and_numeric_target_are_checked():
    with pytest.raises(ValueError, match='missing required columns.*profit_unified'):
        validate_daily_frame(contract_frame().drop(columns='profit_unified'), 'profit')
    with pytest.raises(ValueError, match='must be finite'):
        validate_daily_frame(contract_frame().assign(revenue_unified=[10, float('inf'), 25]), 'revenue')


def test_currency_and_profit_uncertainty_are_preserved():
    revenue = validate_daily_frame(contract_frame(), 'revenue')
    assert revenue.unit == 'source_currency_unverified'
    assert revenue.currency_code is None
    assert any('currency is unverified' in warning for warning in revenue.warnings)
    with pytest.raises(ValueError, match='currency is unverified'):
        validate_daily_frame(contract_frame(), 'revenue', require_verified_currency=True)

    profit = validate_daily_frame(contract_frame(), 'profit')
    assert profit.values[0] == -2.0
    assert profit.unit == 'unknown_units'
    assert profit.definition_status == 'provisional_formula_and_units_unverified'
    assert any('formula, units, and currency' in warning for warning in profit.warnings)
    with pytest.raises(ValueError, match='Profit currency and units are unverified'):
        validate_daily_frame(contract_frame(), 'profit', require_verified_currency=True)


def test_uploaded_unified_dataset_loads_without_models_and_does_not_mutate_source(isolated_db):
    source = (Path(__file__).resolve().parents[2] /
              'ml/experiments/olist_seasonal_2024/unified/unified_daily_series.csv')
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with isolated_db as db:
        ds = dataset_service.ingest(db, {'username': 'analyst'}, 'unified series', source.read_bytes(), '.csv')
        assert ds.status == 'READY', ds.error
        assert 'order_id' not in {column['name'] for column in ds.profile['columns']}
        dataset_service.resolve(db, {'username': 'analyst'}, ds.id)

        with patch('app.services.ml._load_artifact', side_effect=AssertionError('model loading is out of scope')) as loader:
            series = load_daily_forecast_series(db, ds, 'orders')
            revenue = load_daily_forecast_series(db, ds, 'revenue')
            profit = load_daily_forecast_series(db, ds, 'profit')
            loader.assert_not_called()

        assert len(series.values) == 3041
        assert series.dates[0] == date(2016, 9, 4)
        assert series.dates[-1] == date(2024, 12, 31)
        assert series.provenance_counts == {'source_observed': 2923, 'synthetic_extension': 118}
        assert revenue.currency_code is None and revenue.unit == 'source_currency_unverified'
        assert profit.values[0] < 0 and profit.unit == 'unknown_units'
        assert list(series.to_model_frame().columns) == ['date', 'orders']

    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_existing_order_level_adapter_still_counts_order_ids(isolated_db):
    raw = b'date,order_id,revenue\n2025-01-01,o1,10\n2025-01-01,o2,20\n2025-01-02,o3,30\n'
    with isolated_db as db:
        ds = dataset_service.ingest(db, {'username': 'analyst'}, 'order-level', raw, '.csv')
        assert ds.status == 'READY', ds.error
        db.info['dataset'] = ds
        rows = TabularSource(db, Filters()).time_series('day')
    assert rows == [
        {'period': '2025-01-01', 'rows': 2, 'revenue': 30.0, 'orders': 2},
        {'period': '2025-01-02', 'rows': 1, 'revenue': 30.0, 'orders': 1},
    ]
