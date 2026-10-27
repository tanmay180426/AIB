"""Hand-calculated fan-out fixtures, resource contracts and real model execution."""
import io
import time
import zipfile
from datetime import date,timedelta
import pytest
from sqlalchemy import select,inspect
from tests.test_datasets import isolated  # noqa: F401
from app.models.dataset import Dataset
from app.services import bundle_jobs,dataset_bundles as bundles,datasets,ml


def fixture(days=2):
    orders=['order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date,order_estimated_delivery_date']
    items=['order_id,order_item_id,product_id,seller_id,price,freight_value']
    payments=['order_id,payment_sequential,payment_type,payment_value']
    reviews=['review_id,order_id,review_score']
    for i in range(days):
        d=date(2025,1,1)+timedelta(days=i)
        orders.append(f'o{i},c{i%2},delivered,{d},{d+timedelta(days=3+2*(i%2))},{d+timedelta(days=7)}')
        items.append(f'o{i},1,p1,s1,{30 if i==0 else 90},10')
        payments.append(f'o{i},1,credit_card,{40 if i==0 else 90}')
        reviews.append(f'r{i},o{i},{5 if i==0 else 1}')
    # Two item/payment/review rows for the first order expose join fan-out.
    items.append('o0,2,p2,s2,70,5');payments.append('o0,2,voucher,60');reviews.append('extra,o0,3')
    return {name:('\n'.join(lines)+'\n').encode() for name,lines in {
        'orders.csv':orders,'items.csv':items,'payments.csv':payments,'reviews.csv':reviews,
        'customers.csv':['customer_id,customer_unique_id,customer_state,customer_zip_code_prefix','c0,u0,SP,01000','c1,u1,RJ,02000'],
        'products.csv':['product_id,product_category_name,product_weight_g','p1,books,100','p2,office,200'],
        'sellers.csv':['seller_id,seller_state','s1,SP','s2,RJ'],
        'geolocation.csv':['geolocation_zip_code_prefix,geolocation_lat,geolocation_lng','01000,-1,-2','01000,-2,-3'],
        'translation.csv':['product_category_name,product_category_name_english','books,Books','office,Office']}.items()}


def upload(client,auth,data=None,zipped=False):
    data=data or fixture()
    if zipped:
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,raw in data.items():archive.writestr('olist/'+name,raw)
        return client.post('/api/datasets/bundles/zip',headers=auth,data={'name':'Synthetic Olist'},files={'file':('olist.zip',stream.getvalue())})
    return client.post('/api/datasets/bundles/upload',headers=auth,data={'name':'Synthetic Olist','paths':['olist/'+n for n in data]},files=[('files',(n,raw)) for n,raw in data.items()])


@pytest.mark.parametrize('zipped',[False,True])
def test_nine_tables_correct_grains_filters_insights_exports(isolated,analyst_auth,auth,zipped):
    admin_auth=auth
    client,_=isolated;r=upload(client,analyst_auth,zipped=zipped);assert r.status_code==201,r.text
    ds=r.json();assert len(ds['tables'])==9;assert ds['row_count']==21
    assert ds['relational_analysis']['supported']
    assert any(not rel['enabled'] and rel['to_table']=='geolocation' for rel in ds['relational_analysis']['relationships'])
    ident=ds['dataset_id']; headers={**analyst_auth,'X-Dataset-ID':ident}
    selected=client.post(f'/api/datasets/{ident}/select',headers=analyst_auth)
    assert selected.json()['dataset_id']==ident
    response=client.get('/api/analytics/overview',headers=headers);assert response.status_code==200,response.text
    k=response.json()['kpis']
    assert k['total_orders']==2 and k['total_revenue']==190 and k['total_payments']==190
    assert k['unique_customers']==2 and k['items_sold']==3 and k['products_sold']==2 and k['active_sellers']==2
    assert k['avg_order_value']==95 and k['avg_review_score']==3 and k['avg_delivery_days']==4
    for filters,orders,revenue in [('date_to=2025-01-01',1,100),('category=office',1,70),('customer_state=RJ',1,90),('payment_type=voucher',1,100),('review_score=3',1,100),('seller_state=RJ',1,70)]:
        view=client.get('/api/analytics/overview?'+filters,headers=headers)
        assert view.status_code==200,view.text
        assert view.json()['kpis']['total_orders']==orders
        assert view.json()['kpis']['total_revenue']==revenue
        assert sum(p['revenue'] for p in view.json()['time_series'])==revenue
        if filters=='review_score=3': assert view.json()['kpis']['avg_review_score']==4
        if filters=='payment_type=voucher': assert view.json()['kpis']['total_payments']==100
        assert client.get('/api/reports/export?report=kpis&'+filters,headers=headers).status_code==200
    answer=client.post('/api/insights/query',headers=headers,json={'question':'What is the total revenue?'});assert answer.status_code==200,answer.text
    assert '190' in answer.json()['answer']
    assert client.get(f'/api/datasets/{ident}',headers=admin_auth).status_code==403
    assert client.get('/api/analytics/overview',headers={**admin_auth,'X-Dataset-ID':ident}).status_code==403
    assert client.get('/api/reports/export?report=dataset_rows',headers=headers).status_code==422
    assert client.get('/api/analytics/overview?column_filters={"bad":"x"}',headers=headers).status_code==422


