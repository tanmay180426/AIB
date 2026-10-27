"""Reconcile the registered reference with source SQL, reports and AI."""
import csv
import io

import pytest
from sqlalchemy import text
from app.database.session import SessionLocal
from app.services.datasets import REFERENCE_ID


def test_registered_reference_keeps_verified_olist_metrics(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip('Olist reference warehouse is not loaded')
    headers = {**auth, 'X-Dataset-ID': REFERENCE_ID}
    k = client.get('/api/dashboard/kpis', headers=headers).json()['kpis']
    with SessionLocal() as db:
        source_orders = db.scalar(text('SELECT COUNT(*) FROM fact_orders'))
        source_revenue = db.scalar(text('SELECT SUM(price) FROM fact_order_items'))
    assert k['total_orders'] == source_orders == 99441
    assert k['total_revenue'] == round(source_revenue, 2) == 13591643.70
    assert k['unique_customers'] == 96096
    assert k['products_sold'] == 32951
    assert k['active_sellers'] == 3095
    assert k['items_sold'] == 112650
    metadata = client.get(f'/api/datasets/{REFERENCE_ID}', headers=auth).json()
    assert metadata['read_only'] is True
    assert metadata['semantics']['currency_code'] == 'BRL'
    assert metadata['semantics']['fields']['revenue'] == 'item_revenue'
    assert metadata['column_count'] == len(metadata['schema']['columns'])


def test_reference_reports_and_chatbot_respect_shared_filters(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip('Olist reference warehouse is not loaded')
    headers = {**auth, 'X-Dataset-ID': REFERENCE_ID}
    params = {'date_from':'2018-01-01','date_to':'2018-01-31','category':'health_beauty'}
    k = client.get('/api/dashboard/kpis', params=params, headers=headers).json()['kpis']
    for report, field in [('monthly_revenue','revenue'),('revenue_by_category','revenue')]:
        response = client.get('/api/reports/export', params={**params, 'report':report}, headers=headers)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert sum(float(r[field]) for r in rows) == pytest.approx(k['total_revenue'], abs=.01)
    answer = client.post('/api/insights/query', params=params, json={'question':'What is the total revenue?'}, headers=headers).json()
    assert f"{k['total_revenue']:,.2f}" in answer['answer']


def test_reference_category_breakdowns_and_segments_reconcile(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip('Explicit Olist reference snapshot not supplied')
    from app.analytics import metrics
    from app.analytics.filters import Filters
    from app.models.dataset import Dataset
    from app.services import ml
    headers = {**auth, 'X-Dataset-ID': REFERENCE_ID}
    assert client.get('/api/dashboard/kpis', headers=headers).status_code == 200
    with SessionLocal() as db:
        db.info['dataset'] = db.get(Dataset, REFERENCE_ID)
        filters = Filters(category='health_beauty')
        expected = round(db.scalar(text("SELECT SUM(price) FROM fact_order_items WHERE product_category_name_en='health_beauty'")), 2)
        assert expected == 1258681.34
        assert metrics.kpis(db, filters)['total_revenue'] == expected
        for function in [metrics.payment_types, metrics.payment_installments, metrics.customer_spend_distribution,
                         metrics.customers_by_state,
                         lambda session, f: metrics.top_customer_states(session, f, limit=100),
                         lambda session, f: metrics.top_customers(session, f, limit=100000)]:
            assert sum(row['revenue'] for row in function(db, filters)) == pytest.approx(expected, abs=.01)
        assert sum(row['monetary'] for row in ml.customer_segments(db, filters)['segments']) == pytest.approx(expected, abs=.01)
