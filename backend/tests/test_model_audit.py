"""Evaluation arithmetic and chronology, without fitting any trusted model."""
import numpy as np
import pandas as pd
import pytest
from app.services.model_audit import error_metrics, recursive_values, _forecast_replay, audit_model
from app.services.ml import daily_readiness

FEATURES = ['lag1', 'lag7', 'lag14', 'lag30', 'roll7', 'roll30']


class LastValue:
    def predict(self, rows):
        return rows['lag1'].to_numpy()


def test_metrics_have_defined_zero_and_constant_denominators():
    result = error_metrics([1, 2, 3], [2, 2, 2], 2)
    assert result['mae'] == .6667
    assert result['rmse'] == .8165
    assert result['wape_pct'] == 33.3333
    assert result['mase'] == .3333
    zero = error_metrics([0, 0], [0, 0], 0)
    assert zero['mae'] == zero['rmse'] == 0
    assert zero['wape_pct'] is zero['mase'] is zero['mape_nonzero_pct'] is None
    assert zero['mape_excluded_zeros'] == 2


@pytest.mark.parametrize('actual,predicted', [([], []), ([1], [1, 2]), ([1, np.nan], [1, 2]), ([1], [np.inf])])
def test_invalid_evaluation_never_produces_plausible_metrics(actual, predicted):
    with pytest.raises(ValueError): error_metrics(actual, predicted)


def test_recursive_predicts_from_past_values_only_and_preserves_zero():
    assert recursive_values(LastValue(), FEATURES, list(range(30)), 7) == [29]*7
    assert recursive_values(LastValue(), FEATURES, [0]*30, 7) == [0]*7
    assert recursive_values(LastValue(), FEATURES, [5]*30, 7) == [5]*7
    for history in ([1]*29, [-1]+[1]*29, [np.inf]+[1]*29):
        with pytest.raises(ValueError): recursive_values(LastValue(), FEATURES, history, 7)


def test_readiness_reports_gaps_invalid_targets_and_calendar_dates():
    points=[{'period':str(day.date()),'orders':1,'revenue':10} for day in pd.date_range('2025-01-01',periods=40)]
    points.pop(20)
    ready=daily_readiness(points,['orders','revenue'])
    assert ready['missing_calendar_days']==1 and ready['observations']==39
    assert not ready['latest_window_consecutive']
    points[-1]['revenue']=None
    assert daily_readiness(points,['revenue'])['invalid_targets']==['revenue']
    assert daily_readiness([],['orders'])['observations']==0


def test_replay_uses_chronological_declared_split_and_disjoint_future_windows():
    frame=pd.DataFrame({'date':pd.date_range('2025-01-01',periods=104),'orders':np.arange(104,dtype=float)})
    meta={'name':'sales_forecast_orders','metrics':{'n_train':59,'n_test':15,'model':{'mae':1,'rmse':1}}}
    result=_forecast_replay(frame,meta,{'model':LastValue(),'features':FEATURES})
    assert result['declared_training_cutoff']=='2025-03-30'
    assert result['evaluation_from']=='2025-03-31'
    assert result['recorded_mae_rmse_reproduced']
    week=result['recursive_calendar_windows'][0]
    assert week['origins']==2 and week['model']['n']==14
    assert week['model']['mae']==4  # errors 1..7 for each frozen origin
    assert week['last_test_date']=='2025-04-13'
    assert week['excluded_test_observations']==1
    assert result['recursive_calendar_windows'][2]['model'] is None
    assert result['recursive_calendar_windows'][3]['horizon']==90
    assert result['recursive_calendar_windows'][3]['model'] is None


def test_missing_training_source_cannot_create_evaluation(monkeypatch,tmp_path):
    from app.services import ml
    monkeypatch.setattr(ml,'processed_dir',lambda:tmp_path)
    assert audit_model('sales_forecast_orders')['status']=='unavailable'
    assert audit_model('unapproved_candidate')['status']=='unavailable'
