from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.analytics.filters import Filters, analytics_filters
from app.database.deps import get_db

router = APIRouter()


@router.get("/kpis")
def kpis(
    f: Filters = Depends(analytics_filters),
    db: Session = Depends(get_db),
):
    """Return verified business KPIs computed from the selected dataset.

    Values come from real data via the ETL pipeline (see docs/KPIs.md).
    Accepts the shared analytics filter set (see docs/ANALYTICS.md).
    """
    return {"filters": f.as_dict(), "kpis": metrics.kpis(db, f)}


@router.get("/monthly-revenue")
def monthly_revenue(
    f: Filters = Depends(analytics_filters),
    limit: int = Query(default=24, ge=1, le=400),
    db: Session = Depends(get_db),
):
    series = metrics.time_series(db, f, "month")
    return {"series": series[-limit:]}


@router.get("/revenue-by-category")
def revenue_by_category(
    f: Filters = Depends(analytics_filters),
    limit: int = Query(default=15, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return {"series": metrics.revenue_by_category(db, f, limit=limit)}


@router.get("/orders-by-status")
def orders_by_status(
    f: Filters = Depends(analytics_filters),
    db: Session = Depends(get_db),
):
    return {"series": metrics.orders_by_status(db, f)}
