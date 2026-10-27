"""Read aggregate experiment evidence only; never load or promote model binaries.

An operator may point ML_EXPERIMENT_REPORT_PATH to an explicitly reviewed local
evaluation JSON. Missing evidence never becomes an accuracy or readiness claim.
"""
import json
import math
import os
from datetime import date
from functools import lru_cache
from pathlib import Path


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Invalid metric')
    return value


@lru_cache(maxsize=4)
def _read(path, mtime, size):
    if size > 2_000_000:
        raise ValueError('Oversized evaluation report')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def candidate_evidence(name):
    target = name.removeprefix('sales_forecast_')
    if name not in ('sales_forecast_orders', 'sales_forecast_revenue'):
        return None
    unavailable = {'available': False, 'promoted': False,
                   'reason': 'No reviewed local candidate evaluation report is configured.'}
    configured = os.environ.get('ML_EXPERIMENT_REPORT_PATH')
    if not configured:
        return unavailable
    try:
        path = Path(configured)
        stat = path.stat()
        report = _read(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        protocol, data = report['protocol'], report['targets'][target]
        winner = data['winner_selected_on_validation']
        if winner not in ('ridge_recursive', 'ridge_direct', 'forest_recursive', 'boost_recursive',
                          'lightgbm_recursive', 'sarima_weekly', 'ets_weekly'):
            raise ValueError('Unknown candidate')
        for phase in ('train', 'validation', 'holdout'):
            window = protocol[phase]
            if len(window) != 3 or not isinstance(window[2], int) or window[2] <= 0:
                raise ValueError('Invalid evaluation window')
            if (date.fromisoformat(window[1])-date.fromisoformat(window[0])).days+1 != window[2]:
                raise ValueError('Inconsistent evaluation dates')
        if not protocol['train'][1] < protocol['validation'][0] <= protocol['validation'][1] < protocol['holdout'][0]:
            raise ValueError('Evaluation periods overlap')
        if not isinstance(protocol['selection'], str) or len(protocol['selection']) > 300:
            raise ValueError('Invalid selection policy')
        rows = []
        for phase in ('validation', 'holdout'):
            for h in (7, 14, 30, 90):
                row = data[phase][str(h)]
                selected = {key: {metric: _number(value.get(metric))
                    for metric in ('mae', 'rmse', 'r2', 'wape_pct', 'mape_nonzero_pct', 'mase',
                                   'inference_time_seconds', 'n')}
                    for key, value in row['metrics'].items()
                    if key in (winner, 'last_value', 'seasonal_naive', 'legacy_refit', 'legacy_frozen')}
                if not {winner, 'last_value', 'seasonal_naive'} <= selected.keys():
                    raise ValueError('Incomplete comparison')
                if row['origins'] <= 0 or row['points'] != row['origins']*h or row['points'] > protocol[phase][2]:
                    raise ValueError('Inconsistent sample counts')
                if any(m['n'] != row['points'] or m['mae'] is None or m['rmse'] is None or m['mae'] < 0 or m['rmse'] < 0 for m in selected.values()):
                    raise ValueError('Invalid comparison metrics')
                rows.append({'phase': phase, 'horizon': h, 'origins': int(row['origins']),
                             'points': int(row['points']), 'metrics': selected})
        reasons = data['qualification']['reasons']
        if not isinstance(reasons, list) or any(not isinstance(s, str) or len(s) > 200 for s in reasons):
            raise ValueError('Invalid reasons')
        return {'available': True, 'promoted': False, 'winner': winner,
                'status': 'Experimental evidence only; existing serving artifact retained',
                'qualified_in_experiment': data['qualification']['qualified'] is True,
                'reasons': reasons, 'train': protocol['train'],
                'validation': protocol['validation'], 'holdout': protocol['holdout'],
                'selection': protocol['selection'], 'rows': rows,
                'limitations': ['Offline source evaluation is not selected-dataset accuracy.',
                    'Only one 90-day origin per phase; long-horizon evidence is limited.',
                    'Frozen legacy fit cutoff is declared, not independently persisted. Earlier validation uses a refitted legacy algorithm.']}
    except (OSError, ValueError, KeyError, TypeError, OverflowError, IndexError, AttributeError):
        return {**unavailable, 'reason': 'Configured candidate evidence is unavailable or invalid; no quality claim is made.'}
