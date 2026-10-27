"""Source binding, real fitted artifact, raw-unit isolation and honest gaps."""
import hashlib
import json
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
import joblib
from sklearn.linear_model import Ridge
from app.analytics.filters import Filters
from app.services import synthetic_forecast as serving
from app.services.synthetic_features import FEATURES,features,recursive


def test_real_fitted_registered_artifact_uses_exact_schema_and_checksum(tmp_path):
    dates=pd.date_range('2020-01-01',periods=140)
    values=100+np.arange(140)*.1
    x=[features(values[:i],dates[i]) for i in range(30,140)]
    model=Ridge(alpha=1).fit(x,values[30:])
    path=tmp_path/'synthetic-orders-v1.joblib'
    joblib.dump({'model':model,'features':FEATURES,'version':'synthetic-v1'},path)
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    loaded=serving._artifact(str(path),checksum)
    output=recursive(loaded,values[-30:],pd.date_range('2020-05-20',periods=7))
    assert len(output)==7 and np.isfinite(output).all()
    with pytest.raises(ValueError,match='checksum'):serving._artifact(str(path),'0'*64)


def test_only_explicit_matching_bundle_can_use_synthetic_registration(monkeypatch):
    class DB:
        info={'dataset':SimpleNamespace(id='a',source_type='bundle')}
        def execute(self,*args):
            return SimpleNamespace(all=lambda:[('table-a',123,pd.Timestamp('2020-01-01').to_pydatetime())])
    monkeypatch.setattr(serving,'registry',lambda:{'datasets':{'b':{}}})
    assert serving.binding(DB()) is None
    monkeypatch.setattr(serving,'registry',lambda:{'datasets':{'a':{'members':{'table-a':{'rows':123,'updated_at':'2020-01-01 00:00:00'}}}}})
    assert serving.binding(DB())['datasets']['a']
    monkeypatch.setattr(serving,'registry',lambda:{'datasets':{'a':{'members':{}}}})
    assert 'changed' in serving.binding(DB())['invalid']


def test_daily_gap_or_unknown_revenue_blocks_only_latest_window(monkeypatch):
    from app.analytics import metrics
    points=[{'period':str(d.date()),'orders':2,'revenue':20} for d in pd.date_range('2021-01-01',periods=60)]
    points[0]['revenue']=None
    monkeypatch.setattr(serving,'binding',lambda db:{'models':{'orders':{'unit':'orders'},'revenue':{'unit':'source revenue units — currency unconfirmed'}}})
    monkeypatch.setattr(metrics,'time_series',lambda *args,**kwargs:points)
    assert serving.compatibility(None,Filters(),'revenue')['compatible']
    points[-1]['revenue']=None
    assert not serving.compatibility(None,Filters(),'revenue')['compatible']
    assert serving.compatibility(None,Filters(),'orders')['compatible']
    points.pop(-2)
    assert not serving.compatibility(None,Filters(),'orders')['compatible']


def test_incomplete_or_malformed_registration_does_not_activate_anything(monkeypatch,tmp_path):
    path=tmp_path/'registry.json';monkeypatch.setenv('ML_SYNTHETIC_REGISTRY',str(path))
    for content in ('[]','{',json.dumps({'version':'synthetic-v1','features':FEATURES})):
        path.write_text(content);assert serving.registry() is None


def test_aggregation_cache_is_only_for_one_request_and_filter_scope(monkeypatch):
    from app.analytics import metrics
    calls=[]
    def actual_call(*args,**kwargs):calls.append(1);return [{'period':'2021-01-01','orders':2}]
    monkeypatch.setattr(metrics,'time_series',actual_call)
    first=SimpleNamespace(info={});second=SimpleNamespace(info={})
    assert serving._series(first,Filters()) is serving._series(first,Filters())
    assert len(calls)==1
    serving._series(first,Filters(date_to='2021-01-31'));serving._series(second,Filters())
    assert len(calls)==3
    first.info['dataset']=SimpleNamespace(id='another-source')
    serving._series(first,Filters())
    assert len(calls)==4