def test_duplicate_dimension_disabled_not_fanout(isolated,analyst_auth):
    client,_=isolated;data=fixture();data['products.csv']+=b'p1,books,100\n'
    ds=upload(client,analyst_auth,data).json();headers={**analyst_auth,'X-Dataset-ID':ds['dataset_id']}
    assert client.get('/api/analytics/overview',headers=headers).json()['kpis']['total_revenue']==190
    assert client.get('/api/analytics/overview?category=books',headers=headers).status_code==422


@pytest.mark.parametrize('fault',['item_grain','numeric'])
def test_ambiguous_fact_grain_or_measure_never_becomes_revenue(isolated,analyst_auth,fault):
    client,_=isolated;data=fixture()
    if fault=='item_grain':data['items.csv']+=b'o0,1,p1,s1,30,10\n'
    else:data['items.csv']=data['items.csv'].replace(b',30,10',b',not-a-number,10')
    response=upload(client,analyst_auth,data);assert response.status_code==201,response.text
    headers={**analyst_auth,'X-Dataset-ID':response.json()['dataset_id']}
    view=client.get('/api/analytics/overview',headers=headers).json()
    assert view['kpis']['total_orders']==2 and view['kpis']['total_revenue'] is None
    assert 'Item revenue' in view['unavailable']


def test_shared_limit_separate_bundle_budgets(isolated,analyst_auth,monkeypatch):
    client,_=isolated;limits=client.get('/api/datasets/upload-limits',headers=analyst_auth).json()
    assert limits['max_bytes']==209715200 and limits['max_expanded_bytes']==536870912
    monkeypatch.setattr(datasets,'MAX_ROWS',1);monkeypatch.setattr(datasets,'MAX_CELLS',1)
    assert upload(client,analyst_auth).status_code==201
    monkeypatch.setattr(bundles,'MAX_TABLE_ROWS',1)
    assert upload(client,analyst_auth).status_code==422


def test_async_real_progress_ownership_and_atomic_failure(isolated,analyst_auth,auth,monkeypatch):
    admin_auth=auth
    client,factory=isolated;monkeypatch.setattr(bundle_jobs,'ASYNC_BYTES',1)
    result=upload(client,analyst_auth);assert result.status_code==202,result.text
    ident=result.json()['job_id'];path=f'/api/datasets/bundles/jobs/{ident}'
    assert client.get(path,headers=admin_auth).status_code==403
    for _ in range(200):
        status=client.get(path,headers=analyst_auth).json()
        if status['status'] not in {'QUEUED','PROCESSING'}:break
        time.sleep(.02)
    assert status['status']=='READY',status
    assert status['completed_tables']==9 and status['stored_rows']==21
    data=fixture();data['bad.csv']=b'a,b\n1,2,3\n'
    result=upload(client,analyst_auth,data);path=f"/api/datasets/bundles/jobs/{result.json()['job_id']}"
    for _ in range(200):
        status=client.get(path,headers=analyst_auth).json()
        if status['status'] not in {'QUEUED','PROCESSING'}:break
        time.sleep(.02)
    assert status['status']=='FAILED' and 'Nothing was imported' in status['error']
    with factory() as db:
        assert len(db.scalars(select(Dataset).where(Dataset.source_type=='bundle')).all())==1
        assert len([t for t in inspect(db.get_bind()).get_table_names() if t.startswith('dataset_')])==9


