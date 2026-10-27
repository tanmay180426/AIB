"""Offline synthetic/extended forecasting; no filling or serving-file writes."""
import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'backend'))
from app.services.synthetic_features import FEATURES, features, recursive
sys.path.insert(0, str(ROOT/'ml'))
from src.forecasting.evaluate_candidates import score

NAMES = ('ridge', 'forest', 'boost')
HORIZONS = (7, 14, 30, 90)


def prepare(frame):
    frame = frame.copy()
    frame['date'] = pd.to_datetime(frame['date'], utc=True, errors='raise')
    if frame.date.isna().any() or frame.date.duplicated().any():
        raise ValueError('Unique event dates required.')
    for target in ('orders', 'revenue'):
        frame[target] = pd.to_numeric(frame[target], errors='raise')
        known = frame[target].dropna()
        if not np.isfinite(known).all() or (known < 0).any():
            raise ValueError('Invalid observed targets.')
    # Reindexing creates explicit UNKNOWN dates, never observed zeroes.
    return frame.set_index('date').sort_index().reindex(
        pd.date_range(frame.date.min(), frame.date.max(), freq='D')).rename_axis('date').reset_index()


def estimator(name):
    if name == 'ridge': return make_pipeline(StandardScaler(), Ridge(alpha=100.0))
    if name == 'forest': return RandomForestRegressor(n_estimators=48, max_depth=7, min_samples_leaf=8, random_state=42, n_jobs=1)
    if name == 'boost': return HistGradientBoostingRegressor(max_iter=80, max_leaf_nodes=7, learning_rate=.05, l2_regularization=5, early_stopping=False, random_state=42)
    raise ValueError('Unknown candidate.')


def fit(name, values, dates):
    positions = [i for i in range(30, len(values)) if np.isfinite(values[i-30:i+1]).all()]
    if len(positions) < 180: raise ValueError('At least 180 valid past-only supervised rows required.')
    model = estimator(name)
    model.fit(np.asarray([features(values[i-30:i], dates[i]) for i in positions]), values[positions])
    return model, len(positions), len(values)-30-len(positions)


def evaluate(frame, target, start, end, names):
    values = frame[target].to_numpy(float); dates = frame.date.to_numpy()
    scale_pairs = np.abs(values[7:start]-values[:start-7]); scale = float(np.nanmean(scale_pairs))
    cache = {}; result = {}
    for horizon in HORIZONS:
        stride = 28 if horizon in (7, 14) else horizon
        origins = list(range(start, end-horizon+1, stride))
        predictions = {name:[] for name in names}; actual=[]; per_origin={name:[] for name in names}; windows=[]; excluded=[]
        for origin in origins:
            if not np.isfinite(values[origin-30:origin+horizon]).all():
                excluded.append(str(frame.date.iloc[origin].date())); continue
            truth = values[origin:origin+horizon]; actual.extend(truth)
            windows.append({'origin':str(frame.date.iloc[origin-1].date()), 'from':str(frame.date.iloc[origin].date()), 'to':str(frame.date.iloc[origin+horizon-1].date())})
            for name in names:
                if name == 'last_value': prediction = np.repeat(values[origin-1], horizon)
                elif name == 'seasonal_naive': prediction = np.resize(values[origin-7:origin], horizon)
                else:
                    key=(name,origin)
                    if key not in cache: cache[key]=fit(name,values[:origin],dates[:origin])[0]
                    prediction=np.asarray(recursive(cache[key],values[origin-30:origin],dates[origin:origin+horizon]))
                predictions[name].extend(prediction)
                per_origin[name].append(float(np.abs(truth-prediction).mean()))
        metrics={name:{**score(actual,pred,scale),'origin_mae':per_origin[name], 'origin_mae_std':float(np.std(per_origin[name]))} for name,pred in predictions.items()}
        result[str(horizon)]={'origins':len(windows),'points':len(actual),'windows':windows,'excluded_origins':excluded,'unscored_days':end-start-len(actual),'metrics':metrics}
    return result


