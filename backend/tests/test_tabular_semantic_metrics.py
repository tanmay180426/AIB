"""Focused SQL aggregation checks that do not require the API TestClient."""
from types import SimpleNamespace
import uuid

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session
import pandas as pd

from app.analytics.tabular import TabularSource
from app.services.datasets import storage_table
from app.services.datasets import profile_frame


def _source(rows):
    dataset_id = str(uuid.uuid4())
    columns = [
        {"name": "date", "storage": "c0", "dtype": "datetime", "role": "date"},
        {"name": "orders", "storage": "c1", "dtype": "numeric", "role": "order_count"},
        {"name": "generation_seed", "storage": "c2", "dtype": "numeric", "role": "technical_metadata"},
        {"name": "data_source", "storage": "c3", "dtype": "text", "role": "technical_metadata"},
    ]
    dataset = SimpleNamespace(id=dataset_id, profile={"columns": columns}, semantics={"fields": {"date": "date", "order_count": "orders"}},
                              source_type="tabular", adapter="tabular", name="fixture", capabilities={}, quality={})
    engine = create_engine("sqlite://")
    table = storage_table(dataset, columns=columns)
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(insert(table), rows)
    session = Session(engine)
    session.info["dataset"] = dataset
    return engine, session, TabularSource(session)


def test_daily_order_count_is_summed_and_generation_metadata_is_not_a_kpi():
    engine, session, source = _source([
        {"c0": "2024-01-01", "c1": 3, "c2": 17, "c3": "generated"},
        {"c0": "2024-01-02", "c1": 5, "c2": 17, "c3": "generated"},
    ])
    try:
        assert source.kpis()["total_orders"] == 8
        assert all("generation_seed" not in row["field"] and "data_source" not in row["field"]
                   for row in source.view("dashboard")["numeric_statistics"])
        assert source.provenance()["origins"] == [{"value": "generated", "rows": 2}]
    finally:
        session.close()
        engine.dispose()


def test_daily_orders_column_is_inferred_as_an_order_count_measure():
    _, columns, _ = profile_frame(pd.DataFrame({"date": ["2024-01-01"], "orders": [4]}))
    orders = next(column for column in columns if column["name"] == "orders")
    assert orders["role"] == "order_count"
    assert orders["dtype"] == "numeric"


def test_missing_daily_order_count_remains_unknown_in_period_aggregate():
    engine, session, source = _source([
        {"c0": "2024-01-01", "c1": 3, "c2": 17, "c3": "generated"},
        {"c0": "2024-01-02", "c1": None, "c2": 17, "c3": "generated"},
    ])
    try:
        assert source.kpis()["total_orders"] is None
        daily = source.time_series("day")
        assert [point["orders"] for point in daily] == [3, None]
    finally:
        session.close()
        engine.dispose()
