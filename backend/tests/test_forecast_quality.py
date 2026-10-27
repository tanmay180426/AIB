"""Candidate reports cannot activate artifacts or impersonate selected accuracy."""
import json
import pytest
from app.services.forecast_quality import candidate_evidence


def evidence():
    metrics = {name: {'mae': 4., 'rmse': 5., 'wape_pct': 10., 'mase': .5, 'n': 84}
               for name in ('ridge_direct', 'last_value', 'seasonal_naive', 'legacy_frozen', 'legacy_refit')}
    rows = {str(h): {'origins': 90//h, 'points': (90//h)*h,
                    'metrics': {name: {**value, 'n':(90//h)*h} for name,value in metrics.items()}}
            for h in (7, 14, 30, 90)}
    return {'protocol': {'train': ['2020-01-01', '2021-01-01', 367],
            'validation': ['2021-01-02', '2021-04-01', 90], 'holdout': ['2021-04-02', '2021-06-30', 90],
            'selection': 'Validation only', 'private_path': 'never returned'},
        'targets': {'orders': {'winner_selected_on_validation': 'ridge_direct',
             'validation': rows, 'holdout': rows, 'qualification': {'qualified': False, 'reasons': ['Insufficient evidence']}}}}


def test_optional_report_is_unavailable_without_claims(monkeypatch):
    monkeypatch.delenv('ML_EXPERIMENT_REPORT_PATH', raising=False)
    assert candidate_evidence('sales_forecast_orders')['available'] is False
    assert candidate_evidence('customer_segmentation') is None


def test_report_shows_only_aggregate_diagnostics_and_never_promotes(monkeypatch, tmp_path):
    path = tmp_path/'report.json'
    value = evidence()
    value['targets']['orders']['qualification']['qualified'] = True
    path.write_text(json.dumps(value))
    monkeypatch.setenv('ML_EXPERIMENT_REPORT_PATH', str(path))
    result = candidate_evidence('sales_forecast_orders')
    assert result['available'] and not result['promoted']
    assert len(result['rows']) == 8
    assert 'never returned' not in json.dumps(result)
    assert result['rows'][0]['metrics']['ridge_direct']['mae'] == 4
    assert 'not selected-dataset' in result['limitations'][0]


@pytest.mark.parametrize('kind', ['invalid_json', 'nonfinite', 'missing_baseline', 'oversized', 'unknown_model', 'overlap', 'wrong_n'])
def test_malformed_or_incomplete_report_fails_closed(monkeypatch, tmp_path, kind):
    path = tmp_path/'report.json'
    value = evidence()
    if kind == 'nonfinite': value['targets']['orders']['holdout']['7']['metrics']['ridge_direct']['mae'] = float('nan')
    if kind == 'missing_baseline': del value['targets']['orders']['holdout']['7']['metrics']['last_value']
    if kind == 'unknown_model': value['targets']['orders']['winner_selected_on_validation'] = 'arbitrary.pkl'
    if kind == 'overlap': value['protocol']['holdout'] = value['protocol']['validation']
    if kind == 'wrong_n': value['targets']['orders']['holdout']['7']['metrics']['ridge_direct']['n'] = 1
    path.write_text('{' if kind == 'invalid_json' else 'x'*2_000_001 if kind == 'oversized' else json.dumps(value))
    monkeypatch.setenv('ML_EXPERIMENT_REPORT_PATH', str(path))
    assert candidate_evidence('sales_forecast_orders')['available'] is False
