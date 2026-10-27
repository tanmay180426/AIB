import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.forecasting import train_synthetic as training


def fixture(n=500):
    return pd.DataFrame({'date':pd.date_range('2016-01-01',periods=n,tz='UTC'),
                         'orders':100+np.arange(n)*.05+np.sin(np.arange(n)),
                         'revenue':1000+np.arange(n)})


def test_unknown_calendar_days_and_missing_revenue_are_not_zeroes():
    data=fixture().drop(80);data.loc[100,'revenue']=np.nan
    aligned=training.prepare(data)
    assert len(aligned)==500
    assert np.isnan(aligned.orders.iloc[80]) and np.isnan(aligned.revenue.iloc[80])
    assert np.isnan(aligned.revenue.iloc[100])
    assert aligned.orders.iloc[81] == pytest.approx(fixture().orders.iloc[81])


@pytest.mark.parametrize('name',training.NAMES)
def test_real_fit_excludes_exactly_affected_windows_and_has_finite_inference(name):
    data=fixture(300);data.loc[80,'orders']=np.nan
    values=data.orders.to_numpy();dates=data.date.to_numpy()
    model,rows,excluded=training.fit(name,values,dates)
    assert rows==239 and excluded==31
    output=training.recursive(model,values[-30:],pd.date_range(data.date.iloc[-1]+pd.Timedelta(days=1),periods=7))
    assert len(output)==7 and np.isfinite(output).all()


def test_features_and_scaling_never_see_future_targets():
    data=fixture();values=data.orders.to_numpy();dates=data.date.to_numpy()
    first,rows,_=training.fit('ridge',values[:300],dates[:300])
    changed=values.copy();changed[300:]=999999
    second,again,_=training.fit('ridge',changed[:300],dates[:300])
    assert rows==again
    assert np.allclose(first.predict([training.features(values[:300],dates[300])]),second.predict([training.features(changed[:300],dates[300])]))


def test_same_calendar_holdout_and_disjoint_origins_for_every_method():
    data=fixture(500)
    result=training.evaluate(data,'orders',300,500,['last_value','seasonal_naive','ridge'])
    for h,row in result.items():
        assert row['points']==row['origins']*int(h)
        assert len({w['from'] for w in row['windows']})==row['origins']
        assert row['metrics']['ridge']['n']==row['metrics']['last_value']['n']
        assert all(w['origin']<w['from']<=w['to'] for w in row['windows'])


def test_old_short_source_and_serving_directory_outputs_are_rejected(tmp_path):
    with pytest.raises(ValueError,match='outside'):
        training.run('unused',{},Path(__file__).resolve().parents[1]/'models')
    path=tmp_path/'short.csv';fixture().to_csv(path,index=False)
    with pytest.raises(ValueError,match='five-year'):
        training.run(path,{},tmp_path/'experiment')
