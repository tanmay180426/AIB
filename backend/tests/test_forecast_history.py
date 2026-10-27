"""Real authorized bundle aggregation + fitted registered test model, no mocks of inference."""
import csv
import hashlib
import io
import json
from datetime import date,timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sqlalchemy import select

from tests.test_datasets import isolated  # noqa: F401
from tests.test_olist_bundle import fixture,upload
from app.models.dataset import Dataset,DatasetBundleTable
from app.services.synthetic_features import FEATURES,features


def extended():
    raw=fixture(days=1945)
    rows=list(csv.DictReader(io.StringIO(raw['orders.csv'].decode())))
    for i,row in enumerate(rows):
        day=date(2016,9,4)+timedelta(days=i)
        # One unknown early date, and one unknown revenue date; final input is intact.
        if i==5:day+=timedelta(days=1)
        row.update(order_purchase_timestamp=str(day),order_delivered_customer_date=str(day+timedelta(days=3)),order_estimated_delivery_date=str(day+timedelta(days=7)))
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    raw['orders.csv']=stream.getvalue().encode()
    raw['items.csv']=b'\n'.join(line for line in raw['items.csv'].splitlines() if not line.startswith(b'o10,'))+b'\n'
    return raw


def register(factory,ident,tmp_path,monkeypatch):
    from app.services import synthetic_forecast as serving
    values=10+np.arange(120)*.1;dates=pd.date_range('2020-01-01',periods=120)
    # Only a disposable estimator is fitted. Existing serving files are never opened for write.
    estimator=Ridge().fit([features(values[:i],dates[i]) for i in range(30,120)],values[30:])
    artifact=tmp_path/'fixture.joblib';joblib.dump({'model':estimator,'features':FEATURES,'version':'synthetic-v1'},artifact)
    with factory() as db:
        members=db.execute(select(Dataset.id,Dataset.row_count,Dataset.updated_at).join(DatasetBundleTable,Dataset.id==DatasetBundleTable.dataset_id).where(DatasetBundleTable.bundle_id==ident)).all()
    models={target:{'artifact':artifact.name,'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'unit':'expected orders' if target=='orders' else 'source revenue units — currency unconfirmed','quality':{'qualified_synthetic_demo':False,'real_world_qualified':False},'evaluation':{},'name':'registered-test-'+target,'version':'synthetic-v1','algorithm':'ridge','training_cutoff':'2021-12-31'} for target in ('orders','revenue')}
    registry={'version':'synthetic-v1','features':FEATURES,'coverage':['2016-09-04','2021-12-31'],'missing_policy':'Unknown is null','datasets':{ident:{'members':{key:{'rows':n,'updated_at':str(revision)} for key,n,revision in members}}},'models':models}
    path=tmp_path/'registry.json';path.write_text(json.dumps(registry));monkeypatch.setenv('ML_SYNTHETIC_REGISTRY',str(path));serving._artifact.cache_clear()
    return path,artifact


def test_complete_history_real_registered_inference_filters_and_private_discovery(isolated,analyst_auth,auth,tmp_path,monkeypatch):
    client,factory=isolated
    response=upload(client,auth,data=extended());assert response.status_code==201,response.text
    ident=response.json()['dataset_id'];headers={**auth,'X-Dataset-ID':ident}
    registry,artifact=register(factory,ident,tmp_path,monkeypatch)
    response=client.get('/api/ml/forecast?target=orders&periods=30',headers=headers);assert response.status_code==200,response.text
    body=response.json()
    assert body['dataset_id']==ident==body['selected_scope']['dataset_id']
    assert body['synthetic_registration']['status']=='matches'
    history=body['historical_series'];future=body['forecast_series']
    assert len(history)==1945 and len(body['history_tail'])==30
    assert history[0]=={'date':'2016-09-04','orders':1}
    assert history[-1]=={'date':'2021-12-31','orders':1}
    assert history[5]['orders'] is None and history[6]['orders']==2
    assert body['historical_coverage']['missing_dates']==1 and body['historical_coverage']['zero_filled']==0
    assert body['forecast_origin']=='2021-12-31'
    assert len(future)==30 and future==body['forecast']
    assert future[0]['date']=='2022-01-01' and future[-1]['date']=='2022-01-30'
    assert all(np.isfinite(p['orders']) for p in future)
    revenue=client.get('/api/ml/forecast?target=revenue&periods=7',headers=headers).json()
    assert revenue['historical_series'][10]['revenue'] is None
    assert revenue['historical_coverage']['unknown_target_days']==1
    assert 'currency unconfirmed' in revenue['unit'] and len(revenue['forecast_series'])==7
    cutoff=client.get('/api/ml/forecast?target=orders&periods=7&date_to=2018-12-31',headers=headers).json()
    assert cutoff['forecast_origin']=='2018-12-31' and cutoff['forecast_series'][0]['date']=='2019-01-01'
    assert cutoff['historical_series'][-1]['date']=='2018-12-31' and len(cutoff['historical_series'])>30
    short=client.get('/api/ml/forecast?target=orders&date_from=2016-09-04&date_to=2016-09-15',headers=headers).json()
    assert short['status']=='not_applicable' and short['forecast_series']==[] and len(short['historical_series'])==12
    unknown=client.get('/api/ml/forecast?target=revenue&date_to=2016-10-05',headers=headers).json()
    assert unknown['status']=='not_applicable' and '2016-09-14' in unknown['reason']
    # An unregistered older bundle never receives the other bundle's predictions.
    wrong=fixture(days=65);wrong['orders.csv']=wrong['orders.csv'].replace(b'2025-02-10,',b'2025-02-11,')
    old=upload(client,auth,data=wrong).json()['dataset_id']
    wrong_body=client.get('/api/ml/forecast?target=orders',headers={**auth,'X-Dataset-ID':old}).json()
    assert wrong_body['dataset_id']==old and wrong_body['status']=='not_applicable'
    assert 'consecutive' in wrong_body['reason'] and wrong_body['forecast_series']==[]
    assert wrong_body['historical_series'][0]['date']=='2025-01-01'
    assert wrong_body['synthetic_registration']['status']=='different_dataset'
    assert wrong_body['synthetic_registration']['datasets'][0]['dataset_id']==ident
    # Private registration discovery must not leak another owner's bundle.
    analyst=upload(client,analyst_auth).json()['dataset_id']
    private=client.get('/api/ml/forecast?target=orders',headers={**analyst_auth,'X-Dataset-ID':analyst}).json()
    assert private['synthetic_registration']['datasets']==[]
    # Legitimate data revisions are still rejected; no automatic rebinding occurs.
    with factory() as db:
        member=db.get(Dataset,next(iter(json.loads(registry.read_text())['datasets'][ident]['members'])))
        member.row_count+=1;db.commit()
    changed=client.get('/api/ml/forecast?target=orders',headers=headers).json()
    assert changed['status']=='not_applicable' and 'changed' in changed['reason']
    assert changed['synthetic_registration']['status']=='revision_mismatch'


def test_chart_validation_rejects_ambiguous_dates_and_invalid_numbers(monkeypatch):
    import pytest
    from app.analytics.filters import Filters
    from app.services import synthetic_forecast as serving
    for points in ([{'period':'2021-01-01','orders':1}]*2,[{'period':'2021-01-01','orders':float('nan')}],[{'period':'2021-02-30','orders':1}]):
        monkeypatch.setattr(serving,'_series',lambda *args:points)
        with pytest.raises(ValueError):serving.chart_history(None,Filters(),'orders')
