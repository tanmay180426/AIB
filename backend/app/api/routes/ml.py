from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.analytics.filters import Filters, analytics_filters
from app.database.deps import get_db
from app.services import ml as ml_service
from app.api.deps import require_bi_user

router = APIRouter()


class SalesPredictRequest(BaseModel):
    purchase_month: int = Field(..., ge=1, le=12)
    purchase_weekday: int = Field(..., ge=0, le=6)
    purchase_hour: int = Field(..., ge=0, le=23)
    n_items: int = Field(..., ge=1)
    customer_state: str = "SP"
    product_category_name: str = "unknown"


@router.get("/offline-evaluation")
def ml_offline_evaluation(user=Depends(require_bi_user)):
    """Read saved validation predictions without invoking live model inference."""
    from app.services.offline_forecast_evaluation import load_offline_evaluations

    return load_offline_evaluations()


@router.get("/status")
def ml_status(db=Depends(get_db), f=Depends(analytics_filters)):
    features = ml_service.feature_status()
    for feature in features:
        for model in feature["models"]:
            model["compatibility"] = ml_service.compatibility(model["name"], db, f)
            model["metrics_scope"] = "Recorded offline evaluation on documented training-source files, not the selected dataset. Real/synthetic composition and original fit logs are unverified."
    candidates = []
    candidate_path = ml_service.REPO_ROOT / 'ml/candidates/abi-revenue/provenance.json'
    if candidate_path.is_file():
        import json
        candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
        candidates.append({'name':'abi_gradient_boosting_revenue','status':'blocked','models':[{
            'name':'abi_gradient_boosting_revenue','algorithm':'GradientBoostingRegressor (source candidate)',
            'trained_at':None,
            'artifact_available':(candidate_path.parent/'gradient_boosting_sales_model.joblib').is_file(),
            'runtime_ready':False,'runtime_reason':'Inactive source candidate: verified training/preprocessing and provenance inputs are missing; it is not loaded in this API process.',
            'metrics':None,'metrics_scope':'Source evaluation claims are not reproducible and are not selected-dataset metrics.',
            'compatibility':{'compatible':False,'reasons':candidate.get('missing_evidence',[]),'contract':{},'training_domain':None},
            'source_commit':candidate.get('source_commit'),'artifact_sha256':candidate.get('artifact_sha256')
        }]})
    return {"features": features, "source_candidates": candidates, "dataset_id": db.info["dataset"].id}


@router.get("/models/{name}")
def ml_model_detail(name: str, db=Depends(get_db), f=Depends(analytics_filters)):
    meta = ml_service.load_all_metadata().get(name)
    if not meta:
        raise HTTPException(status_code=404, detail=f"model '{name}' not found")
    from app.services.model_audit import audit_model
    from app.services.forecast_quality import candidate_evidence
    from app.services.synthetic_forecast import selected_evidence
    return {**meta, "compatibility": ml_service.compatibility(name, db, f), "audit": audit_model(name),
            "candidate_evidence": candidate_evidence(name),
            "selected_synthetic_forecast": selected_evidence(db, name.removeprefix('sales_forecast_')) if name.startswith('sales_forecast_') else None}


def _infer(name, db, f, function, check_override=None):
    check = check_override if check_override is not None else ml_service.compatibility(name, db, f)
    if not check["compatible"]:
        return {"status": "not_applicable", "reason": " ".join(check["reasons"]), "compatibility": check,
                "dataset_id": db.info["dataset"].id}
    try:
        result = function()
        ml_service.validate_output(result)
        return {**result, "status": "available", "compatibility": check, "dataset_id": db.info["dataset"].id}
    except FileNotFoundError:
        raise HTTPException(503, "The trained model artifact is unavailable. Contact the administrator.") from None
    except (ValueError, KeyError, IndexError):
        raise HTTPException(422, "Model inference could not produce valid output for this dataset and filter selection.") from None


@router.get("/forecast")
def ml_forecast(periods: int = 30, target: str = "orders", db=Depends(get_db), f=Depends(analytics_filters), user=Depends(require_bi_user)):
    # One calendar year can contain 366 days; recursion remains bounded.
    if not (1 <= periods <= 366):
        raise HTTPException(status_code=400, detail="periods must be between 1 and 366")
    if target not in ("orders", "revenue"):
        raise HTTPException(status_code=400, detail="target must be orders or revenue")
    from app.services import synthetic_forecast
    registration = synthetic_forecast.registered_scopes(db,user['username'])
    try:
        chart = synthetic_forecast.chart_history(db,f,target)
    except HTTPException as error:
        if error.status_code not in (409,422): raise
        chart = {'historical_series':[],'historical_coverage':None,'history_reason':str(error.detail)}
    except (ValueError,KeyError,TypeError):
        raise HTTPException(422,'Selected history contains invalid or duplicate daily target observations; no chart or substitute forecast was returned.') from None
    check = synthetic_forecast.compatibility(db, f, target)
    if check is not None:
        result = _infer(f'synthetic_{target}', db, f,
            lambda: synthetic_forecast.forecast(db, f, target, periods), check_override=check)
    else:
        result = _infer(f"sales_forecast_{target}", db, f, lambda: ml_service.forecast(periods, target, db, f))
    if result.get('status') == 'available' and periods > 90:
        result['warnings'] = [*result.get('warnings',[]),
            'Long-horizon experimental output: annual forecast accuracy has not been validated. Recursive errors may accumulate beyond the evaluated 7/14/30/90-day horizons.']
    return {**result,**chart,'forecast_series':result.get('forecast',[]),
        'selected_scope':{'dataset_id':db.info['dataset'].id,'dataset_name':db.info['dataset'].name},
        'synthetic_registration':registration}


@router.get("/segments/customers")
def ml_customer_segments(db=Depends(get_db), f=Depends(analytics_filters)):
    return _infer("customer_segmentation", db, f, lambda: ml_service.customer_segments(db, f))


@router.get("/anomalies")
def ml_anomalies(db=Depends(get_db), f=Depends(analytics_filters)):
    return _infer("anomaly_detection", db, f, lambda: ml_service.anomalies(db, f))


@router.post("/predict/sales")
def ml_predict_sales(payload: SalesPredictRequest, db=Depends(get_db), f=Depends(analytics_filters)):
    return _infer("sales_prediction", db, f, lambda: ml_service.predict_sales(payload.model_dump()))


@router.get("/product-segmentation")
def ml_product_segmentation(
    f=Depends(analytics_filters),
    db=Depends(get_db)
):
    return _infer("product_segmentation", db, f, lambda: ml_service.product_segments(db, f))


@router.get("/seasonal-demo")
def ml_seasonal_demo(target: str = "orders", horizon: int = 30, user=Depends(require_bi_user)):
    """Serve frozen experiment artifacts through an isolated, non-production demo endpoint."""
    from fastapi import HTTPException
    from app.services.integrated_seasonal_forecast import forecast

    if target not in {"orders", "revenue"}:
        raise HTTPException(status_code=422, detail="target must be orders or revenue")
    if horizon not in {30, 90, 365}:
        raise HTTPException(status_code=422, detail="horizon must be 30, 90, or 365 days")
    try:
        return forecast(target, horizon)
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Seasonal demo artifacts or working-series data are unavailable.") from None
    except Exception:
        # Artifact deserialization and runtime errors can include local paths.
        # Keep those details out of the API response while failing closed.
        raise HTTPException(status_code=503, detail="Seasonal demo inference failed; verify the saved artifacts and server configuration.") from None
