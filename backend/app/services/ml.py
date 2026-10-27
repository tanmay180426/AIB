"""ML model registry + serving layer.

Reads model metadata written by the ml/ training scripts and lazily loads
joblib artifacts to serve predictions. All numbers come from real training runs.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

FEATURE_GROUPS: dict[str, list[str]] = {
    "sales_forecast": ["sales_forecast_orders", "sales_forecast_revenue"],
    "sales_prediction": ["sales_prediction"],
    "customer_segmentation": ["customer_segmentation"],
    "product_segmentation": ["product_segmentation"],
    "anomaly_detection": ["anomaly_detection"],
}


def models_dir() -> Path:
    env = os.getenv("ML_MODELS_DIR")
    return Path(env) if env else REPO_ROOT / "ml" / "models"


def processed_dir() -> Path:
    env = os.getenv("ML_DATA_DIR")
    return Path(env) if env else REPO_ROOT / "ml" / "data" / "processed"


@lru_cache(maxsize=1)
def load_all_metadata() -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = models_dir()
    if not d.exists():
        return out
    for path in d.glob("*.metadata.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out[path.name.replace(".metadata.json", "")] = data
        except (json.JSONDecodeError, OSError):
            continue
    return out


def artifact_available(name: str) -> bool:
    meta = load_all_metadata().get(name)
    if not meta or not meta.get("artifact"):
        return False
    return (models_dir() / meta["artifact"]).exists()


def feature_status() -> list[dict]:
    metas = load_all_metadata()
    features = []
    for feature, keys in FEATURE_GROUPS.items():
        present = [k for k in keys if k in metas]
        if not present:
            features.append({"name": feature, "status": "planned", "models": []})
            continue
        statuses = [metas[k].get("status", "planned") for k in present]
        all_available = all(s == "available" for s in statuses)
        runtime = {}
        for key in present:
            try:
                asset = _load_artifact(key)
                expected = 'pipeline' if key == 'sales_prediction' else 'model'
                if not isinstance(asset, dict) or not hasattr(asset.get(expected), 'predict') or not asset.get('features'):
                    raise ValueError('Invalid serving bundle.')
                if asset['features'] != metas[key].get('features_schema'):
                    raise ValueError('Artifact feature order does not match its registered schema.')
                if key in {'customer_segmentation','product_segmentation'} and not hasattr(asset.get('scaler'),'transform'):
                    raise ValueError('Required trained preprocessing scaler is missing.')
                runtime[key] = {'ready':True,'reason':None}
            except FileNotFoundError:
                runtime[key] = {'ready':False,'reason':'Trusted trained artifact is missing at the configured model directory.'}
            except Exception:
                runtime[key] = {'ready':False,'reason':'Artifact exists but its loader or serving contract failed. Check package versions and trusted artifact format.'}
        artifacts_ready = all(runtime[k]['ready'] for k in present)
        if all_available and artifacts_ready:
            status = "available"
        elif all_available:
            status = "integration"  # trained + documented, artifact not present locally
        else:
            status = statuses[0]
        features.append(
            {
                "name": feature,
                "status": status,
                "models": [
                    {
                        "name": k,
                        "algorithm": metas[k].get("algorithm"),
                        "trained_at": metas[k].get("trained_at"),
                        "metrics": metas[k].get("metrics"),
                        "artifact_available": artifact_available(k),
                        "runtime_ready": runtime[k]['ready'],
                        "runtime_reason": runtime[k]['reason'],
                        "version": metas[k].get('version'),
                    }
                    for k in present
                ],
            }
        )
    return features


@lru_cache(maxsize=8)
def _load_artifact(name: str):
    import joblib

    meta = load_all_metadata().get(name)
    if not meta or not meta.get("artifact"):
        raise FileNotFoundError(f"no artifact metadata for {name}")
    path = models_dir() / meta["artifact"]
    if Path(meta['artifact']).name != meta['artifact']:
        raise ValueError('Artifact must be a trusted model-directory filename.')
    if not path.exists():
        raise FileNotFoundError(f"artifact missing: {path}")
    return joblib.load(path)


def forecast(periods: int = 30, target: str = "orders", db=None, f=None) -> dict:
    """Recursive daily forecast using lag/rolling features."""
    import numpy as np
    import pandas as pd

    if target not in {"orders", "revenue"} or not 1 <= periods <= 366:
        raise ValueError("Invalid forecast target or horizon.")
    if db is None:
        raise ValueError("Dataset context is required for inference.")
    from app.analytics import metrics
    from app.analytics.filters import Filters
    points = metrics.time_series(db, f or Filters(), "day", limit=100_000)
    if len(points) < 30:
        raise ValueError("Forecasting requires at least 30 daily observations.")
    series = pd.DataFrame(points).rename(columns={"period": "date"})
    series["date"] = pd.to_datetime(series["date"])
    series = series.sort_values("date")
    hist = series.set_index("date")[target].astype(float).copy()
    dates = hist.index[-30:]
    if hist.index.has_duplicates or not ((dates[1:] - dates[:-1]).days == 1).all():
        raise ValueError("Forecast history must contain consecutive daily observations.")
    if not np.isfinite(hist.to_numpy()).all():
        raise ValueError("Forecast history contains non-finite values.")
    bundle = _load_artifact(f"sales_forecast_{target}")
    model, feature_cols = bundle["model"], bundle["features"]
    last_date = hist.index.max()
    values = list(hist.values)

    from app.services.model_audit import recursive_values
    predictions = recursive_values(model, feature_cols, values, periods)
    preds = [{"date": (last_date + pd.Timedelta(days=step + 1)).strftime("%Y-%m-%d"), target: round(value, 2)}
             for step, value in enumerate(predictions)]
    meta = load_all_metadata().get(f'sales_forecast_{target}', {})
    return {"history_tail": [{"date": d.strftime("%Y-%m-%d"), target: float(v)} for d, v in list(hist.items())[-30:]],
            "forecast": preds, "forecast_origin": last_date.strftime('%Y-%m-%d'),
            "horizon": periods, "frequency": "daily",
            "data_coverage": {"from": hist.index.min().strftime('%Y-%m-%d'),
                              "to": last_date.strftime('%Y-%m-%d'), "observed_days": len(hist)},
            "evaluation_status": "Selected-dataset forecast quality is unqualified; inspect separate offline evidence.",
            "target_definition": 'Daily distinct matching orders' if target == 'orders' else 'Daily qualifying item revenue, excluding freight',
            "unit": 'orders' if target == 'orders' else db.info['dataset'].semantics.get('currency_code'),
            "model": {"name": meta.get('name'), "version": meta.get('version'), "algorithm": meta.get('algorithm')},
            "training_cutoff": None,
            "warnings": ['Original fit cutoff is not persisted; inspect the model audit for reconstructed offline evaluation.',
                         'Offline one-step scores do not establish multi-day or selected-dataset accuracy. No calibrated interval is available.']}


def anomalies(db=None, f=None) -> dict:
    if db is not None:
        import pandas as pd
        from app.analytics import metrics
        from app.analytics.filters import Filters
        points = metrics.time_series(db, f or Filters(), "day", limit=100_000)
        frame = pd.DataFrame(points)
        bundle = _load_artifact("anomaly_detection")
        features = frame[bundle["features"]].astype(float)
        frame["anomaly"] = bundle["model"].predict(features)
        frame["score"] = bundle["model"].decision_function(features)
        selected = frame[frame.anomaly == -1].sort_values("score")
        return {"status": "available", "n_days": len(frame), "n_anomalies": len(selected),
                "anomalies": selected.rename(columns={"period": "date"}).head(100).to_dict("records")}
    meta = load_all_metadata().get("anomaly_detection", {})
    return {"metrics": meta.get("metrics", {}), "status": meta.get("status", "planned")}


def customer_segments(db=None, f=None) -> dict:
    if db is not None:
        import numpy as np
        import pandas as pd
        from sqlalchemy import func, select
        from app.analytics.filters import order_from, order_where, order_monetary_scope, Filters
        from app.analytics.tabular import TabularSource
        from sqlalchemy import text
        ds = db.info["dataset"]
        f = f or Filters()
        if getattr(ds,'source_type',None) == 'bundle':
            from app.analytics.bundle import BundleSource
            source = BundleSource(db,f)
            customer=source.customer; order=source.oc['order_id']; date=source.oc['order_purchase_timestamp']; amount=source.amount
            rows=source.rows(source.statement(customer.label('customer'),func.max(date).label('last_purchase'),func.count(func.distinct(order)).label('frequency'),func.sum(amount).label('monetary')).where(customer.is_not(None),date.is_not(None),amount.is_not(None)).group_by(customer))
        elif ds.adapter == "tabular":
            source = TabularSource(db, f)
            customer, order, date, amount = (source.field(r) for r in ("customer", "order", "date", "revenue"))
            rows = source.rows(source.statement(customer.label("customer"), func.max(date).label("last_purchase"),
                                                func.count(func.distinct(order)).label("frequency"), func.sum(amount).label("monetary"))
                               .where(customer.is_not(None)).group_by(customer))
        else:
            where, params = order_where(f)
            source, amount = order_monetary_scope(f)
            rows = [dict(r) for r in db.execute(text(f"SELECT o.customer_unique_id AS customer, MAX(o.purchase_date) AS last_purchase, "
                f"COUNT(DISTINCT o.order_id) AS frequency, COALESCE(SUM({amount}), 0) AS monetary FROM {source} WHERE {where} "
                "AND o.purchase_date IS NOT NULL AND o.customer_unique_id IS NOT NULL "
                "GROUP BY o.customer_unique_id"), params).mappings()]
        frame = pd.DataFrame(rows)
        dates = pd.to_datetime(frame.last_purchase, utc=True)
        frame["recency_days"] = ((dates.max() + pd.Timedelta(days=1)) - dates).dt.days
        frame["monetary_log"] = np.log1p(frame.monetary.clip(lower=0))
        bundle = _load_artifact("customer_segmentation")
        frame["segment"] = bundle["model"].predict(bundle["scaler"].transform(frame[bundle["features"]].astype(float)))
        return {"status": "available", "segments": frame.groupby("segment").agg(customers=("customer", "count"),
                    monetary=("monetary", "sum")).reset_index().to_dict("records")}
    meta = load_all_metadata().get("customer_segmentation", {})
    return {"metrics": meta.get("metrics", {}), "status": meta.get("status", "planned")}


def product_segments(db, f) -> dict:
    import pandas as pd
    import numpy as np
    from app.analytics.filters import item_where, item_from

    bundle = _load_artifact("product_segmentation")
    model = bundle["model"]
    scaler = bundle["scaler"]
    features = bundle["features"]

    ds = db.info.get("dataset")
    if ds is not None and getattr(ds,'source_type',None) == 'bundle':
        from app.analytics.bundle import BundleSource
        from sqlalchemy import func
        source=BundleSource(db,f)
        ic,pc=source.ic,source.pc
        df=pd.DataFrame(source.rows(source.item_statement(ic['product_id'].label('product'),func.min(pc['product_category_name']).label('category'),func.count().label('total_qty'),func.sum(ic['price']).label('total_revenue'),func.avg(ic['price']).label('avg_price'),func.avg(pc['product_weight_g']).label('product_weight_g')).group_by(ic['product_id'])))
    elif ds is not None and ds.adapter == "tabular":
        from app.analytics.tabular import TabularSource
        from sqlalchemy import func
        source = TabularSource(db, f)
        product, quantity, revenue, price, weight = (source.field(r) for r in ("product", "quantity", "revenue", "price", "weight_g"))
        category = source.field("category")
        columns = [product.label("product"), func.sum(quantity).label("total_qty"), func.sum(revenue).label("total_revenue"),
                   func.avg(price).label("avg_price"), func.avg(weight).label("product_weight_g")]
        if category is not None:
            columns.append(func.min(category).label("category"))
        df = pd.DataFrame(source.rows(source.statement(*columns).where(product.is_not(None)).group_by(product)))
        if "category" not in df:
            df["category"] = "Unspecified"
    else:
        df = _reference_product_features(db, f)

    return _product_predictions(df, bundle)


def _reference_product_features(db, f):
    import pandas as pd
    from app.analytics.filters import item_where, item_from
    where, params = item_where(f)
    sql = f"""
        SELECT SUBSTR(i.product_id, 1, 8) AS product,
               COALESCE(i.product_category_name_en, 'unknown') AS category,
               COALESCE(SUM(i.price), 0) AS total_revenue,
               COUNT(*) AS total_qty,
               AVG(i.price) AS avg_price,
               AVG(p.product_weight_g) AS product_weight_g
        FROM {item_from(f, with_product=True)}
        WHERE {where}
        GROUP BY i.product_id, category
    """
    df = pd.read_sql(sql, db.connection(), params=params)
    return df


def _product_predictions(df, bundle):
    import numpy as np
    model, scaler, features = bundle["model"], bundle["scaler"], bundle["features"]

    if df.empty:
        return {"segments": [], "top_products": [], "k": bundle.get("k", 0)}

    # Preprocessing identical to training
    df["qty_log"] = np.log1p(df["total_qty"].clip(lower=0))
    df["revenue_log"] = np.log1p(df["total_revenue"].clip(lower=0))

    if not np.isfinite(df[['total_qty', 'total_revenue', 'avg_price']].to_numpy(dtype=float)).all() or (df[['total_qty', 'total_revenue', 'avg_price']] < 0).any().any():
        raise ValueError('Product inputs must be finite and nonnegative.')

    # This saved artifact has no fitted imputer. A current-batch median (or
    # zero) would change preprocessing when filters/datasets change.
    if df[["product_weight_g", "avg_price"]].isna().any().any():
        raise ValueError("Training imputation statistics are unavailable; complete product weight and price inputs are required.")

    X = df[features].astype(float)
    Xs = scaler.transform(X)
    df["segment"] = model.predict(Xs).astype(int)

    # Aggregate
    agg = df.groupby("segment").agg(
        products=("product", "count"),
        revenue=("total_revenue", "sum"),
        quantity=("total_qty", "sum"),
        avg_price=("avg_price", "mean"),
    ).reset_index()

    # Get sample products per segment
    samples = []
    for s in agg["segment"].unique():
        sdf = df[df["segment"] == s].nlargest(5, "total_revenue")
        for _, row in sdf.iterrows():
            samples.append({
                "product": row["product"],
                "category": row["category"],
                "segment": int(row["segment"]),
                "revenue": round(float(row["total_revenue"]), 2),
                "quantity": int(row["total_qty"]),
                "avg_price": round(float(row["avg_price"]), 2)
            })

    # Add share pct
    total_rev = agg["revenue"].sum()
    total_qty = agg["quantity"].sum()

    out_segs = []
    for _, row in agg.iterrows():
        out_segs.append({
            "segment": int(row["segment"]),
            "products": int(row["products"]),
            "revenue": round(float(row["revenue"]), 2),
            "quantity": int(row["quantity"]),
            "avg_price": round(float(row["avg_price"]), 2),
            "revenue_share": round(float(row["revenue"]) / total_rev * 100, 1) if total_rev else 0.0,
            "quantity_share": round(float(row["quantity"]) / total_qty * 100, 1) if total_qty else 0.0
        })

    return {
        "segments": out_segs,
        "top_products": samples,
        "k": int(bundle.get("k", len(agg)))
    }


def predict_sales(payload: dict) -> dict:
    import pandas as pd

    bundle = _load_artifact("sales_prediction")
    pipe, features = bundle["pipeline"], bundle["features"]
    row = pd.DataFrame([{f: payload.get(f) for f in features}])
    yhat = float(pipe.predict(row)[0])
    return {"predicted_item_revenue": round(yhat, 2), "currency": "BRL"}


def daily_readiness(points, targets):
    """Profile observed calendar coverage without filling or inventing days."""
    import pandas as pd
    import numpy as np
    if not points:
        return {'observations': 0, 'from': None, 'to': None, 'missing_calendar_days': 0,
                'latest_window_consecutive': False, 'invalid_targets': [], 'zero_targets': {}}
    dates = pd.to_datetime([point['period'] for point in points], errors='coerce', utc=True)
    valid_dates = dates[~dates.isna()]
    ordered = valid_dates.sort_values()
    latest = ordered[-30:]
    invalid, zero = [], {}
    for target in targets:
        values = pd.to_numeric(pd.Series([point.get(target) for point in points]), errors='coerce').to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any(): invalid.append(target)
        zero[target] = int((values == 0).sum())
    return {'observations': len(points), 'from': str(ordered.min().date()) if len(ordered) else None,
            'to': str(ordered.max().date()) if len(ordered) else None,
            'invalid_dates': int(dates.isna().sum()), 'duplicate_dates': int(valid_dates.duplicated().sum()),
            'missing_calendar_days': len(pd.date_range(ordered.min(), ordered.max()).difference(ordered)) if len(ordered) else 0,
            'latest_window_consecutive': len(latest) >= 30 and bool(((latest[1:]-latest[:-1]).days == 1).all()),
            'invalid_targets': invalid, 'zero_targets': zero}


def compatibility(name, db, f=None):
    """Contracts describe trained-domain validity separately from availability."""
    from app.analytics.filters import Filters
    from app.analytics import metrics
    ds = db.info["dataset"]
    contract = load_all_metadata().get(name, {}).get("contract", {})
    reasons = []
    if not contract:
        reasons.append("No verified inference contract is registered for this model.")
    if getattr(ds,'source_type',None) == 'bundle':
        from app.analytics.bundle import BundleSource
        source=BundleSource(db,f)
        roles={'date','order'}
        if source.amount is not None: roles.update({'revenue','price','quantity','product','seller'})
        if source.enabled('orders','customers'): roles.update({'customer','location'})
        if source.pc: roles.add('category')
        if 'product_weight_g' in source.pc and next(c['dtype'] for c in source.tables['products'][0].profile['columns'] if c['name']=='product_weight_g')=='numeric': roles.add('weight_g')
        for role in contract.get('required_semantics',[]):
            if role not in roles: reasons.append(f'Missing validated {role} relationship or field. Review bundle relationships or select a compatible table.')
        if contract.get('currency_code') and ds.semantics.get('currency_code')!=contract['currency_code']:
            reasons.append(f"This trained model requires confirmed {contract['currency_code']} monetary units. Confirm bundle currency in Dataset Manager.")
        if ds.semantics.get('domain') not in {'commerce','transactions'}:
            reasons.append('Confirm the commerce domain in Dataset Manager.')
        required=contract.get('required_semantics',[])
        checks=[('date','orders','order_purchase_timestamp'),('customer','customers','customer_unique_id'),('price','items','price'),('revenue','items','price'),('weight_g','products','product_weight_g')]
        for role,table,column in checks:
            if role in required and table in source.tables:
                profile=next((c for c in source.tables[table][0].profile['columns'] if c['name']==column),None)
                if profile and profile['missing']: reasons.append(f'Required {role} contains missing values; no fitted training imputation is available. Review table quality before inference.')
                if profile and (profile.get('statistics',{}).get('min') or 0)<0: reasons.append(f'Required {role} contains negative values outside the trained contract.')
    elif ds.adapter == "tabular":
        from app.analytics.tabular import TabularSource
        source = TabularSource(db, f)
        for role in contract.get("required_semantics", []):
            if source.field(role) is None:
                reasons.append(f"Missing confirmed {role.replace('_', ' ')} field.")
        currency = contract.get("currency_code")
        if currency and ds.semantics.get("currency_code") != currency:
            reasons.append(f"This trained model requires confirmed {currency} monetary units.")
        if ds.semantics.get("domain") not in {"commerce", "transactions"}:
            reasons.append("The model was trained for commerce; this dataset's domain is unconfirmed or unrelated.")
        columns = {c["name"]: c for c in source.columns}
        for role in contract.get("required_semantics", []):
            column = columns.get(source.fields.get(role))
            if column and column["missing"]:
                reasons.append(f"Required {role} contains missing values; correct the dataset before inference.")
            if column and role in {"revenue", "price", "quantity", "weight_g"} and column.get("statistics", {}).get("min", 0) < 0:
                reasons.append(f"The {role} field contains negative values outside the trained feature contract.")
    readiness = None
    if not reasons:
        if contract.get("frequency") == "daily":
            points = metrics.time_series(db, f or Filters(), "day", limit=100_000)
            targets = [name.removeprefix('sales_forecast_')] if name.startswith('sales_forecast_') else ['orders', 'revenue']
            readiness = daily_readiness(points, targets)
            if len(points) < contract.get("minimum_observations", 1):
                reasons.append(f"At least {contract.get('minimum_observations')} daily observations are required after filtering.")
            elif name.startswith('sales_forecast_') and not readiness['latest_window_consecutive']:
                reasons.append("The latest 30 daily observations must be consecutive; missing days cannot be assumed to be zero.")
            if readiness.get('invalid_dates') or readiness.get('duplicate_dates'):
                reasons.append('Daily observations contain invalid or duplicate dates.')
            if readiness['invalid_targets']:
                reasons.append('Daily targets contain missing, non-finite or negative values: '+', '.join(readiness['invalid_targets']))
        else:
            if getattr(ds,'source_type',None) == 'bundle':
                from sqlalchemy import func
                n=db.scalar(__import__('sqlalchemy').select(func.count()).select_from(source.order_ids().subquery()))
            elif ds.adapter == "star_schema":
                from app.analytics.filters import order_from, order_where
                from sqlalchemy import text
                where, params = order_where(f or Filters())
                n = db.scalar(text(f"SELECT COUNT(*) FROM {order_from(f or Filters())} WHERE {where}"), params)
            else:
                from sqlalchemy import func
                n = source.scalar(func.count())
            if not n:
                reasons.append("No observations match the selected filters.")
    return {"compatible": not reasons, "reasons": reasons, "contract": contract,
            "training_domain": contract.get("training_domain"), "dataset_id": ds.id,
            "artifact_available": artifact_available(name), "readiness": readiness}


def validate_output(value):
    import math
    import numbers
    if isinstance(value, dict):
        for v in value.values():
            validate_output(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            validate_output(v)
    elif isinstance(value, numbers.Real) and not math.isfinite(float(value)):
        raise ValueError("Model returned a non-finite prediction.")
