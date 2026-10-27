"""Explicit bounded experiments. Never writes serving models or trains on requests.

Run with a contiguous observed daily CSV and an explicit provenance document.
Validation selects one candidate per target before the final segment is scored.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import platform
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

HORIZONS = (7, 14, 30, 90)
PRIMARY = (7, 14, 30)
NAMES = ('ridge_recursive', 'forest_recursive', 'boost_recursive', 'ridge_direct')
CLASSICAL_NAMES = ('lightgbm_recursive', 'sarima_weekly', 'ets_weekly')
ALL_NAMES = NAMES + CLASSICAL_NAMES
FEATURES = ('lag1', 'lag7', 'lag14', 'lag30', 'roll7', 'roll30', 'std7', 'std30',
            'weekday_sin', 'weekday_cos', 'month_sin', 'month_cos')
LEGACY_FEATURES = FEATURES[:6]
SEED = 42


def validate_series(frame):
    frame = frame.copy()
    frame['date'] = pd.to_datetime(frame.date, errors='raise', utc=True)
    if frame.date.isna().any() or frame.date.duplicated().any():
        raise ValueError('Unique valid dates required.')
    frame = frame.sort_values('date').reset_index(drop=True)
    if not frame.date.diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError('Only a complete observed daily block is supported; no gaps are filled.')
    if not np.isfinite(frame[['orders', 'revenue']].to_numpy(dtype=float)).all():
        raise ValueError('Both targets must have observed finite values.')
    if (frame[['orders', 'revenue']] < 0).any().any():
        raise ValueError('Historical target values must be nonnegative.')
    return frame


def feature_row(history, when):
    values = np.asarray(history, dtype=float)
    if len(values) < 30 or not np.isfinite(values).all():
        raise ValueError('Thirty finite prior observations required.')
    day = pd.Timestamp(when)
    return [values[-1], values[-7], values[-14], values[-30], values[-7:].mean(),
            values[-30:].mean(), values[-7:].std(), values[-30:].std(),
            np.sin(2*np.pi*day.dayofweek/7), np.cos(2*np.pi*day.dayofweek/7),
            np.sin(2*np.pi*(day.month-1)/12), np.cos(2*np.pi*(day.month-1)/12)]


def estimator(name):
    if name.startswith('ridge'):
        return make_pipeline(StandardScaler(), Ridge(alpha=100.0))
    if name == 'forest_recursive':
        return RandomForestRegressor(n_estimators=64, max_depth=6, min_samples_leaf=8,
                                     random_state=SEED, n_jobs=1)
    if name == 'boost_recursive':
        return HistGradientBoostingRegressor(max_iter=80, max_leaf_nodes=7,
                                            learning_rate=.05, l2_regularization=5,
                                            early_stopping=False, random_state=SEED)
    if name == 'legacy_refit':
        return LinearRegression()
    if name == 'lightgbm_recursive':
        try:
            from lightgbm import LGBMRegressor
        except ImportError as error:
            raise RuntimeError('LightGBM candidate unavailable: install ml/requirements-forecasting.txt.') from error
        return LGBMRegressor(n_estimators=120, num_leaves=15, max_depth=5,
                             learning_rate=.04, min_child_samples=20,
                             reg_lambda=2, verbosity=-1, random_state=SEED,
                             n_jobs=1, deterministic=True, force_col_wise=True)
    raise ValueError('Unknown estimator.')


def fit_candidate(name, values, dates, horizon):
    """Only values strictly before the forecast origin are passed here."""
    if name in ('sarima_weekly', 'ets_weekly'):
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            from statsmodels.tsa.statespace.sarimax import SARIMAX
        except ImportError as error:
            raise RuntimeError(f'{name} candidate unavailable: statsmodels is not installed.') from error
        y = np.asarray(values, dtype=float)
        if len(y) < 56:
            raise ValueError('Weekly seasonal models require at least 56 prior daily observations.')
        if name == 'sarima_weekly':
            model = SARIMAX(y, order=(1, 0, 0), seasonal_order=(1, 0, 0, 7),
                            trend='c', enforce_stationarity=False, enforce_invertibility=False,
                            simple_differencing=True).fit(method='powell', disp=False, maxiter=50)
            if not model.mle_retvals.get('converged', True):
                raise RuntimeError('SARIMAX optimizer did not converge.')
        else:
            scale = max(float(np.mean(np.abs(y))), 1.0)
            fitted = ExponentialSmoothing(y/scale, trend='add', damped_trend=True,
                    seasonal='add', seasonal_periods=7, initialization_method='estimated').fit(
                    optimized=True, use_brute=False)
            retvals = getattr(fitted, 'mle_retvals', {})
            if retvals and not retvals.get('success', True):
                raise RuntimeError('ETS optimizer did not converge.')
            # A plain mapping keeps the scaled wrapper pickleable even when
            # this script is executed as __main__.
            model = {'fitted': fitted, 'scale': scale}
        return model, len(y)
    direct = name == 'ridge_direct'
    width = horizon if direct else 1
    positions = range(30, len(values)-width+1)
    x = np.asarray([feature_row(values[:t], dates[t]) for t in positions])
    y = np.asarray([values[t:t+width] if direct else values[t] for t in positions])
    if not len(x):
        raise ValueError('Insufficient training rows after lag/horizon construction.')
    if name == 'legacy_refit':
        x = x[:, :6]
    model = estimator(name)
    model.fit(x, y)
    return model, len(x)


def predict_candidate(name, model, history, future_dates):
    history = list(np.asarray(history, dtype=float))
    if name in ('sarima_weekly', 'ets_weekly'):
        result = np.asarray(model['fitted'].forecast(len(future_dates))*model['scale']
                            if name == 'ets_weekly' else model.forecast(len(future_dates)), dtype=float)
        if result.shape != (len(future_dates),) or not np.isfinite(result).all():
            raise ValueError('Invalid prediction length or finite-value contract.')
        return result
    if name == 'ridge_direct':
        result = np.asarray(model.predict([feature_row(history, future_dates[0])])[0])
    else:
        result = []
        for day in future_dates:
            features = feature_row(history, day)
            row = [features[:6] if name == 'legacy_refit' else features]
            if hasattr(model, 'feature_names_in_'):
                row = pd.DataFrame(row, columns=model.feature_names_in_)
            prediction = float(model.predict(row)[0])
            result.append(prediction)
            history.append(prediction)
        result = np.asarray(result)
    if len(result) != len(future_dates) or not np.isfinite(result).all():
        raise ValueError('Invalid prediction length or finite-value contract.')
    return result  # Never clamp negative estimates.


def score(actual, predicted, scale):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    if not len(actual) or actual.shape != predicted.shape or not np.isfinite(predicted).all() or not np.isfinite(actual).all():
        raise ValueError(f'Aligned finite predictions required (actual={actual.shape}, predicted={predicted.shape}, '
                         f'actual_finite={np.isfinite(actual).all()}, predicted_finite={np.isfinite(predicted).all()}).')
    error = np.abs(actual-predicted)
    nonzero = actual != 0
    denominator = float(np.sum((actual-actual.mean())**2))
    return dict(mae=float(error.mean()), rmse=float(np.sqrt(((actual-predicted)**2).mean())),
                r2=float(1-np.sum((actual-predicted)**2)/denominator) if denominator else None,
                wape_pct=float(error.sum()/np.abs(actual).sum()*100) if np.abs(actual).sum() else None,
                mase=float(error.mean()/scale) if scale > 0 else None,
                mape_nonzero_pct=float((error[nonzero]/np.abs(actual[nonzero])).mean()*100) if nonzero.any() else None,
                mape_excluded_zeros=int((~nonzero).sum()), n=len(actual),
                negative_predictions=int((predicted < 0).sum()))


def candidate_config(name):
    if name in (*NAMES, 'legacy_refit'):
        return str(estimator(name).get_params(deep=False))
    return {
        'lightgbm_recursive': {'n_estimators': 120, 'num_leaves': 15, 'max_depth': 5,
            'learning_rate': .04, 'min_child_samples': 20, 'reg_lambda': 2,
            'random_state': SEED, 'n_jobs': 1, 'deterministic': True, 'force_col_wise': True},
        'sarima_weekly': {'order': (1, 0, 0), 'seasonal_order': (1, 0, 0, 7),
            'trend': 'c', 'enforce_stationarity': False, 'enforce_invertibility': False,
            'simple_differencing': True, 'optimizer': 'powell', 'maxiter': 50},
        'ets_weekly': {'trend': 'add', 'damped_trend': True, 'seasonal': 'add',
            'seasonal_periods': 7, 'initialization_method': 'estimated',
            'optimizer': 'statsmodels default', 'scale': 'mean absolute training target'},
    }.get(name, name)


def evaluate(frame, target, start, end, names, legacy=None):
    values = frame[target].to_numpy(dtype=float)
    dates = frame.date.to_numpy()
    result = {}
    cache = {}
    for horizon in HORIZONS:
        origins = list(range(start, end-horizon+1, horizon))
        scale = np.abs(values[7:start]-values[:start-7]).mean()
        actual, predictions = [], {name: [] for name in names}
        timings = {name: [] for name in names}
        per_origin = {name: [] for name in names}
        failures = {}
        windows = []
        for origin in origins:
            observed = values[origin:origin+horizon]
            actual.extend(observed)
            windows.append({'origin': str(frame.date.iloc[origin-1].date()),
                            'from': str(frame.date.iloc[origin].date()),
                            'to': str(frame.date.iloc[origin+horizon-1].date()),
                            'training_cutoff_index_exclusive': origin})
            for name in names:
                # A failed candidate is excluded for the remainder of this
                # horizon, while all other candidates continue at each origin.
                if name in failures:
                    continue
                try:
                    if name == 'last_value':
                        started = time.perf_counter()
                        prediction = np.repeat(values[origin-1], horizon)
                    elif name == 'seasonal_naive':
                        started = time.perf_counter()
                        prediction = np.resize(values[origin-7:origin], horizon)
                    elif name == 'legacy_frozen':
                        # Only used after its declared fit cutoff; fit provenance still unverified.
                        started = time.perf_counter()
                        prediction = predict_candidate('legacy_refit', legacy, values[:origin], dates[origin:origin+horizon])
                    else:
                        key = (name, origin, horizon if name == 'ridge_direct' else 1)
                        if key not in cache:
                            cache[key] = fit_candidate(name, values[:origin], dates[:origin], horizon)[0]
                        started = time.perf_counter()
                        prediction = predict_candidate(name, cache[key], values[:origin], dates[origin:origin+horizon])
                    if len(prediction) != horizon or not np.isfinite(prediction).all():
                        raise ValueError('Candidate returned invalid or non-finite predictions.')
                    timings[name].append(time.perf_counter()-started)
                    predictions[name].extend(prediction)
                    per_origin[name].append(float(np.abs(observed-prediction).mean()))
                except Exception as error:
                    failures[name] = f'{type(error).__name__}: {error}'
                    continue
        for name in failures:
            predictions.pop(name, None)
            timings.pop(name, None)
            per_origin.pop(name, None)
        result[str(horizon)] = {'horizon': horizon, 'windows': windows, 'origins': len(origins),
                                'points': len(actual), 'excluded_points': end-start-len(actual),
                                'origin_evidence_sufficient': len(origins) >= (3 if horizon >= 30 else 5),
                                'candidate_failures': failures,
                                'metrics': {name: {**score(actual, predicted, scale),
                                    'inference_time_seconds': float(sum(timings[name])),
                                    'origin_mae': per_origin[name],
                                    'origin_mae_std': float(np.std(per_origin[name]))}
                                    for name, predicted in predictions.items()},
                                'series': [dict(date=str(frame.date.iloc[t].date()), actual=float(actual[i]),
                                    **{name: float(prediction[i]) for name, prediction in predictions.items()})
                                    for i, t in enumerate(t for origin in origins for t in range(origin, origin+horizon))]}
    return result


def select_on_validation(validation):
    # legacy_refit recreates the documented production LinearRegression recipe
    # from the current series. It is deliberately distinguished from a missing
    # frozen production binary and must not be described as that binary.
    selection_names = (*ALL_NAMES, 'legacy_refit')
    eligible = [name for name in selection_names if all(
        validation[str(h)]['metrics'].get(name, {}).get('mae') is not None for h in PRIMARY)]
    if not eligible:
        raise ValueError('No candidate completed all primary validation horizons.')
    return min(eligible, key=lambda name: sum(
        validation[str(h)]['metrics'][name]['mae'] /
        max(1e-12, min(validation[str(h)]['metrics'][b]['mae'] for b in ('last_value', 'seasonal_naive')))
        for h in PRIMARY))


def quality_gate(validation, holdout, winner, provenance_verified=False, currency_verified=True):
    reasons = []
    for phase, results in [('validation', validation), ('holdout', holdout)]:
        for h in PRIMARY:
            row = results[str(h)]
            model = row['metrics'][winner]
            baseline_name = min(('last_value', 'seasonal_naive'), key=lambda b: row['metrics'][b]['mae'])
            baseline = row['metrics'][baseline_name]
            wins = np.mean(np.asarray(model['origin_mae']) < np.asarray(baseline['origin_mae']))
            if not row['origin_evidence_sufficient']: reasons.append(f'{phase} {h}d: insufficient origins')
            if model['mae'] > .95*baseline['mae']: reasons.append(f'{phase} {h}d: less than 5% MAE improvement')
            if model['rmse'] > 1.05*baseline['rmse']: reasons.append(f'{phase} {h}d: material RMSE regression')
            if wins < .6: reasons.append(f'{phase} {h}d: improvement unstable across origins')
            if model['negative_predictions']: reasons.append(f'{phase} {h}d: negative predictions require review')
    if not provenance_verified: reasons.append('Original real/synthetic provenance is not independently certified')
    if not currency_verified: reasons.append('Revenue training currency is not independently certified')
    return {'qualified': not reasons, 'reasons': reasons,
            'ninety_day_claim': 'Limited: one independent origin per phase; no general 90-day quality claim'}


def run(source, provenance, output, legacy_dir):
    output = Path(output).resolve()
    repo = Path(__file__).resolve().parents[3]
    if output.is_relative_to(repo):
        raise ValueError('Experiment output must be outside the source tree.')
    if Path(legacy_dir).resolve() != (repo/'ml/models').resolve():
        raise ValueError('Only the existing reviewed serving artifact directory is supported.')
    output.mkdir(exist_ok=False, parents=True)
    raw = Path(source).read_bytes()
    frame = validate_series(pd.read_csv(source))
    if len(frame) < 380:
        raise ValueError('Need at least 380 contiguous observations for this fixed protocol.')
    train_end, validation_end = len(frame)-180, len(frame)-90
    # The old production estimator can be rebuilt from the documented training
    # recipe, but this is a candidate artifact, not a byte-identical recovery.
    available = [*NAMES, 'legacy_refit']
    unavailable = {}
    if importlib.util.find_spec('lightgbm'):
        available.append('lightgbm_recursive')
    else:
        unavailable['lightgbm_recursive'] = 'LightGBM package is not installed; see ml/requirements-forecasting.txt.'
    if importlib.util.find_spec('statsmodels'):
        available.extend(('sarima_weekly', 'ets_weekly'))
    else:
        unavailable.update({name: 'statsmodels package is not installed.' for name in ('sarima_weekly', 'ets_weekly')})
    protocol = {'version': 1, 'run_id': output.name,
                'source_sha256': hashlib.sha256(raw).hexdigest(),
                'provenance': provenance, 'seed': SEED, 'features': FEATURES,
                'missing_dates': 'No filling; longest observed contiguous block chosen by coverage only',
                'selection': 'Minimum validation MAE/strongest-simple-baseline ratio summed over 7/14/30d',
                'gate': 'At least 5% MAE improvement at every primary horizon in validation and final holdout; RMSE regression <=5%; >=60% origin wins; provenance/units mandatory',
                'windows': 'Disjoint targets within each horizon; different horizons reuse dates and are not independent replications',
                'train': [str(frame.date.iloc[0].date()), str(frame.date.iloc[train_end-1].date()), train_end],
                'validation': [str(frame.date.iloc[train_end].date()), str(frame.date.iloc[validation_end-1].date()), 90],
                'holdout': [str(frame.date.iloc[validation_end].date()), str(frame.date.iloc[-1].date()), 90],
                'versions': {'python': platform.python_version(), 'sklearn': sklearn.__version__,
                             'numpy': np.__version__, 'pandas': pd.__version__, 'joblib': joblib.__version__,
                             **{package: package_version(package) for package in ('statsmodels', 'lightgbm')
                                if importlib.util.find_spec(package)}},
                'candidates': {name: {'status': 'available for evaluation' if name in available else 'unavailable',
                                      'reason': unavailable.get(name)} for name in ALL_NAMES},
                'recreated_baseline': {'name': 'legacy_refit',
                                       'status': 'available for evaluation',
                                       'identity': 'refit documented legacy LinearRegression recipe; not the missing production binary'},
                'configurations': {name: candidate_config(name) for name in available}}
    legacy_paths = {target: Path(legacy_dir)/f'sales_forecast_{target}.joblib'
                    for target in ('orders', 'revenue')}
    protocol['legacy_artifacts'] = {
        target: ({'status': 'present', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                 if path.is_file() else {'status': 'missing', 'sha256': None})
        for target, path in legacy_paths.items()}
    # Pre-register the protocol before fitting or scoring the reserved segment.
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2, default=str), encoding='utf-8')
    # Pipeline configuration includes estimator objects; store their explicit
    # repr as metadata, never executable Python in the JSON evaluation report.
    protocol = json.loads(json.dumps(protocol, default=str))
    results = {'protocol': protocol, 'targets': {}}
    for target in ('orders', 'revenue'):
        validation = evaluate(frame, target, train_end, validation_end,
                              ['last_value', 'seasonal_naive', *available])
        winner = select_on_validation(validation)
        (output/f'{target}-selection.json').write_text(json.dumps({'winner': winner, 'validation': validation}, indent=2), encoding='utf-8')
        # The frozen legacy artifact's declared cutoff is May 17, 2018. It is
        # excluded from earlier validation; refitted identical LR is scored there.
        if frame.date.iloc[validation_end] <= pd.Timestamp('2018-05-17', tz='UTC'):
            raise ValueError('Reserved window overlaps the frozen legacy declared fit span.')
        legacy_path = legacy_paths[target]
        frozen_legacy = None
        holdout_names = ['last_value', 'seasonal_naive', *available]
        if legacy_path.is_file():
            asset = joblib.load(legacy_path)
            if not isinstance(asset, dict) or asset.get('features') != list(LEGACY_FEATURES):
                raise ValueError(f'Legacy artifact schema mismatch: {legacy_path.name}')
            if 'model' not in asset:
                raise ValueError(f'Legacy artifact has no model: {legacy_path.name}')
            frozen_legacy = asset['model']
            holdout_names.append('legacy_frozen')
        holdout = evaluate(frame, target, validation_end, len(frame),
                           holdout_names, frozen_legacy)
        artifacts = []
        artifact_failures = {}
        for name in available:
            try:
                estimators, counts = {}, {}
                for h in (HORIZONS if name == 'ridge_direct' else (1,)):
                    model, count = fit_candidate(name, frame[target].to_numpy()[:validation_end],
                                                 frame.date.to_numpy()[:validation_end], h)
                    estimators[str(h)] = model
                    counts[str(h)] = count
                path = output/f'{target}-{name}-v1.joblib'
                joblib.dump({'candidate': name, 'target': target,
                             'features': LEGACY_FEATURES if name == 'legacy_refit' else FEATURES,
                             'estimators': estimators, 'frequency': 'daily',
                             'cutoff': str(frame.date.iloc[validation_end-1].date()),
                             'training_rows': counts, 'source_sha256': protocol['source_sha256']}, path)
                artifacts.append({'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'training_rows': counts})
            except Exception as error:
                artifact_failures[name] = f'{type(error).__name__}: {error}'
        results['targets'][target] = {'winner_selected_on_validation': winner,
            'validation': validation, 'holdout': holdout, 'artifacts': artifacts,
            'artifact_failures': artifact_failures,
            'qualification': quality_gate(validation, holdout, winner,
                provenance.get('independently_verified', False),
                target != 'revenue' or provenance.get('currency_independently_verified', False))}
        (output/'results.json').write_text(json.dumps(results, indent=2, allow_nan=False), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--provenance', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--legacy-models', type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        result = run(args.source, json.loads(args.provenance.read_text(encoding='utf-8')),
                     args.output, args.legacy_models)
    print(json.dumps({key: {'winner': value['winner_selected_on_validation'],
                           'qualification': value['qualification']}
                      for key, value in result['targets'].items()}, indent=2))
