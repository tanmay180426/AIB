"""Read-only replay of trusted saved artifacts, never fit/retrain or write data.

Legacy metadata fingerprints are partial hashes. Matching them and replaying
recorded scores supports reproducibility, not proof of original fit provenance.
"""
from hashlib import sha256
from functools import lru_cache
import numpy as np
import pandas as pd
from app.services import ml

SOURCES = {'sales_forecast_orders': 'daily_series.csv', 'sales_forecast_revenue': 'daily_series.csv',
           'anomaly_detection': 'daily_series.csv', 'customer_segmentation': 'customer_rfm.csv',
           'product_segmentation': 'product_features.csv', 'sales_prediction': 'orders_features.csv'}


def error_metrics(actual, predicted, scale=None):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.ndim != 1 or actual.shape != predicted.shape or not len(actual):
        raise ValueError('Aligned nonempty one-dimensional observations are required.')
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError('Evaluation contains non-finite observations.')
    errors = np.abs(actual-predicted)
    denominator = float(np.abs(actual).sum())
    nonzero = actual != 0
    return {'mae': round(float(errors.mean()), 4), 'rmse': round(float(np.sqrt(np.mean((actual-predicted)**2))), 4),
            'wape_pct': round(float(errors.sum())/denominator*100, 4) if denominator else None,
            'mase': round(float(errors.mean())/scale, 4) if scale is not None and scale > 0 else None,
            'mape_nonzero_pct': round(float(np.mean(errors[nonzero]/np.abs(actual[nonzero])))*100, 4) if nonzero.any() else None,
            'mape_excluded_zeros': int((~nonzero).sum()), 'n': len(actual)}


def recursive_values(model, features, history, horizon):
    """Same frozen-model recursion used by serving; future actuals never enter."""
    values = list(np.asarray(history, dtype=float))
    if len(values) < 30 or not np.isfinite(values).all() or min(values) < 0:
        raise ValueError('Forecast requires at least 30 finite nonnegative actual observations.')
    predictions = []
    for _ in range(horizon):
        row = {'lag1': values[-1], 'lag7': values[-7], 'lag14': values[-14], 'lag30': values[-30],
               'roll7': float(np.mean(values[-7:])), 'roll30': float(np.mean(values[-30:]))}
        prediction = float(model.predict(pd.DataFrame([[row[key] for key in features]], columns=features))[0])
        if not np.isfinite(prediction):
            raise ValueError('Model returned a non-finite prediction.')
        predictions.append(prediction); values.append(prediction)
    return predictions