def gate(validation, holdout, winner):
    failures=[]
    for phase,rows in [('validation',validation),('holdout',holdout)]:
        for h in HORIZONS:
            row=rows[str(h)];m=row['metrics'][winner]
            base=min(('last_value','seasonal_naive'),key=lambda x:row['metrics'][x]['mae']);b=row['metrics'][base]
            if row['origins'] < 3: failures.append(f'{phase} {h}d: insufficient origins')
            if m['mae'] > .95*b['mae']: failures.append(f'{phase} {h}d: less than 5% MAE improvement')
            if m['rmse'] > 1.05*b['rmse']: failures.append(f'{phase} {h}d: RMSE regression above 5%')
            if np.mean(np.asarray(m['origin_mae'])<np.asarray(b['origin_mae'])) < .6: failures.append(f'{phase} {h}d: fewer than 60% origin wins')
            if m['negative_predictions']: failures.append(f'{phase} {h}d: negative output')
    return {'qualified_synthetic_demo':not failures,'real_world_qualified':False,'reasons':failures,
            'provenance':'Synthetic/extended owner-supplied history; generator and per-row origins unavailable. Scores describe this source only.'}


def run(source, manifest, output):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT): raise ValueError('Output must be outside the repository.')
    output.mkdir(parents=True,exist_ok=False)
    frame=prepare(pd.read_csv(source))
    if (frame.date.max()-frame.date.min()).days < 5*365: raise ValueError('The intended extended five-year source is required.')
    train_end=int((frame.date < pd.Timestamp('2020-01-01',tz='UTC')).sum())
    validation_end=int((frame.date < pd.Timestamp('2021-01-01',tz='UTC')).sum())
    if train_end < 800 or validation_end-train_end < 360 or len(frame)-validation_end < 360: raise ValueError('Fixed chronological split requires 2020 validation and 2021 holdout.')
    protocol={'version':'synthetic-v1','created_at':datetime.now(timezone.utc).isoformat(),'source_sha256':hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        'features':FEATURES,'coverage':[str(frame.date.iloc[0].date()),str(frame.date.iloc[-1].date())],
        'train':[str(frame.date.iloc[0].date()),str(frame.date.iloc[train_end-1].date()),train_end],
        'validation':['2020-01-01','2020-12-31',validation_end-train_end],
        'holdout':['2021-01-01',str(frame.date.iloc[-1].date()),len(frame)-validation_end],
        'missing_policy':'Unknown dates remain NaN; supervised windows need 30 consecutive past values and an observed target. No zero filling.',
        'selection':'Minimum summed MAE / stronger naive MAE over 7/14/30-day validation; final holdout never selects hyperparameters.',
        'gate':'At least 5% MAE improvement, at most 5% RMSE regression, >=60% origin wins and >=3 origins at every supported horizon in both phases. Synthetic quality only.',
        'versions':{'python':platform.python_version(),'sklearn':sklearn.__version__,'numpy':np.__version__,'pandas':pd.__version__,'joblib':joblib.__version__},
        'configurations':{n:repr(estimator(n)) for n in NAMES},'source_manifest':manifest}
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    result={'protocol':protocol,'targets':{}}
    for target in ('orders','revenue'):
        validation=evaluate(frame,target,train_end,validation_end,['last_value','seasonal_naive',*NAMES])
        winner=min(NAMES,key=lambda n:sum(validation[str(h)]['metrics'][n]['mae']/max(1e-12,min(validation[str(h)]['metrics'][b]['mae'] for b in ('last_value','seasonal_naive'))) for h in (7,14,30)))
        (output/f'{target}-selection.json').write_text(json.dumps({'winner':winner,'validation':validation},indent=2))
        holdout=evaluate(frame,target,validation_end,len(frame),['last_value','seasonal_naive',winner])
        qualification=gate(validation,holdout,winner)
        model,rows,excluded=fit(winner,frame[target].to_numpy(float),frame.date.to_numpy())
        artifact=output/f'synthetic-{target}-v1.joblib'
        joblib.dump({'model':model,'features':FEATURES,'target':target,'version':'synthetic-v1','algorithm':winner},artifact)
        result['targets'][target]={'winner':winner,'validation':validation,'holdout':holdout,'qualification':qualification,
            'artifact':artifact.name,'artifact_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
            'final_fit_observations':len(frame),'final_supervised_rows':rows,'excluded_supervised_windows':excluded,
            'refit_policy':'After frozen final evaluation, only the validation-selected configuration was refitted through source end for explicit synthetic preview.'}
        (output/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with threadpool_limits(limits=1): result=run(args.source,json.loads(args.manifest.read_text()),args.output)
    print(json.dumps({t:{'winner':v['winner'],'qualification':v['qualification']} for t,v in result['targets'].items()},indent=2))
