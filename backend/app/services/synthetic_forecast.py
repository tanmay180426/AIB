"""Explicit local registration for dataset-bound synthetic forecast previews.

Only offline-generated, checksum-verified artifacts from an operator configured
registry are loaded. Ordinary requests never train, register or mutate data.
"""
import hashlib
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.models.dataset import Dataset, DatasetBundleTable
from app.services.synthetic_features import FEATURES, recursive

PREDICTION_LOCK = threading.Lock()
ALGORITHM_LABELS = {'ridge':'Ridge regression with fitted standard scaler',
                    'forest':'Random Forest regression', 'boost':'Histogram Gradient Boosting regression'}


def _series(db, filters):
    from app.analytics import metrics
    # Request/session-local only: compatibility and inference reconcile against
    # one bounded aggregation, without caching across datasets or sessions.
    info = getattr(db, 'info', None)
    if info is None:
        return metrics.time_series(db, filters, 'day', limit=100_000)
    ds = info.get('dataset')
    key = str((getattr(ds,'id',None),getattr(ds,'updated_at',None),getattr(ds,'owner',None)))+':'+json.dumps(filters.as_dict(), sort_keys=True)
    cache = info.setdefault('synthetic_daily_series', {})
    if key not in cache:
        cache[key] = metrics.time_series(db, filters, 'day', limit=100_000)
    return cache[key]


def registry():
    path = os.getenv('ML_SYNTHETIC_REGISTRY')
    if not path:
        return None
    try:
        file = Path(path).resolve()
        if file.stat().st_size > 200_000: return None
        value = json.loads(file.read_text(encoding='utf-8'))
        if value.get('version') != 'synthetic-v1' or value.get('features') != FEATURES:
            return None
        if not isinstance(value.get('datasets'), dict) or not all(
            isinstance(value.get('models',{}).get(target),dict) and
            {'artifact','artifact_sha256','unit','quality','evaluation','name','version','algorithm','training_cutoff'} <= value['models'][target].keys()
            for target in ('orders','revenue')):
            return None
        value['_directory'] = file.parent
        return value
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return None


def _members(db, ident):
    members = db.execute(select(Dataset.id, Dataset.row_count, Dataset.updated_at).join(
        DatasetBundleTable, Dataset.id == DatasetBundleTable.dataset_id).where(
        DatasetBundleTable.bundle_id == ident)).all()
    return {key: {'rows': rows, 'updated_at': str(updated)} for key, rows, updated in members}


def binding(db):
    value = registry()
    ds = db.info['dataset']
    if not value or ds.source_type != 'bundle': return None
    contract = value.get('datasets', {}).get(ds.id)
    if not contract: return None
    # Bind immutable imported members and revisions, never a display name.
    current = _members(db, ds.id)
    if current != contract.get('members'):
        return {'invalid': 'Registered synthetic source changed. Repeat the explicit source audit and offline registration.'}
    return value


def registered_scopes(db, username):
    """Discover only this user's already registered, unchanged bundle scopes.

    No selection mutation, fuzzy name matching, re-registration or model load.
    """
    value = registry()
    if not value: return {'status':'not_configured','datasets':[]}
    ds = db.info['dataset']; scopes = []
    candidates = db.scalars(select(Dataset).where(Dataset.id.in_(list(value['datasets'])),
        Dataset.source_type == 'bundle', Dataset.status == 'READY',
        (Dataset.owner == username) | Dataset.owner.is_(None))).all()
    for candidate in candidates:
        if _members(db,candidate.id) == value['datasets'][candidate.id].get('members'):
            scopes.append({'dataset_id':candidate.id,'dataset_name':candidate.name,'table':'Bundle overview'})
    matches = any(scope['dataset_id'] == ds.id for scope in scopes)
    return {'status':'matches' if matches else 'revision_mismatch' if ds.id in value['datasets'] else 'different_dataset',
            'datasets':scopes}


def chart_history(db, filters, target):
    """Complete authorized daily display aggregates, separate from lag inputs.

    An absent date is an explicit null, never observed zero or imputed input.
    Query and calendar are bounded; request-local aggregation is reused.
    """
    points = _series(db,filters)
    by_date = {}
    for point in points:
        day = date.fromisoformat(point['period'])
        if day.isoformat() != point['period'] or day in by_date:
            raise ValueError('Historical aggregate contains invalid or duplicate daily dates.')
        value = point.get(target)
        if value is not None and (not isinstance(value,(int,float,np.number)) or not np.isfinite(value) or value < 0):
            raise ValueError('Historical aggregate contains an invalid target value.')
        by_date[day] = value
    if not by_date:
        return {'historical_series':[], 'historical_coverage':None}
    first,last = min(by_date),max(by_date)
    length = (last-first).days+1
    if length > 100_000: raise ValueError('Historical daily timeline exceeds the supported bound.')
    history = [{'date':(first+timedelta(days=i)).isoformat(),target:by_date.get(first+timedelta(days=i))} for i in range(length)]
    return {'historical_series':history,'historical_coverage':{'from':first.isoformat(),'to':last.isoformat(),
        'calendar_positions':length,'recorded_days':len(by_date),'missing_dates':length-len(by_date),
        'unknown_target_days':sum(v is None for v in by_date.values()),
        'missing_target_positions':sum(p[target] is None for p in history),'zero_filled':0},
        'history_description':'Recorded selected-scope daily aggregates. Unknown dates/targets remain null; coverage completeness is unconfirmed.'}


