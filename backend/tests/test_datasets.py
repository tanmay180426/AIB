"""Real ingestion/SQL/inference tests against isolated temporary databases."""
import csv
import io
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, inspect
from sqlalchemy.orm import sessionmaker

from app.database.deps import get_db
from app.main import app
from app.models.dataset import Dataset
from app.services import datasets as service

SALES = b'date,product,category,region,quantity,price,revenue\n2025-01-01,Book,Books,Pune,2,100,200\n2025-01-02,Pen,Office,Delhi,4,200,800\n'
STUDENT = b'student_id,name,department,marks,attendance,semester\n1,Ada,CS,80,90,5\n2,Ben,EE,60,70,5\n'
TRANSACTION = b'transaction_date,amount,category,location,status\n2025-01-01,100,Food,Mumbai,paid\n2025-01-02,300,Travel,Delhi,pending\n'
MINIMAL = b'date,value\n2025-01-01,10\n2025-01-02,30\n'
AMBIGUOUS = b'date,amount,age,phone,latitude,student_id\n01/02/2025,20,19,123456789,20.1,1\n02/03/2025,40,21,987654321,21.1,2\n'


@pytest.fixture
def isolated(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'datasets.db').as_posix()}", connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def upload(client, auth, content=SALES, filename='sales.csv', name='Sales'):
    r = client.post('/api/datasets/upload', data={'name': name}, files={'file': (filename, content)}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def scoped(auth, ds):
    return {**auth, 'X-Dataset-ID': ds['dataset_id']}


@pytest.mark.parametrize('source,rows,sumfield,total,average', [
    (SALES,2,'revenue',1000,500), (STUDENT,2,'marks',140,70),
    (TRANSACTION,2,'amount',400,200), (MINIMAL,2,'value',40,20), (AMBIGUOUS,2,'age',40,20),
])
def test_dataset_matrix(isolated, analyst_auth, source, rows, sumfield, total, average):
    client, _ = isolated
    ds = upload(client, analyst_auth, source)
    assert ds['status'] == 'READY', ds
    assert ds['row_count'] == rows
    assert all('storage' not in column for column in ds['schema']['columns'])
    response = client.get('/api/analytics/overview', headers=scoped(analyst_auth, ds))
    assert response.status_code == 200, response.text
    view = response.json()
    stat = next(s for s in view['numeric_statistics'] if s['field'] == sumfield)
    assert stat['sum'] == total
    assert stat['mean'] == average
    assert stat['median'] == average
    assert view['kpis']['row_count'] == rows
    answer = client.post('/api/insights/query', json={'question': f'What is the total {sumfield}?'}, headers=scoped(analyst_auth, ds)).json()
    assert f'{total:,.2f}' in answer['answer']
    assert answer['dataset_id'] == ds['dataset_id']
    if source is STUDENT:
        assert view['kpis']['total_revenue'] is None
        assert view['kpis']['unique_customers'] is None
        assert 'student_id' not in [s['field'] for s in view['numeric_statistics']]


def test_switching_and_chatbot_reconciliation(isolated, analyst_auth):
    client, _ = isolated
    a = upload(client, analyst_auth)
    b = upload(client, analyst_auth, SALES.replace(b'200\n', b'1000\n').replace(b'800\n', b'4000\n'), name='Sales B')
    c = upload(client, analyst_auth, STUDENT, name='Students')
    assert len(client.get('/api/datasets', headers=analyst_auth).json()['datasets']) == 3
    for ds, expected in [(a,1000),(b,5000),(a,1000)]:
        assert client.post(f"/api/datasets/{ds['dataset_id']}/select", headers=analyst_auth).status_code == 200
        assert client.get('/api/dashboard/kpis', headers=analyst_auth).json()['kpis']['total_revenue'] == expected
        answer = client.post('/api/insights/query', json={'question':'What is the total revenue?'}, headers=analyst_auth).json()['answer']
        assert f'{expected:,.2f}' in answer
        assert '6,000' not in answer
    unavailable = client.post('/api/insights/query', json={'question':'What is the delivery success rate?'}, headers=scoped(analyst_auth,c)).json()['answer']
    assert 'cannot calculate' in unavailable.lower()


def test_daily_order_measure_aggregation_and_business_metric_filtering(isolated, analyst_auth):
    client, _ = isolated
    daily = b'date,orders,revenue,generation_seed,data_origin\n2024-01-01,2,100,51,source_observed\n2024-01-01,3,150,51,source_observed\n2024-01-02,,200,51,source_observed\n'
    ds = upload(client, analyst_auth, daily, 'daily.csv', 'Daily business series')
    response = client.get('/api/analytics/overview', params={'grain':'day'}, headers=scoped(analyst_auth, ds))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['kpis']['total_orders'] is None  # an incomplete count is not reported as a partial total
    assert payload['kpis']['total_revenue'] == 450
    assert payload['order_series_quality']['available'] is True
    assert payload['order_series_quality']['order_count_field'] == 'orders'
    assert payload['order_series_quality']['incomplete_order_values'] == 1
    assert payload['time_series'][0]['orders'] == 5
    assert payload['time_series'][1]['orders'] is None
    labels = [card['label'] for card in payload['metric_cards']]
    assert 'Orders' not in labels  # incomplete overall coverage
    assert 'Revenue' in labels
    assert not any('generation_seed' in label.lower() for label in labels)
    assert not any('generation_seed' in stat['field'].lower() for stat in payload['numeric_statistics'])
    assert not any('profit' in label.lower() for label in labels)


def test_missing_order_and_revenue_fields_return_explicit_quality_not_zero(isolated, analyst_auth):
    client, _ = isolated
    content = b'date,amount,generation_seed\n2024-01-01,20,777\n2024-01-02,,777\n'
    ds = upload(client, analyst_auth, content, 'no-orders.csv', 'No business targets')
    response = client.get('/api/analytics/overview', params={'grain':'day'}, headers=scoped(analyst_auth, ds))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['kpis']['total_orders'] is None
    assert payload['kpis']['total_revenue'] is None
    assert payload['order_series_quality']['available'] is False
    assert 'No order ID or daily order-count field' in payload['order_series_quality']['reason']
    assert all('generation_seed' not in card['label'].lower() for card in payload['metric_cards'])
    assert all('generation_seed' not in stat['field'].lower() for stat in payload['numeric_statistics'])
    assert all('profit' not in card['label'].lower() for card in payload['metric_cards'])


def test_transaction_orders_use_distinct_order_id_when_no_daily_measure(isolated, analyst_auth):
    client, _ = isolated
    content = b'date,order_id,revenue\n2024-01-01,a,10\n2024-01-01,a,5\n2024-01-01,b,7\n'
    ds = upload(client, analyst_auth, content, 'items.csv', 'Order items')
    response = client.get('/api/analytics/overview', params={'grain':'day'}, headers=scoped(analyst_auth, ds))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['kpis']['total_orders'] == 2
    assert payload['time_series'][0]['orders'] == 2


def test_filters_reports_and_exports(isolated, analyst_auth):
    client, _ = isolated
    ds = upload(client, analyst_auth)
    auth = scoped(analyst_auth, ds)
    params = {'column_filters': json.dumps({'region':'Pune'})}
    r = client.get('/api/analytics/sales', params=params, headers=auth)
    assert r.json()['kpis']['total_revenue'] == 200
    assert r.json()['kpis']['row_count'] == 1
    assert r.json()['time_series'][0]['revenue'] == 200
    options = client.get('/api/analytics/filters', headers=auth).json()
    assert next(d for d in options['dynamic'] if d['field']=='region')['values'] == ['Delhi','Pune']
    for report in ['kpis','monthly_revenue','revenue_by_category','dataset_rows','numeric_statistics']:
        response = client.get('/api/reports/export', params={**params,'report':report}, headers=auth)
        assert response.status_code == 200, response.text
        assert response.headers['x-dataset-id'] == ds['dataset_id']
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert rows
        assert 'Delhi' not in response.text and '800' not in response.text
    response = client.post('/api/insights/query', params=params, json={'question':'total revenue'}, headers=auth)
    assert '200.00' in response.json()['answer']
    assert client.get('/api/analytics/overview', params={'date_from':'2025-01-02'}, headers=auth).json()['kpis']['total_revenue'] == 800
    assert client.get('/api/analytics/overview', params={'column_filters':json.dumps({'region':'Absent'})}, headers=auth).json()['kpis']['row_count'] == 0
    grouped = client.post('/api/insights/query',json={'question':'What is the total revenue by region?'},headers=auth).json()['answer']
    assert 'Pune: 200.00' in grouped and 'Delhi: 800.00' in grouped
    average = client.post('/api/insights/query',json={'question':'What is the average revenue?'},headers=auth).json()['answer']
    assert '500.00' in average and '1,000.00' not in average


@pytest.mark.parametrize('content,filename', [
    (b'', 'empty.csv'), (b'a,a\n1,2\n','duplicates.csv'), (b'a,b\n1\n','malformed.csv'),
    (b'1,2\n3,4\n','noheader.csv'), (b'[{"a": {"x":1}}]','nested.json'),
    (b'[{"a":1,"a":2}]','duplicates.json'), (b'{}','object.json'),
    (b'column\nInfinity\n','infinite.csv'), (b'\xff\xfe','encoding.csv'),
])
def test_failed_uploads_cannot_be_selected(isolated, analyst_auth, content, filename):
    client, _ = isolated
    ds = upload(client, analyst_auth, content, filename)
    assert ds['status'] == 'FAILED', ds
    assert ds['error'] and 'Traceback' not in ds['error']
    assert client.post(f"/api/datasets/{ds['dataset_id']}/select", headers=analyst_auth).status_code == 409
    assert client.get('/api/analytics/overview', headers=scoped(analyst_auth,ds)).status_code == 409


def test_upload_size_and_type_limits(isolated, analyst_auth, monkeypatch):
    client, _ = isolated
    assert client.post('/api/datasets/upload', data={'name':'bad'}, files={'file':('bad.exe', b'abc')}, headers=analyst_auth).status_code == 422
    monkeypatch.setattr(service, 'MAX_BYTES', 20)
    assert client.post('/api/datasets/upload', data={'name':'large'}, files={'file':('large.csv', SALES)}, headers=analyst_auth).status_code == 413


def test_row_column_and_memory_limits(isolated, analyst_auth, monkeypatch):
    client, _ = isolated
    for limit, value in [('MAX_ROWS',1), ('MAX_COLUMNS',2), ('MAX_CELLS',3)]:
        with monkeypatch.context() as context:
            context.setattr(service,limit,value)
            ds = upload(client,analyst_auth)
            assert ds['status'] == 'FAILED'


def test_currency_evidence_and_account_semantics(isolated, analyst_auth):
    client, _ = isolated
    ds = upload(client,analyst_auth,b'date,user_id,revenue_brl\n2025-01-01,u1,100\n2025-01-02,u2,200\n')
    assert ds['semantics']['currency_code'] == 'BRL'
    assert ds['semantics']['fields']['revenue'] == 'revenue_brl'
    view = client.get('/api/analytics/customers',headers=scoped(analyst_auth,ds)).json()
    assert view['status'] == 'available'
    assert next(c['value'] for c in view['metric_cards'] if c['label']=='Users / accounts') == 2


def test_conflicting_and_unsupported_request_filters(isolated, analyst_auth):
    client, _ = isolated
    a = upload(client,analyst_auth)
    b = upload(client,analyst_auth,STUDENT)
    assert client.get('/api/analytics/overview',params={'dataset_id':b['dataset_id']},headers=scoped(analyst_auth,a)).status_code == 422
    for params in [{'column_filters':'null'}, {'column_filters':'{"revenue":NaN}'}, {'grain':'century'}, {'invalid_filter':'x'}]:
        assert client.get('/api/analytics/overview',params=params,headers=scoped(analyst_auth,a)).status_code == 422
    assert client.get('/api/ml/forecast?grain=month',headers=scoped(analyst_auth,a)).status_code == 422


def test_missing_reference_requires_explicit_selection(isolated, analyst_auth):
    client, _ = isolated
    assert client.get('/api/dashboard/kpis',headers=analyst_auth).status_code == 409
    upload(client,analyst_auth)
    assert client.get('/api/dashboard/kpis',headers=analyst_auth).status_code == 409


@pytest.mark.parametrize('endpoint', ['/api/dashboard/kpis','/api/analytics/overview','/api/analytics/filters','/api/ml/status','/api/ml/forecast','/api/reports/export'])
def test_dataset_authorization_at_all_read_boundaries(isolated, analyst_auth, auth, endpoint):
    client, _ = isolated
    ds = upload(client, analyst_auth)
    assert client.get(endpoint, headers=scoped(auth,ds)).status_code == 403
    assert client.get(endpoint, headers={'X-Dataset-ID':ds['dataset_id']}).status_code == 401
    assert client.get(endpoint, headers=scoped(analyst_auth,ds)).status_code == 200


def test_private_dataset_cannot_be_accessed_by_other_user_or_admin(isolated, analyst_auth, auth):
    client, _ = isolated
    ds = upload(client, analyst_auth)
    ident = ds['dataset_id']
    assert ds['owner'] == 'analyst'
    assert client.get('/api/datasets', headers=auth).json()['datasets'] == []
    for method, url in [('get',f'/api/datasets/{ident}'),('post',f'/api/datasets/{ident}/select'),('delete',f'/api/datasets/{ident}')]:
        assert getattr(client,method)(url, headers=auth).status_code == 403
    assert client.post('/api/insights/query', json={'question':'total revenue'},headers=scoped(auth,ds)).status_code == 403
    assert client.patch(f'/api/datasets/{ident}/schema',json={'fields':{}},headers=auth).status_code == 403


def test_deleted_dataset_never_falls_back(isolated, analyst_auth):
    client, _ = isolated
    a = upload(client, analyst_auth)
    upload(client, analyst_auth, STUDENT)
    ident = a['dataset_id']
    client.post(f'/api/datasets/{ident}/select',headers=analyst_auth)
    assert client.delete(f'/api/datasets/{ident}', headers=analyst_auth).status_code == 204
    assert client.get('/api/dashboard/kpis',headers=analyst_auth).status_code == 404


def test_ambiguous_dates_require_confirmation_and_do_not_invent_revenue(isolated, analyst_auth):
    client, _ = isolated
    ds = upload(client,analyst_auth,AMBIGUOUS)
    assert 'date' not in ds['semantics']['fields']
    assert 'revenue' not in ds['semantics']['fields']
    assert ds['quality']['warnings']
    assert client.get('/api/analytics/overview',params={'date_from':'2025-01-01'},headers=scoped(analyst_auth,ds)).status_code == 422
    r = client.patch(f"/api/datasets/{ds['dataset_id']}/schema", json={'fields':{'revenue':'amount'},'date_order':'dayfirst'}, headers=analyst_auth)
    assert r.status_code == 200, r.text
    assert r.json()['semantics']['fields']['date'] == 'date'
    view = client.get('/api/analytics/overview?date_to=2025-02-01',headers=scoped(analyst_auth,ds)).json()
    assert view['kpis']['row_count'] == 1
    assert view['kpis']['total_revenue'] == 20
    assert client.patch(f"/api/datasets/{ds['dataset_id']}/schema",json={'fields':{'revenue':'phone'}}, headers=analyst_auth).status_code == 422


def test_sql_and_csv_formula_safety(isolated, analyst_auth):
    client, factory = isolated
    ds = upload(client,analyst_auth,b'date,region,revenue\n2025-01-01,=1+1,100\n')
    auth = scoped(analyst_auth,ds)
    assert client.get('/api/analytics/overview',params={'column_filters':json.dumps({'region':"' OR 1=1 --"})},headers=auth).json()['kpis']['row_count'] == 0
    assert client.get('/api/analytics/overview',params={'column_filters':json.dumps({'c0;DROP TABLE app_dataset':'x'})},headers=auth).status_code == 422
    text = client.get('/api/reports/export?report=dataset_rows',headers=auth).text
    assert "'=1+1" in text
    from app.api.routes.reports import _to_csv
    assert "'=header" in _to_csv([{'=header': '=value'}])
    with factory() as db:
        assert db.get(Dataset,ds['dataset_id']) is not None


@pytest.mark.parametrize('filename', ['table.json', 'table.xlsx'])
def test_supported_non_csv_formats(isolated, analyst_auth, filename):
    client, _ = isolated
    if filename.endswith('json'):
        raw = b'[{"date":"2025-01-01","revenue":100},{"date":"2025-01-02","revenue":200}]'
    else:
        import openpyxl
        workbook = openpyxl.Workbook(); worksheet = workbook.active
        worksheet.append(['date','revenue']); worksheet.append(['2025-01-01',100]); worksheet.append(['2025-01-02',200])
        buffer = io.BytesIO(); workbook.save(buffer); raw = buffer.getvalue()
    ds = upload(client,analyst_auth,raw,filename)
    assert ds['status'] == 'READY', ds
    assert client.get('/api/dashboard/kpis',headers=scoped(analyst_auth,ds)).json()['kpis']['total_revenue'] == 300


def test_incompatible_models_do_not_execute(isolated, analyst_auth, monkeypatch):
    client, _ = isolated
    ds = upload(client,analyst_auth,STUDENT)
    def forbidden(*args, **kwargs):
        pytest.fail('An incompatible model was executed')
    from app.services import ml
    monkeypatch.setattr(ml,'_load_artifact',forbidden)
    for endpoint in ['/api/ml/forecast?target=revenue','/api/ml/product-segmentation','/api/ml/anomalies','/api/ml/segments/customers']:
        body = client.get(endpoint,headers=scoped(analyst_auth,ds)).json()
        assert body['status'] == 'not_applicable'
        assert body['compatibility']['compatible'] is False
        assert body['reason']
        assert 'forecast' not in body and 'segments' not in body
    body = client.post('/api/ml/predict/sales', headers=scoped(analyst_auth, ds), json={
        'purchase_month': 1, 'purchase_weekday': 2, 'purchase_hour': 12, 'n_items': 2}).json()
    assert body['status'] == 'not_applicable'
    assert 'predicted_item_revenue' not in body


def test_existing_models_execute_on_compatible_uploaded_data(isolated, analyst_auth):
    client, _ = isolated
    header = 'date,order_id,customer_id,product,category,region,quantity,price,revenue,weight_g\n'
    rows = [f'{date(2025,1,1)+timedelta(days=i)},o{i},c{i%5},p{i%4},Books,SP,2,100,200,100' for i in range(40)]
    ds = upload(client,analyst_auth,(header+'\n'.join(rows)).encode())
    r = client.patch(f"/api/datasets/{ds['dataset_id']}/schema",json={'fields':{},'currency_code':'BRL','domain':'commerce'},headers=analyst_auth)
    assert r.status_code == 200
    auth = scoped(analyst_auth,ds)
    for path in ['/api/ml/forecast?target=revenue&periods=7','/api/ml/forecast?target=orders&periods=7','/api/ml/product-segmentation','/api/ml/anomalies','/api/ml/segments/customers']:
        response = client.get(path,headers=auth)
        assert response.status_code == 200,response.text
        body = response.json()
        assert body['status'] == 'available',body
        assert body['compatibility']['compatible'] is True
        assert body['dataset_id'] == ds['dataset_id']
        if 'forecast' in path:
            assert len(body['forecast']) == 7
            target = 'orders' if 'target=orders' in path else 'revenue'
            assert sum(p[target] for p in body['history_tail']) == (30 if target == 'orders' else 6000)
        if 'product-segmentation' in path:
            assert sum(s['revenue'] for s in body['segments']) == 8000
            assert sum(s['products'] for s in body['segments']) == 4
    prediction = client.post('/api/ml/predict/sales', headers=auth, json={
        'purchase_month': 1, 'purchase_weekday': 2, 'purchase_hour': 12,
        'n_items': 2, 'customer_state': 'SP', 'product_category_name': 'Books'})
    assert prediction.status_code == 200, prediction.text
    assert prediction.json()['status'] == 'available'
    assert prediction.json()['currency'] == 'BRL'
    assert prediction.json()['dataset_id'] == ds['dataset_id']