def _forecast_replay(frame, meta, bundle):
    target = 'orders' if meta['name'].endswith('orders') else 'revenue'
    frame = frame.sort_values('date').reset_index(drop=True)
    dates = pd.to_datetime(frame['date'], utc=True)
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError('Training-source dates are invalid or duplicated.')
    values = frame[target].astype(float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError('Training-source target is invalid.')
    matrix = pd.DataFrame({'y': values})
    for lag in (1, 7, 14, 30): matrix[f'lag{lag}'] = values.shift(lag)
    matrix['roll7'] = values.shift(1).rolling(7).mean()
    matrix['roll30'] = values.shift(1).rolling(30).mean()
    matrix = matrix.dropna()
    n_train, n_test = meta['metrics']['n_train'], meta['metrics']['n_test']
    if n_train+n_test != len(matrix) or n_train != int(.8*len(matrix)) or not n_test:
        raise ValueError('Source does not reproduce the recorded chronological split sizes.')
    train, test = matrix.iloc[:n_train], matrix.iloc[n_train:]
    first = int(test.index[0])
    calendar = pd.Series(values.to_numpy(), index=dates).asfreq('D')
    train_calendar = calendar.loc[:dates[first-1]]
    scale = float(train_calendar.diff(7).abs().dropna().mean())
    if not np.isfinite(scale): scale = None
    one_step = error_metrics(test.y, bundle['model'].predict(test[bundle['features']]), scale)
    seasonal = error_metrics(test.y, test.lag7, scale)
    recorded = meta['metrics']['model']
    matches = all(abs(one_step[key]-recorded[key]) <= .0001 for key in ('mae', 'rmse'))
    windows = []
    for horizon in (7, 14, 30, 90):
        observed, predictions, naive, seasonal_predictions, origins, ends = [], [], [], [], [], []
        origin = first
        while origin+horizon <= len(frame):
            span = dates.iloc[origin-30:origin+horizon]
            if not span.diff().dropna().eq(pd.Timedelta(days=1)).all():
                origin += 1; continue
            history = values.iloc[:origin].tolist()
            predictions.extend(recursive_values(bundle['model'], bundle['features'], history, horizon))
            observed.extend(values.iloc[origin:origin+horizon])
            naive.extend([history[-1]]*horizon)
            repeated = history[-7:]
            seasonal_predictions.extend([repeated[i % 7] for i in range(horizon)])
            origins.append(dates.iloc[origin].date().isoformat())
            ends.append(dates.iloc[origin+horizon-1].date().isoformat())
            origin += horizon  # nonoverlapping forecast windows
        windows.append({'horizon': horizon, 'origins': len(origins), 'first_test_date': origins[0] if origins else None,
                        'last_test_date': ends[-1] if ends else None,
                        'excluded_test_observations': n_test-len(observed),
                        'model': error_metrics(observed, predictions, scale) if observed else None,
                        'last_value_baseline': error_metrics(observed, naive, scale) if observed else None,
                        'seasonal_naive_baseline': error_metrics(observed, seasonal_predictions, scale) if observed else None})
    return {'protocol': 'Frozen artifact replay; source-declared chronological 80/20. No fitting or model selection.',
            'declared_training_cutoff': dates.iloc[first-1].date().isoformat(),
            'evaluation_from': dates.iloc[first].date().isoformat(), 'evaluation_to': dates.iloc[-1].date().isoformat(),
            'n_train': len(train), 'n_test': len(test), 'recorded_mae_rmse_reproduced': matches,
            'legacy_one_step': one_step, 'legacy_observation_lag7_baseline': seasonal,
            'recursive_calendar_windows': windows,
            'limitations': ['Legacy lag/rolling features advance by observations, including across missing calendar dates.',
                           'One-step replay uses newly observed prior test values; it is not a 30-day recursive forecast score.',
                           'Recursive windows require complete 30-day history and future dates; gaps are never filled.',
                           'MASE scale uses observed seven-calendar-day differences in the declared training span only.',
                           'The declared cutoff is reconstructed, not an independently verified fit log. Dataset provenance is unverified.']}


def audit_model(name):
    """Explicit model-detail inspection, cached by source/artifact content hashes."""
    if name not in SOURCES:
        return {'status': 'unavailable', 'reason': 'No audited source mapping is registered.'}
    meta = ml.load_all_metadata().get(name, {})
    source = ml.processed_dir()/SOURCES[name]
    artifact = ml.models_dir()/meta.get('artifact', '')
    if not source.is_file() or not artifact.is_file():
        return {'status': 'unavailable', 'reason': 'Matching trusted processed source and saved artifact are required; no evaluation was fabricated.'}
    raw = source.read_bytes()
    fingerprint = sha256(source.name.encode()+str(len(raw)).encode()+raw[:65536]).hexdigest()[:16]
    if fingerprint != meta.get('dataset_fingerprint'):
        return {'status': 'unavailable', 'reason': 'Processed source does not match the registered legacy fingerprint.'}
    return _audit(str(source), name, sha256(raw).hexdigest(), sha256(artifact.read_bytes()).hexdigest(),
                  __import__('json').dumps(meta, sort_keys=True))


@lru_cache(maxsize=8)
def _audit(path, name, source_hash, artifact_hash, metadata):
    import json
    meta = json.loads(metadata)
    frame = pd.read_csv(path)
    result = {'status': 'replayed', 'source_sha256': source_hash, 'artifact_sha256': artifact_hash,
              'source_rows': len(frame), 'training_cutoff': None,
              'provenance': 'Legacy partial fingerprint matched; original fit log and real/synthetic composition are not verified.',
              'features': meta.get('features_schema'), 'version': meta.get('version')}
    try:
        bundle = ml._load_artifact(name)
        if 'date' in frame:
            dates = pd.to_datetime(frame.date, errors='coerce', utc=True)
            result['date_profile'] = {'from': str(dates.min().date()), 'to': str(dates.max().date()),
                                      'duplicate_dates': int(dates.duplicated().sum()),
                                      'missing_calendar_days': len(pd.date_range(dates.min(), dates.max()).difference(dates))}
        if name.startswith('sales_forecast_'):
            result['evaluation'] = _forecast_replay(frame, meta, bundle)
        elif name == 'sales_prediction':
            from sklearn.model_selection import train_test_split
            frame = frame.dropna(subset=['item_revenue'])
            rows = frame[bundle['features']].copy()
            rows[['customer_state', 'product_category_name']] = rows[['customer_state', 'product_category_name']].fillna('unknown')
            _, test, _, actual = train_test_split(rows, frame.item_revenue, test_size=.2, random_state=42)
            result['evaluation'] = {'protocol': 'Source-declared random 80/20, seed 42; saved selected pipeline, no refit.',
                                    'metrics': error_metrics(actual, bundle['pipeline'].predict(test)),
                                    'limitations': ['Not temporal forecasting validation. The same test split selected the winning candidate; no independent final test is documented.',
                                                   'Random Forest candidate scores are historical metadata; its separate artifact is not retained.']}
        elif name == 'anomaly_detection':
            inputs = frame[bundle['features']].astype(float)
            labels = bundle['model'].predict(inputs)
            result['evaluation'] = {'protocol': 'Unsupervised training-source replay, no fraud labels or holdout accuracy.',
                                    'n_days': len(frame), 'flagged_days': int((labels == -1).sum()),
                                    'contamination': bundle.get('contamination'),
                                    'limitations': ['Decision scores are not probabilities. No validated feature attribution or supervised detection quality is available.']}
        else:
            if name == 'customer_segmentation': frame['monetary_log'] = np.log1p(frame.monetary.clip(lower=0))
            else:
                frame['qty_log'] = np.log1p(frame.total_qty.clip(lower=0))
                frame['revenue_log'] = np.log1p(frame.total_revenue.clip(lower=0))
                # Reconstruct the documented training-source medians for audit
                # only; never use these current-source statistics for serving.
                for column in ('product_weight_g', 'avg_price'): frame[column] = frame[column].fillna(frame[column].median())
            labels = bundle['model'].predict(bundle['scaler'].transform(frame[bundle['features']].astype(float)))
            counts = pd.Series(labels).value_counts().sort_index()
            result['evaluation'] = {'protocol': 'Saved scaler/KMeans training-source assignment replay; no clustering refit.',
                                    'cluster_counts': {str(int(key)): int(value) for key, value in counts.items()},
                                    'limitations': ['Recorded silhouette selected k on the same data/sample; it is not external accuracy. Stability and transfer quality are unverified.']}
    except (ValueError, KeyError, FileNotFoundError) as error:
        return {**result, 'status': 'unavailable', 'reason': str(error)}
    return result
