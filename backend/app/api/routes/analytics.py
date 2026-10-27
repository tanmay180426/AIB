"""Analytics endpoints: the six BI sections plus shared filter metadata.

Every endpoint accepts the same optional filter set (see docs/ANALYTICS.md):
date_from, date_to, category, customer_state, seller_state, order_status,
payment_type, review_score - all validated (422 on bad input) and bound as SQL
parameters. Series endpoints additionally accept a time grain
(day/week/month/year, default month).

Reads are handled by app.analytics.metrics, the shared metric layer, so the
same metric reconciles across pages for the same filters.
"""

from __future__ import annotations

from typing import Optional
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.analytics.filters import GRAINS, Filters, analytics_filters, parse_filters
from app.database.deps import get_db

router = APIRouter()


@router.get("/business")
def business_evidence(
    domain: Literal['revenue', 'customers', 'sellers'] = 'revenue',
    f: Filters = Depends(analytics_filters),
    db: Session = Depends(get_db),
):
    """Opt-in evidence without re-running every legacy dashboard aggregate."""
    from app.analytics.business import evidence
    return evidence(db, f, domain)


def _grain(grain: Optional[str]) -> str:
    """Validate the optional grain query value (422 when unknown)."""
    parse_filters(grain=grain)
    return grain or "month"


@router.get("/filters")
def filter_options(db: Session = Depends(get_db)):
    """Distinct values for the shared filter bar (states, categories, ...)."""
    return metrics.filter_options(db)


@router.get("/overview")
def overview(
    f: Filters = Depends(analytics_filters),
    grain: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Dashboard payload: KPIs, series and distributions in one request."""
    view = metrics.overview(db, f)
    if grain:
        view["time_series" if "metric_cards" in view else "revenue_series"] = metrics.time_series(db, f, _grain(grain))
    return view


@router.get("/sales")
def sales(
    f: Filters = Depends(analytics_filters),
    grain: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    view = metrics.sales(db, f)
    if grain:
        view["time_series" if "metric_cards" in view else "revenue_series"] = metrics.time_series(db, f, _grain(grain))
    return view


@router.get("/orders")
def orders(
    f: Filters = Depends(analytics_filters),
    grain: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    view = metrics.orders(db, f)
    if grain:
        _grain(grain)
        if "metric_cards" in view:
            view["time_series"] = metrics.time_series(db, f, grain)
        else:
            view["orders_series"] = metrics.time_series(db, f, grain)
            view["status_over_time"] = metrics.status_over_time(db, f, grain)
    return view


@router.get("/customers")
def customers(f: Filters = Depends(analytics_filters), db: Session = Depends(get_db)):
    return metrics.customers(db, f)


@router.get("/products")
def products(f: Filters = Depends(analytics_filters), db: Session = Depends(get_db)):
    return metrics.products(db, f)


@router.get("/sellers")
def sellers(
    f: Filters = Depends(analytics_filters),
    grain: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    view = metrics.sellers(db, f)
    if grain:
        _grain(grain)
        if "metric_cards" in view:
            view["time_series"] = metrics.time_series(db, f, grain)
        else:
            view["top_sellers_series"] = metrics.top_sellers_series(db, f, grain=grain)
    return view


@router.get("/delivery")
def delivery(f: Filters = Depends(analytics_filters), db: Session = Depends(get_db)):
    return metrics.delivery(db, f)