def test_existing_trusted_models_execute_bundle_contract(isolated,analyst_auth,monkeypatch):
    client,_=isolated;monkeypatch.setenv('ML_MODELS_DIR',str(ml.REPO_ROOT/'ml/models'));ml.load_all_metadata.cache_clear();ml._load_artifact.cache_clear()
    ds=upload(client,analyst_auth,fixture(40)).json();ident=ds['dataset_id'];headers={**analyst_auth,'X-Dataset-ID':ident}
    assert client.patch(f'/api/datasets/{ident}/schema',headers=analyst_auth,json={'fields':{},'currency_code':'BRL','domain':'commerce'}).status_code==200
    for path in ['/api/ml/forecast?periods=2&target=orders','/api/ml/forecast?periods=2&target=revenue','/api/ml/anomalies','/api/ml/segments/customers','/api/ml/product-segmentation']:
        response=client.get(path,headers=headers);assert response.status_code==200,response.text
        assert response.json()['status']=='available',response.text;ml.validate_output(response.json())
    predicted=client.post('/api/ml/predict/sales',headers=headers,json={'purchase_month':1,'purchase_weekday':0,'purchase_hour':12,'n_items':2,'customer_state':'SP','product_category_name':'books'})
    assert predicted.status_code==200 and predicted.json()['status']=='available',predicted.text
    # First daily forecast equals the deployed source model on the documented six features.
    import pandas as pd
    bundle=ml._load_artifact('sales_forecast_revenue')
    expected=float(bundle['model'].predict(pd.DataFrame([[90]*6],columns=bundle['features']))[0])
    actual=client.get('/api/ml/forecast?periods=1&target=revenue',headers=headers).json()['forecast'][0]['revenue']
    assert actual==round(expected,2)
    catalog=client.get('/api/ml/status',headers=headers).json();statuses=catalog['features']
    assert all(m['runtime_ready'] for feature in statuses if feature['name']!='abi_gradient_boosting_revenue' for m in feature['models'])
    candidate=catalog['source_candidates'][0]
    assert candidate['status']=='blocked' and not candidate['models'][0]['runtime_ready']


def test_cancel_and_concurrency_are_atomic(isolated,analyst_auth,monkeypatch):
    import threading
    client,factory=isolated;monkeypatch.setattr(bundle_jobs,'ASYNC_BYTES',1)
    started=threading.Event();release=threading.Event();original=datasets.profile_frame
    def paused(*args,**kwargs):
        started.set();assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(datasets,'profile_frame',paused)
    response=upload(client,analyst_auth);ident=response.json()['job_id'];assert started.wait(3)
    try:
        assert upload(client,analyst_auth).status_code==429
        assert client.post(f'/api/datasets/bundles/jobs/{ident}/cancel',headers=analyst_auth).status_code==200
    finally:release.set()
    for _ in range(200):
        status=client.get(f'/api/datasets/bundles/jobs/{ident}',headers=analyst_auth).json()
        if status['status'] not in {'QUEUED','PROCESSING'}:break
        time.sleep(.02)
    assert status['status']=='CANCELLED'
    with factory() as db:
        assert not db.scalars(select(Dataset)).all()
        assert not any(t.startswith('dataset_') for t in inspect(db.get_bind()).get_table_names())


def test_actual_200_mib_cap_rejects_stream_before_parsing(isolated):
    from types import SimpleNamespace
    _,factory=isolated
    class Payload:
        remaining=209715201
        def read(self,n):
            if not self.remaining:return b''
            n=min(n,self.remaining);self.remaining-=n;return b'x'*n
    with factory() as db:
        with pytest.raises(Exception) as failure:
            bundle_jobs.submit(db,{'username':'analyst'},'oversized',[SimpleNamespace(file=Payload())],['large.csv'])
        assert failure.value.status_code==413
        assert '209715200 bytes' in failure.value.detail and '209715201' in failure.value.detail
        assert not db.scalars(select(Dataset)).all()


