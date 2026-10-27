from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import require_bi_user
from app.database.deps import get_db
from app.models.dataset import Dataset, DatasetSelection, DatasetBundleTable
from app.services import datasets as service
from app.services import dataset_bundles as bundles
from app.services import bundle_jobs
from fastapi.responses import JSONResponse

router = APIRouter()


def dataset_context(request: Request, db=Depends(get_db), user=Depends(require_bi_user),
                    x_dataset_id: str | None = Header(None), dataset_id: str | None = None):
    if x_dataset_id and dataset_id and x_dataset_id != dataset_id:
        raise HTTPException(422, "Conflicting dataset identifiers.")
    allowed = {"dataset_id", "date_from", "date_to", "category", "customer_state", "seller_state", "order_status",
               "payment_type", "review_score", "column_filters", "grain", "limit", "periods", "target", "report"}
    if request.url.path == '/api/analytics/business':
        allowed.add('domain')
    if request.url.path == '/api/ml/seasonal-demo':
        allowed.add('horizon')
    if any(k not in allowed for k in request.query_params):
        raise HTTPException(422, "An unsupported dataset query parameter was supplied.")
    if request.url.path == '/api/ml/seasonal-demo':
        # This isolated demo loads its own frozen working-series artifacts and
        # intentionally does not depend on the user's selected live dataset.
        return None
    if "grain" in request.query_params:
        from app.analytics.filters import parse_filters
        parse_filters(grain=request.query_params["grain"])
    if request.url.path.startswith("/api/ml") and request.query_params.get("grain", "day") != "day":
        raise HTTPException(422, "ML inference uses daily history or entity aggregates. Remove the unsupported time grain filter.")
    return service.resolve(db, user, x_dataset_id or dataset_id)


@router.get("")
def list_datasets(db=Depends(get_db), user=Depends(require_bi_user)):
    service.ensure_registry(db)
    datasets = db.scalars(select(Dataset).where((Dataset.owner == user["username"]) | Dataset.owner.is_(None))
                          .order_by(Dataset.created_at.desc())).all()
    selection = db.get(DatasetSelection, user["username"])
    if not selection and any(d.id == service.REFERENCE_ID for d in datasets):
        service.resolve(db, user)
        selection = db.get(DatasetSelection, user["username"])
    children = set(db.scalars(select(DatasetBundleTable.dataset_id)).all())
    return {"datasets": [bundles.public(d, db) for d in datasets if d.id not in children],
            "active_dataset_id": selection.dataset_id if selection else None}


@router.get("/upload-limits")
def upload_limits(user=Depends(require_bi_user)):
    return {"max_bytes": service.MAX_BYTES, "max_rows": service.MAX_ROWS, "max_columns": service.MAX_COLUMNS,
            "max_cells": service.MAX_CELLS, "max_seconds": service.MAX_SECONDS, "max_files": bundles.MAX_FILES,
            "max_zip_ratio": bundles.MAX_RATIO, "relational_analysis": True,
            "max_expanded_bytes": bundles.MAX_EXPANDED_BYTES, "bundle_max_rows": bundles.MAX_ROWS,
            "bundle_max_cells": bundles.MAX_CELLS, "bundle_max_seconds": bundles.MAX_SECONDS,
            "max_table_rows": bundles.MAX_TABLE_ROWS, "max_table_cells": bundles.MAX_TABLE_CELLS,
            "concurrent_bundle_imports": 1}


@router.post("/bundles/upload", status_code=201)
def upload_bundle(files: list[UploadFile] = File(...), paths: list[str] = Form(...),
                  name: str = Form(..., min_length=1, max_length=120),
                  db=Depends(get_db), user=Depends(require_bi_user)):
    if len(files) != len(paths):
        raise HTTPException(422, "Each file must have one relative path.")
    if len(files) > bundles.MAX_FILES:
        raise HTTPException(413, f"Bundle exceeds {bundles.MAX_FILES} files.")
    result,code = bundle_jobs.submit(db,user,name,files,paths)
    return JSONResponse(result,status_code=code)


