"""Leakage, real estimator execution, qualification and safe output boundaries."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import joblib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.forecasting import evaluate_candidates as experiment


def frame(n=150):
    return pd.DataFrame({'date': pd.date_range('2020-01-01', periods=n, tz='UTC'),
                         'orders': 50+np.arange(n)*.1+np.sin(np.arange(n)),
                         'revenue': 500+np.arange(n)})


@pytest.mark.parametrize('problem', ['gap', 'duplicate', 'null', 'negative', 'invalid_date'])
def test_bad_history_is_rejected_without_filling(problem):
    data = frame()
    if problem == 'gap': data = data.drop(50)
    if problem == 'duplicate': data.loc[50, 'date'] = data.date.iloc[49]
    if problem == 'null': data.loc[50, 'orders'] = np.nan
    if problem == 'negative': data.loc[50, 'revenue'] = -1
    if problem == 'invalid_date': data.loc[50, 'date'] = pd.NaT
    with pytest.raises(ValueError): experiment.validate_series(data)


@pytest.mark.parametrize('name', experiment.NAMES)
def test_real_estimator_is_fitted_on_prior_rows_only(name):
    data = frame()
    values, dates = data.orders.to_numpy(), data.date.to_numpy()
    model, rows = experiment.fit_candidate(name, values[:100], dates[:100], 7)
    assert rows == (64 if name == 'ridge_direct' else 70)
    prediction = experiment.predict_candidate(name, model, values[:100], dates[100:107])
    assert len(prediction) == 7 and np.isfinite(prediction).all()
    # Future target changes never enter fit or the recursive feature construction.
    changed = values.copy(); changed[100:] = 999999
    assert np.array_equal(experiment.feature_row(changed[:100], dates[100]),
                          experiment.feature_row(values[:100], dates[100]))
    again, _ = experiment.fit_candidate(name, changed[:100], dates[:100], 7)
    assert np.allclose(prediction, experiment.predict_candidate(name, again, changed[:100], dates[100:107]))


def test_metrics_zero_policy_and_invalid_data():
    result = experiment.score([0, 2], [1, 3], 2)
    assert result['mae'] == result['rmse'] == 1
    assert result['wape_pct'] == 100 and result['mase'] == .5
    assert result['mape_excluded_zeros'] == 1
    assert experiment.score([0], [0], 0)['wape_pct'] is None
    for actual, predicted in [([np.nan], [1]), ([1], [np.inf]), ([1], [1, 2])]:
        with pytest.raises(ValueError): experiment.score(actual, predicted, 1)


def test_walk_forward_targets_are_disjoint_and_report_same_aligned_points():
    result = experiment.evaluate(frame(200), 'orders', 110, 200, ['last_value', 'seasonal_naive'])
    for horizon in experiment.HORIZONS:
        row = result[str(horizon)]
        assert row['origins'] == 90//horizon
        assert len(row['series']) == row['points'] == row['origins']*horizon
        assert len({p['date'] for p in row['series']}) == row['points']
        for window in row['windows']:
            assert window['origin'] < window['from'] <= window['to']
        assert row['metrics']['last_value']['n'] == row['metrics']['seasonal_naive']['n']


def test_one_candidate_failure_does_not_skip_other_candidates(monkeypatch):
    original = experiment.fit_candidate

    def fail_ridge(name, values, dates, horizon):
        if name == 'ridge_recursive':
            raise RuntimeError('intentional candidate failure')
        return original(name, values, dates, horizon)

    monkeypatch.setattr(experiment, 'fit_candidate', fail_ridge)
    result = experiment.evaluate(frame(200), 'orders', 110, 200,
                                 ['last_value', 'ridge_recursive', 'forest_recursive'])
    for horizon in experiment.HORIZONS:
        row = result[str(horizon)]
        assert 'intentional candidate failure' in row['candidate_failures']['ridge_recursive']
        assert 'ridge_recursive' not in row['metrics']
        assert row['metrics']['forest_recursive']['n'] == row['points']


def test_scaled_ets_candidate_round_trips_as_a_loadable_artifact(tmp_path):
    data = frame()
    values, dates = data.orders.to_numpy(), data.date.to_numpy()
    model, rows = experiment.fit_candidate('ets_weekly', values, dates, 7)
    path = tmp_path/'ets.joblib'
    joblib.dump({'model': model}, path)
    restored = joblib.load(path)['model']
    prediction = experiment.predict_candidate('ets_weekly', restored, values,
                                              pd.date_range(data.date.iloc[-1]+pd.Timedelta(days=1), periods=7))
    assert rows == len(values)
    assert len(prediction) == 7 and np.isfinite(prediction).all()


def test_qualification_cannot_hide_instability_or_unknown_provenance():
    result = experiment.evaluate(frame(200), 'orders', 110, 200, ['last_value', 'seasonal_naive'])
    gate = experiment.quality_gate(result, result, 'last_value', False, False)
    assert not gate['qualified']
    assert any('5% MAE' in reason for reason in gate['reasons'])
    assert any('provenance' in reason for reason in gate['reasons'])
    assert any('currency' in reason for reason in gate['reasons'])
    assert 'one independent origin' in gate['ninety_day_claim']


def test_no_experiment_can_overwrite_source_or_load_arbitrary_artifacts():
    repo = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError, match='outside'):
        experiment.run('unused', {}, repo/'ml/models', repo/'ml/models')
    with pytest.raises(ValueError, match='reviewed'):
        experiment.run('unused', {}, Path.home()/'unused-abi-experiment', Path.home())
