"""Hand-calculated audit cases; storage is synthetic and disposable."""
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.analytics import metrics
from app.analytics.filters import Filters
from app.services import ml
from tests.database_fixture import seed_synthetic_warehouse


@pytest.fixture
def warehouse(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'forensic.db'}")
    seed_synthetic_warehouse(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_delivery_comparisons_count_each_order_once(warehouse):
    warehouse.execute(text("UPDATE fact_orders SET delivery_days=10, is_late=1 WHERE order_id='test-0'"))
    for item in range(2, 102):
        warehouse.execute(text("INSERT INTO fact_order_items(order_id,order_item_id,product_id,seller_id,customer_unique_id,purchase_date,price,freight_value,product_category_name_en) VALUES('test-0',:item,'test-product','test-seller','test-customer','2025-01-01',1,0,'books')"), {'item': item})
    result = metrics.delivery_metrics(warehouse, Filters())
    for group in ('by_seller', 'by_category'):
        row = result[group][0]
        assert row['orders'] == 45
        assert row['late_orders'] == 1
        assert row['orders_with_estimate'] == 45
        assert row['avg_delivery_days'] == pytest.approx(98 / 45, abs=.005)
        assert row['on_time_rate'] == round(100 * 44 / 45, 1)


def test_customer_comparison_is_a_partition_not_overlapping_counts(warehouse):
    result = metrics.customers(warehouse, Filters())
    assert result['kpis']['unique_customers'] == 1
    assert result['kpis']['repeat_customers'] == 1
    assert sum(row['customers'] for row in result['new_vs_repeat']) == 1
    assert result['new_vs_repeat'][0] == {'segment': 'Single-purchase customers', 'customers': 0}


def test_missing_customer_identity_is_not_a_repeat_person(warehouse):
    warehouse.execute(text('UPDATE fact_orders SET customer_unique_id=NULL'))
    result = metrics.kpis(warehouse, Filters())
    assert result['unique_customers'] == 0
    assert result['repeat_customers'] == 0


def test_invalid_delivery_durations_are_excluded(warehouse):
    warehouse.execute(text("UPDATE fact_orders SET delivery_days=-1 WHERE order_id='test-0'"))
    result = metrics.delivery_metrics(warehouse, Filters())
    assert result['kpis']['orders_in_scope'] == 44
    assert result['kpis']['avg_delivery_days'] == 2


def test_product_inference_never_invents_an_unsaved_imputer():
    class Scaler:
        def transform(self, frame):
            return frame.to_numpy()
    class Model:
        def predict(self, frame):
            return np.zeros(len(frame), dtype=int)
    bundle = {'model': Model(), 'scaler': Scaler(), 'features': ['qty_log', 'revenue_log', 'avg_price', 'product_weight_g']}
    rows = pd.DataFrame([{'product': 'p1', 'category': 'books', 'total_qty': 1, 'total_revenue': 10, 'avg_price': 10, 'product_weight_g': None}])
    with pytest.raises(ValueError, match='imputation'):
        ml._product_predictions(rows, bundle)