def selected_evidence(db, target):
    value = binding(db)
    if not value: return None
    if value.get('invalid'): return {'status':'blocked', 'reason':value['invalid']}
    model = value['models'][target]
    return {k:model[k] for k in ('name','version','algorithm','unit','quality','evaluation','training_cutoff')} | {
        'status':'synthetic_demo', 'provenance':'Synthetic/extended source; individual real/synthetic origins and generator unavailable.',
        'algorithm_label':ALGORITHM_LABELS.get(model['algorithm'],model['algorithm']),
        'coverage':value['coverage'], 'missing_policy':value['missing_policy'],
        'historical_mode':'If origin precedes final fitting cutoff, this is a fitted historical demonstration, not independent validation.'}


@lru_cache(maxsize=4)
def _artifact(path, expected_hash):
    file = Path(path)
    if file.stat().st_size > 10_000_000 or hashlib.sha256(file.read_bytes()).hexdigest() != expected_hash:
        raise ValueError('Synthetic model checksum mismatch.')
    import joblib
    value = joblib.load(file)  # Only newly trained, locally reviewed registration.
    if value.get('features') != FEATURES or value.get('version') != 'synthetic-v1':
        raise ValueError('Synthetic model preprocessing schema mismatch.')
    if not hasattr(value.get('model'),'predict'):
        raise ValueError('Synthetic estimator is unavailable.')
    return value['model']


def compatibility(db, filters, target):
    value = binding(db)
    if not value: return None
    if value.get('invalid'): return {'compatible':False,'reasons':[value['invalid']]}
    points = _series(db, filters)
    reasons=[]
    tail=points[-30:]
    if len(tail)<30:
        reasons.append('Synthetic preview requires 30 observed daily values after the selected filters.')
    else:
        dates=pd.to_datetime([p['period'] for p in tail],utc=True,errors='coerce')
        values=np.asarray([p.get(target) for p in tail],dtype=float)
        if dates.isna().any() or not np.all(np.diff(dates.asi8)==86400_000_000_000):
            known = set(dates.dropna().date)
            missing = [d.date().isoformat() for d in pd.date_range(dates.min(),dates.max(),freq='D') if d.date() not in known]
            reasons.append('Latest synthetic history has unknown missing dates'+(': '+', '.join(missing[:5])+(' …' if len(missing)>5 else '') if missing else '')+'. No date was filled with zero.')
        if not np.isfinite(values).all() or (values<0).any():
            bad = [p['period'] for p,v in zip(tail,values) if not np.isfinite(v) or v<0]
            reasons.append('Latest synthetic target contains unknown or invalid values on '+', '.join(bad[:5])+'. Missing revenue is never zero-filled.')
    return {'compatible':not reasons,'reasons':reasons,'contract':{
        'domain':'synthetic/extended registered dataset only','frequency':'daily','target':target,
        'unit':value['models'][target]['unit'],'minimum_observations':30},
        'quality_scope':'Synthetic source evaluation, not real-world accuracy.'}


def forecast(db, filters, target, periods):
    if target not in ('orders','revenue') or not 1 <= periods <= 366:
        raise ValueError('Forecast horizon must be between 1 and 366 daily predictions.')
    value = binding(db)
    if not value or value.get('invalid'): raise ValueError('No matching synthetic registration.')
    check = compatibility(db, filters, target)
    if not check['compatible']: raise ValueError(' '.join(check['reasons']))
    points = _series(db, filters)
    tail=points[-30:]; model=value['models'][target]
    filename=model['artifact']
    if Path(filename).name != filename: raise ValueError('Invalid artifact filename.')
    estimator=_artifact(str(value['_directory']/filename),model['artifact_sha256'])
    origin=pd.Timestamp(tail[-1]['period']); dates=pd.date_range(origin+pd.Timedelta(days=1),periods=periods,freq='D')
    from threadpoolctl import threadpool_limits
    # Tiny recursive batches should not spawn every native CPU thread. The
    # lock also makes restoration of process-wide native limits deterministic.
    with PREDICTION_LOCK, threadpool_limits(limits=1):
        predicted=recursive(estimator,[p[target] for p in tail],dates)
    return {'history_tail':[{'date':p['period'],target:p[target]} for p in tail],
        'forecast':[{'date':str(d.date()),target:round(v,2)} for d,v in zip(dates,predicted)],
        'forecast_origin':str(origin.date()),'horizon':periods,'frequency':'daily','unit':model['unit'],
        'target_definition':'Daily distinct matching orders' if target=='orders' else 'Qualifying item price sum excluding freight and payments; source revenue units — currency unconfirmed',
        'data_coverage':{'from':points[0]['period'],'to':points[-1]['period'],'observed_days':len(points)},
        'model':{k:model[k] for k in ('name','version')} | {'algorithm':ALGORITHM_LABELS.get(model['algorithm'],model['algorithm'])},
        'synthetic':True,'quality':model['quality'],'training_cutoff':model['training_cutoff'],
        'evaluation_status':'Synthetic-demo evaluation only; selected filtered-scope and real-world accuracy are unqualified.',
        'warnings':['Experimental synthetic-data forecast. It is not independently validated real-world Olist performance.',
            'Unknown historical gaps remain missing; only the latest complete 30-day window enters inference.',
            'The model was refitted through '+model['training_cutoff']+'. Earlier origins overlap fitted history and are not independent backtests.',
            'Dimension-filtered subsets may have a different scale from training; inspect offline quality before business use. No calibrated intervals.']}
