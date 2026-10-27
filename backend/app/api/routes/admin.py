import platform
import sys
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text

from app.api.deps import require_roles
from app.core.config import settings
from app.database.session import engine
from app.database.deps import get_db
from app.api.routes.datasets import dataset_context

router = APIRouter()

WAREHOUSE_TABLES = [
    "dim_customer",
    "dim_product",
    "dim_seller",
    "dim_date",
    "fact_orders",
    "fact_order_items",
]

_STARTED_AT = time.time()


def _table_counts() -> dict[str, int | None]:
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    counts: dict[str, int | None] = {}
    with engine.connect() as conn:
        for table in WAREHOUSE_TABLES:
            if table in existing:
                counts[table] = int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
            else:
                counts[table] = None
    return counts


@router.get("/system/status")
def system_status(_: dict = Depends(require_roles("admin"))):
    return {
        "app": "Sem5 BI Platform",
        "version": "0.1.0",
        "env": settings.ENV,
        "auth_required": settings.AUTH_REQUIRED,
        "database": settings.DATABASE_URL.split("://", 1)[0],
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.get("/health")
def health_status(_: dict = Depends(require_roles("admin"))):
    """Real health checks for the administration UI."""
    from app.services import ml as ml_service

    # Check Database Connectivity
    db_status = "Unavailable"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_status = "Healthy"
    except Exception:
        db_status = "Unavailable"

    # Check Warehouse
    warehouse_status = "Unavailable"
    try:
        counts = _table_counts()
        loaded_tables = sum(1 for v in counts.values() if v)
        if loaded_tables == len(WAREHOUSE_TABLES):
            warehouse_status = "Healthy"
        elif loaded_tables > 0:
            warehouse_status = "Degraded"
        else:
            warehouse_status = "Empty"
    except Exception:
        warehouse_status = "Unavailable"

    # Check ML Models
    ml_status = "Unavailable"
    available_models = 0
    total_models = 0
    try:
        features = ml_service.feature_status()
        for f in features:
            for m in f["models"]:
                total_models += 1
                if m.get("artifact_available"):
                    available_models += 1
        if total_models > 0 and available_models == total_models:
            ml_status = f"{available_models}/{total_models} Available"
        elif total_models > 0:
            ml_status = f"{available_models}/{total_models} Available (Warning)"
        else:
            ml_status = "0/0 Available"
    except Exception:
        ml_status = "Unavailable"

    return {
        "backend": "Healthy",
        "database": db_status,
        "warehouse": warehouse_status,
        "ml_models": ml_status,
        "authentication": db_status,  # Relies on database
    }


@router.get("/data/etl/status")
def etl_status(_: dict = Depends(require_roles("admin"))):
    counts = _table_counts()
    loaded = bool(counts.get("fact_orders"))
    return {
        "loaded": loaded,
        "tables": counts,
        "olist_dir": str(_olist_dir()),
    }


def _olist_dir() -> str:
    import os
    from pathlib import Path

    env = os.getenv("OLIST_DIR")
    if env:
        return env
    return str(Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads" / "olist")


@router.get("/warehouse/status")
def warehouse_status(_: dict = Depends(require_roles("admin")), ds=Depends(dataset_context), db=Depends(get_db)):
    """Warehouse administration: schema presence, row counts and load state."""
    if ds.adapter == "tabular":
        from app.analytics.tabular import TabularSource
        source = TabularSource(db)
        dates = source.filters()["date_range"]
        return {"dataset_id": ds.id, "dialect": db.get_bind().dialect.name,
                "schema_tables": [ds.name], "warehouse_tables": {ds.name: ds.row_count},
                "expected_tables": 1, "loaded_tables": 1, "total_rows": ds.row_count,
                "complete": ds.status == "READY", "source": ds.name,
                "min_date": dates["min"], "max_date": dates["max"]}
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    counts = _table_counts()
    loaded_tables = sum(1 for v in counts.values() if v)
    total_rows = sum(v for v in counts.values() if v)
    min_date = None
    max_date = None
    try:
        if counts.get("fact_orders"):
            with engine.connect() as conn:
                res = conn.execute(text("SELECT min(purchase_date), max(purchase_date) FROM fact_orders")).fetchone()
                if res and res[0]:
                    min_date = res[0]
                    max_date = res[1]
    except Exception:
        pass

    return {
        "dialect": engine.dialect.name,
        "schema_tables": sorted(existing),
        "warehouse_tables": counts,
        "expected_tables": len(WAREHOUSE_TABLES),
        "loaded_tables": loaded_tables,
        "total_rows": total_rows,
        "complete": loaded_tables == len(WAREHOUSE_TABLES),
        "source": str(_olist_dir()),
        "min_date": min_date,
        "max_date": max_date,
    }


@router.get("/ml/status")
def ml_admin_status(_: dict = Depends(require_roles("admin"))):
    """ML administration: deployed artifacts and training state on disk."""
    from pathlib import Path

    from app.services import ml as ml_service

    models_dir = ml_service.models_dir()
    artifacts = []
    if models_dir.exists():
        for path in sorted(models_dir.glob("*.joblib")):
            stat = path.stat()
            artifacts.append(
                {
                    "file": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    features = ml_service.feature_status()
    trained = sum(1 for f in features for m in f["models"])
    return {
        "models_dir": str(models_dir),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "metadata_entries": trained,
        "features": features,
        "data_dir_exists": Path(ml_service.processed_dir()).exists(),
        "retraining": "manual (python ml/run_all.py)",
    }


@router.get("/settings")
def system_settings(_: dict = Depends(require_roles("admin")), ds=Depends(dataset_context)):
    """Non-secret application settings. Secrets are never returned."""
    return {
        "app": "Sem5 BI Platform",
        "version": "0.1.0",
        "env": settings.ENV,
        "auth_required": settings.AUTH_REQUIRED,
        "access_token_expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        "refresh_token_expire_minutes": settings.REFRESH_TOKEN_EXPIRE_MINUTES,
        "roles": ["admin", "analyst"],
        "llm": {
            "enabled": settings.ENABLE_LLM_ASSISTANT,
            "provider": settings.LLM_PROVIDER,
            "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        },
        "dataset": ds.name,
        "reports": ["kpis", "monthly_revenue", "revenue_by_category", "orders_by_status"],
        "secrets_exposed": False,
    }
