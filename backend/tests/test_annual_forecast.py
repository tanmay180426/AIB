"""Real recursive annual API inference; original artifacts never opened for write."""
import json
import numpy as np
from tests.test_datasets import isolated  # noqa: F401
from tests.test_olist_bundle import upload,fixture
from tests.test_forecast_history import extended,register
from app.services import synthetic_forecast as serving


def test_year_and_short_horizons_use_registered_estimator_without_future_actuals(isolated,auth,tmp_path,monkeypatch):
    client,factory=isolated
    ds=upload(client,auth,data=extended()).json();ident=ds['dataset_id']
    register(factory,ident,tmp_path,monkeypatch)
    headers={**auth,'X-Dataset-ID':ident}
    original=serving._artifact;calls=[];outputs=[]
    class AuditedRealEstimator:
        def __init__(self,model):self.model=model
        def predict(self,rows):
            calls.extend(np.asarray(rows).tolist())
            predictions=self.model.predict(rows);outputs.extend(predictions.tolist());return predictions
    monkeypatch.setattr(serving,'_artifact',lambda *args:AuditedRealEstimator(original(*args)))
    response=client.get('/api/ml/forecast?periods=365&target=orders',headers=headers)
    assert response.status_code==200,response.text
    body=response.json();predicted=body['forecast_series']
    assert len(predicted)==365==len(calls)==len(outputs)
    assert body['forecast_origin']=='2021-12-31' and predicted[0]['date']=='2022-01-01' and predicted[-1]['date']=='2022-12-31'
    assert len({p['date'] for p in predicted})==365
    assert len(body['history_tail'])==30 and len(body['historical_series'])==1945
    assert body['historical_series'][5]['orders'] is None
    assert [p['orders'] for p in predicted]==[round(v,2) for v in outputs]
    assert calls[0][:4]==[1,1,1,1]
    # Step two consumes the actual first model prediction, not a future actual.
    assert calls[1][0]==outputs[0]
    assert calls[30][3]==outputs[0]
    assert any('annual forecast accuracy has not been validated' in w for w in body['warnings'])
    for horizon in (7,14,30,90,366):
        calls.clear();outputs.clear()
        other=client.get('/api/ml/forecast?periods='+str(horizon)+'&target=orders',headers=headers)
        assert other.status_code==200,other.text
        points=other.json()['forecast_series']
        assert len(points)==horizon==len(calls)
        assert points[:min(horizon,365)]==predicted[:min(horizon,365)]
        if horizon==366:assert points[-1]['date']=='2023-01-01'
    for horizon in (0,367):
        assert client.get('/api/ml/forecast?periods='+str(horizon),headers=headers).status_code==400
    revenue=client.get('/api/ml/forecast?periods=365&target=revenue',headers=headers).json()
    assert len(revenue['forecast_series'])==365 and revenue['historical_series'][10]['revenue'] is None
    assert 'currency unconfirmed' in revenue['unit']
    invalid=client.get('/api/ml/forecast?periods=365&target=revenue&date_to=2016-10-05',headers=headers).json()
    assert invalid['status']=='not_applicable' and invalid['forecast_series']==[]
    assert invalid['historical_series'] and '2016-09-14' in invalid['reason']


def test_annual_does_not_bypass_legacy_currency_or_owner_checks(isolated,auth,analyst_auth):
    client,_=isolated
    ds=upload(client,auth,data=fixture(days=65)).json()
    private={**auth,'X-Dataset-ID':ds['dataset_id']}
    assert client.get('/api/ml/forecast?periods=365',headers={**analyst_auth,'X-Dataset-ID':ds['dataset_id']}).status_code==403
    body=client.get('/api/ml/forecast?periods=365&target=revenue',headers=private).json()
    assert body['status']=='not_applicable' and body['forecast_series']==[]
    assert 'BRL' in body['reason']
    assert len(body['historical_series'])==65


def test_legacy_model_generates_real_annual_predictions_with_compatible_units(isolated,auth):
    client,_=isolated
    ds=upload(client,auth,data=fixture(days=65)).json()
    headers={**auth,'X-Dataset-ID':ds['dataset_id']}
    mapped=client.patch('/api/datasets/'+ds['dataset_id']+'/schema',headers=headers,json={'fields':{},'currency_code':'BRL','domain':'commerce'})
    assert mapped.status_code==200,mapped.text
    for target in ('orders','revenue'):
        result=client.get('/api/ml/forecast?target='+target+'&periods=365',headers=headers)
        assert result.status_code==200,result.text
        body=result.json()
        assert body['status']=='available' and len(body['forecast'])==365 and len(body['history_tail'])==30
        assert all(np.isfinite(p[target]) for p in body['forecast'])
