"""Focused, transport-independent checks for dataset API readiness."""
from pathlib import Path
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.models.dataset import Dataset
from app.analytics.filters import Filters
from app.api.routes.ml import ml_forecast
from app.services import datasets as service
from app.api.routes import datasets as dataset_routes


@pytest.fixture
def isolated_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'dataset-readiness.db').as_posix()}")
    factory = sessionmaker(bind=engine)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def test_registry_initialization_is_repeatable_and_non_destructive(isolated_db):
    engine, factory = isolated_db
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE preserved_marker (id INTEGER PRIMARY KEY, value TEXT)'))
        conn.execute(text("INSERT INTO preserved_marker(value) VALUES ('keep')"))
    assert 'app_dataset' not in inspect(engine).get_table_names()

    with factory() as db:
        user = {'username': 'analyst'}
        for _ in range(2):
            result = dataset_routes.list_datasets(db, user)
            assert result == {'datasets': [], 'active_dataset_id': None}
        names = set(inspect(engine).get_table_names())
        assert {'app_dataset', 'app_dataset_selection', 'app_dataset_bundle_table', 'preserved_marker'} <= names
        assert db.execute(text('SELECT COUNT(*) FROM app_dataset')).scalar_one() == 0
        assert db.execute(text('SELECT COUNT(*) FROM app_dataset_selection')).scalar_one() == 0
        assert db.execute(text('SELECT value FROM preserved_marker')).scalar_one() == 'keep'


def test_unified_daily_ingestion_and_api_preview_keep_full_provenance(isolated_db):
    _, factory = isolated_db
    source = (Path(__file__).resolve().parents[2] /
              'ml/experiments/olist_seasonal_2024/unified/unified_daily_series.csv')
    if not source.is_file():
        pytest.skip('Unified experiment CSV is unavailable in this checkout.')

    with factory() as db:
        user = {'username': 'analyst'}
        ds = service.ingest(db, user, 'Unified Olist daily', source.read_bytes(), '.csv')
        assert ds.status == 'READY', ds.error
        assert ds.row_count == 3041
        columns = {column['name']: column for column in ds.profile['columns']}
        assert {'date', 'data_origin', 'orders_unified', 'revenue_unified', 'profit_unified'} <= columns.keys()
        assert ds.quality['duplicate_rows'] == 0

        table = service.storage_table(ds, db)
        selected = [table.c[columns[name]['storage']] for name in
                    ('date', 'data_origin', 'orders_unified', 'revenue_unified', 'profit_unified')]
        rows = db.execute(select(*selected).order_by(table.c.row_id)).all()
        assert len(rows) == 3041
        assert rows[0][0] == '2016-09-04T00:00:00+00:00'
        assert rows[-1][0] == '2024-12-31T00:00:00+00:00'
        assert rows[0][1] == 'source_observed'
        assert rows[-1][1] == 'synthetic_extension'
        assert sum(row[1] == 'source_observed' for row in rows) == 2923
        assert sum(row[1] == 'synthetic_extension' for row in rows) == 118
        calendar = [date.fromisoformat(row[0][:10]) for row in rows]
        assert all((current - previous).days == 1 for previous, current in zip(calendar, calendar[1:]))
        assert rows[0][2:] == (1.0, 72.89, -34.51)
        assert all(value is not None for value in rows[-1][2:])

        listing = dataset_routes.list_datasets(db, user)
        assert len(listing['datasets']) == 1
        preview = dataset_routes.preview(ds.id, db, user)
        assert preview['rows'][0]['date'] == rows[0][0]
        assert preview['rows'][0]['data_origin'] == rows[0][1]
        assert {'orders_unified', 'revenue_unified', 'profit_unified'} <= set(preview['columns'])
        assert db.get(Dataset, ds.id).row_count == 3041

        # Exercise the forecast route handler separately from ASGI transport:
        # this aggregate CSV is not an order-level schema and legacy binaries
        # are absent, so it must return unavailable or the documented 503.
        service.resolve(db, user, ds.id)
        from fastapi import HTTPException
        for target in ('orders', 'revenue'):
            try:
                forecast = ml_forecast(periods=7, target=target, db=db, f=Filters(), user=user)
            except HTTPException as exc:
                assert exc.status_code == 503
                assert 'artifact is unavailable' in str(exc.detail).lower()
            else:
                assert forecast['status'] == 'not_applicable'
                assert forecast['forecast_series'] == []


def test_invalid_daily_csv_is_rejected_by_existing_parser():
    with pytest.raises(ValueError, match='same number of fields'):
        service.parse_source(b'date,revenue\n2024-01-01,10\n2024-01-02\n', '.csv')