def test_csv_escaping_after_sniff_sample_and_multiline():
    stream=io.StringIO(newline='')
    import csv
    writer=csv.writer(stream);writer.writerow(['review_id','comment'])
    writer.writerow(['first','ordinary text '*1000])
    writer.writerow(['second','A "quoted" review, with a comma\nand another line'])
    frame=datasets.parse_source(stream.getvalue().encode(),'.csv')
    assert len(frame)==2
    assert frame.iloc[1]['comment']=='A "quoted" review, with a comma\nand another line'


def test_multipart_budget_before_parser_and_chunked_receive(isolated,analyst_auth,monkeypatch):
    client,_=isolated
    headers={**analyst_auth,'Content-Type':'multipart/form-data; boundary=budget','Origin':'http://localhost:5173',
             'Content-Length':str(209715200+1048576+1)}
    response=client.post('/api/datasets/bundles/zip',headers=headers,content=b'')
    assert response.status_code==413 and response.headers['access-control-allow-origin']=='http://localhost:5173'
    monkeypatch.setattr(datasets,'MAX_BYTES',1000)
    def stream():
        yield b'--budget\r\nContent-Disposition: form-data; name="file"; filename="test.zip"\r\n\r\n'
        for _ in range(5):yield b'x'*262144
        yield b'\r\n--budget--\r\n'
    response=client.post('/api/datasets/bundles/zip-preview',headers={**analyst_auth,'Content-Type':'multipart/form-data; boundary=budget'},content=stream())
    assert response.status_code==413,response.text
    assert 'framing bytes' in response.json()['detail']


def test_windows_zip_paths_are_normalized_without_losing_member(isolated,analyst_auth):
    client,_=isolated;stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('folder\\nested\\sales.csv','date,revenue\n2025-01-01,100\n')
    response=client.post('/api/datasets/bundles/zip',headers=analyst_auth,data={'name':'Windows ZIP'},files={'file':('windows.zip',stream.getvalue())})
    assert response.status_code==201,response.text
    assert response.json()['tables'][0]['relative_path']=='folder/nested/sales.csv'


def test_bundle_date_correction_uses_bundle_limits_and_refreshes_relations(isolated,analyst_auth,monkeypatch):
    client,_=isolated;data=fixture()
    data['orders.csv']=data['orders.csv'].replace(b'2025-01-01',b'01/02/2025').replace(b'2025-01-02',b'02/03/2025')
    ds=upload(client,analyst_auth,data).json();assert not ds['relational_analysis']['supported']
    child=next(t for t in ds['tables'] if t['relative_path'].endswith('/orders.csv'))
    monkeypatch.setattr(datasets,'MAX_ROWS',1);monkeypatch.setattr(datasets,'MAX_CELLS',1)
    result=client.patch(f"/api/datasets/{child['dataset_id']}/schema",headers=analyst_auth,json={'date_order':'dayfirst','fields':{},'domain':'commerce'})
    assert result.status_code==200,result.text
    parent=client.get(f"/api/datasets/{ds['dataset_id']}",headers=analyst_auth).json()
    assert parent['relational_analysis']['supported']
    assert parent['column_count']==sum(t['column_count'] for t in parent['tables'])


def test_large_table_export_streams_all_filtered_rows_with_formula_safety(isolated,analyst_auth):
    client,_=isolated
    raw=b'record_id,region,comment\n'+b''.join(f'{i},{"Pune" if i%2==0 else "Delhi"},=untrusted\n'.encode() for i in range(5001))
    result=client.post('/api/datasets/upload',headers=analyst_auth,data={'name':'Streaming export'},files={'file':('export.csv',raw)})
    assert result.status_code==201 and result.json()['status']=='READY'
    ident=result.json()['dataset_id']
    response=client.get('/api/reports/export?report=dataset_rows&column_filters={"region":"Pune"}',headers={**analyst_auth,'X-Dataset-ID':ident})
    assert response.status_code==200
    import csv
    rows=list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows)==2501 and all(r['region']=='Pune' and r['comment']=="'=untrusted" for r in rows)
    assert response.headers['x-dataset-id']==ident