@router.post("/bundles/zip", status_code=201)
def upload_zip(file: UploadFile = File(...), name: str = Form(..., min_length=1, max_length=120),
               db=Depends(get_db), user=Depends(require_bi_user)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(422, "Choose a ZIP archive.")
    result,code = bundle_jobs.submit(db,user,name,[file],zipped=True)
    return JSONResponse(result,status_code=code)


@router.post("/bundles/zip-preview")
def zip_preview(file: UploadFile = File(...), user=Depends(require_bi_user)):
    raw = file.file.read(service.MAX_BYTES + 1)
    if len(raw) > service.MAX_BYTES:
        raise HTTPException(413, f"Compressed ZIP exceeds {service.MAX_BYTES} byte upload limit.")
    return bundle_jobs.zip_manifest(__import__('io').BytesIO(raw))


@router.get('/bundles/jobs/{job_id}')
def import_status(job_id: str,user=Depends(require_bi_user)):
    return bundle_jobs.status(job_id,user)


@router.post('/bundles/jobs/{job_id}/cancel')
def import_cancel(job_id: str,user=Depends(require_bi_user)):
    return bundle_jobs.cancel(job_id,user)


@router.post("/upload", status_code=201)
def upload(file: UploadFile = File(...), name: str = Form(..., min_length=1, max_length=120),
           db=Depends(get_db), user=Depends(require_bi_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".json", ".xlsx", ".xls"}:
        raise HTTPException(422, "Unsupported file type. Use CSV, XLSX, XLS or flat-record JSON.")
    raw = file.file.read(service.MAX_BYTES + 1)
    if len(raw) > service.MAX_BYTES:
        raise HTTPException(413, "File exceeds the configured upload size limit.")
    if not name.strip():
        raise HTTPException(422, "Dataset name is required.")
    return service.public(service.ingest(db, user, name.strip(), raw, suffix))


@router.get("/{dataset_id}")
def detail(dataset_id: str, db=Depends(get_db), user=Depends(require_bi_user)):
    service.ensure_registry(db)
    return bundles.public(service.authorized(db, dataset_id, user), db)


@router.post("/{dataset_id}/select")
def select_dataset(dataset_id: str, db=Depends(get_db), user=Depends(require_bi_user)):
    service.ensure_registry(db)
    ds = service.authorized(db, dataset_id, user, ready=True)
    if ds.source_type == "bundle" and not ds.profile.get('relational_analysis',{}).get('supported'):
        member = db.scalars(select(DatasetBundleTable).where(DatasetBundleTable.bundle_id == ds.id)
                            .order_by(DatasetBundleTable.relative_path)).first()
        if not member:
            raise HTTPException(409, "Bundle contains no ready tables.")
        ds = service.authorized(db, member.dataset_id, user, ready=True)
    selection = db.get(DatasetSelection, user["username"])
    if selection:
        selection.dataset_id = ds.id
    else:
        db.add(DatasetSelection(username=user["username"], dataset_id=ds.id))
    db.commit()
    return bundles.public(ds, db)


@router.get("/{dataset_id}/preview")
def preview(dataset_id: str, db=Depends(get_db), user=Depends(require_bi_user)):
    service.ensure_registry(db)
    ds = service.authorized(db, dataset_id, user, ready=True)
    if ds.source_type == "bundle" or ds.adapter != "tabular":
        raise HTTPException(422, "Select an uploaded table to preview its rows.")
    columns = ds.profile["columns"]
    rows = db.execute(select(service.storage_table(ds, db)).limit(20)).mappings().all()
    return {"dataset_id": ds.id, "columns": [c["name"] for c in columns],
            "rows": [{c["name"]: row[c["storage"]] for c in columns} for row in rows], "limit": 20}


class SchemaUpdate(BaseModel):
    fields: dict[str, str | None] = Field(default_factory=dict)
    currency_code: Literal["BRL", "USD", "INR", "EUR", "GBP"] | None = None
    domain: Literal["general", "commerce", "transactions"] = "general"
    date_order: Literal["dayfirst", "monthfirst"] | None = None


@router.patch("/{dataset_id}/schema")
def update_schema(dataset_id: str, payload: SchemaUpdate, db=Depends(get_db), user=Depends(require_bi_user)):
    ds = service.authorized(db, dataset_id, user, ready=True)
    if ds.source_type == "bundle":
        if payload.fields or payload.date_order:
            raise HTTPException(422,'Configure field mappings on the individual table. Bundle schema confirms currency and domain only.')
        ds.semantics = {**ds.semantics, 'currency_code':payload.currency_code,'domain':payload.domain,'confirmed_by':user['username']}
        ds.updated_at = datetime.now(timezone.utc)
        db.commit()
        return bundles.public(ds,db)
    if ds.owner is None:
        raise HTTPException(403, "Reference dataset schema is read-only.")
    columns = ds.profile["columns"]
    member = db.get(DatasetBundleTable, ds.id)
    if payload.date_order:
        with bundle_jobs.GUARD:
            if any(job['status'] in {'QUEUED','PROCESSING'} for job in bundle_jobs.JOBS.values()) or bundles.IMPORT_LOCK.locked():
                raise HTTPException(429,'Wait for the current import before reparsing table dates.')
        import csv
        limits = {'max_rows':bundles.MAX_TABLE_ROWS,'max_cells':bundles.MAX_TABLE_CELLS,'max_bytes':bundles.MAX_EXPANDED_BYTES} if member else {}
        try:
            source = service.parse_source(ds.raw_source, "." + ds.source_type, **limits)
            normalized, columns, quality = service.profile_frame(source, payload.date_order)
        except (ValueError,csv.Error,UnicodeError) as exc:
            raise HTTPException(422,str(exc)) from None
        table = service.storage_table(ds, db)
        # Dates are stored as text; only date fields change on reparsing.
        date_columns = [c for c in columns if c["dtype"] == "datetime"]
        from sqlalchemy import update,bindparam
        statement=update(table).where(table.c.row_id==bindparam('_schema_row'))
        batch=[]
        for idx, values in enumerate(normalized.itertuples(index=False, name=None), 1):
            if date_columns:
                batch.append({'_schema_row':idx,**{
                    c["storage"]: None if __import__("pandas").isna(values[int(c["storage"][1:])]) else str(values[int(c["storage"][1:])])
                    for c in date_columns}})
                if len(batch)==5000: db.execute(statement,batch);batch=[]
        if batch: db.execute(statement,batch)
        ds.profile = {"columns": columns}
        ds.quality = quality
    by_name = {c["name"]: c for c in columns}
    mappings = dict(service.infer_semantics(columns)["fields"] if payload.date_order else ds.semantics.get("fields", {}))
    for role, name in payload.fields.items():
        if role not in service.ROLES:
            raise HTTPException(422, "Unsupported semantic role.")
        if name is None:
            mappings.pop(role, None)
            continue
        if name not in by_name:
            raise HTTPException(422, "The selected field does not exist in this dataset.")
        dtype = by_name[name]["dtype"]
        if role in {"revenue", "currency", "price", "quantity", "rating", "weight_g"} and dtype != "numeric":
            raise HTTPException(422, "This semantic role requires a numeric field.")
        if role in {"date", "delivery_date", "estimated_date"} and dtype != "datetime":
            raise HTTPException(422, "This semantic role requires a validated date field. Confirm date order first.")
        mappings[role] = name
    ds.semantics = {**ds.semantics, "fields": mappings,
                    "currency_code": payload.currency_code, "domain": payload.domain,
                    "confirmed_by": user["username"], "ambiguities": [a for a in ds.semantics.get("ambiguities", []) if a["role"] not in payload.fields]}
    ds.capabilities = service.detect_capabilities(ds.semantics)
    ds.updated_at = datetime.now(timezone.utc)
    if member:
        from app.analytics.bundle import describe
        parent=service.authorized(db,member.bundle_id,user,ready=True)
        relation=describe(db,parent)
        parent.profile={'relational_analysis':relation}
        parent.semantics={**parent.semantics,'fields':bundles.semantic_fields(relation)}
        parent.capabilities=service.detect_capabilities(parent.semantics)
        parent.updated_at=ds.updated_at
    db.commit()
    return bundles.public(ds, db)


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, db=Depends(get_db), user=Depends(require_bi_user)):
    ds = service.authorized(db, dataset_id, user)
    if ds.owner is None:
        raise HTTPException(403, "The shared reference dataset cannot be deleted.")
    if ds.status == "PROCESSING":
        raise HTTPException(409, "Wait for dataset processing to finish.")
    member = db.get(DatasetBundleTable, ds.id)
    if member:
        raise HTTPException(409, "Delete the containing bundle to remove its tables together.")
    if ds.source_type == "bundle":
        for member in db.scalars(select(DatasetBundleTable).where(DatasetBundleTable.bundle_id == ds.id)).all():
            child = service.authorized(db, member.dataset_id, user)
            service.storage_table(child, db).drop(db.connection())
            db.delete(member)
            db.delete(child)
    elif ds.status == "READY":
        service.storage_table(ds, db).drop(db.connection())
    # Keep selection pointing at the removed ID until explicit selection.
    # Subsequent calls fail visibly instead of silently reverting to reference.
    db.delete(ds)
    db.commit()
