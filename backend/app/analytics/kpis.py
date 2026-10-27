"""KPI computations over the warehouse.

Definitions are documented in docs/KPIs.md. Values derive from the authorized
selected dataset. Reference revenue is the sum of order item prices.

Historical filter surface (kept for the dashboard endpoints, CSV reports and
the AI-assistant context): date_from, date_to (ISO dates), order_status.
Newer filter-aware code calls `app.analytics.metrics` directly with a full
`Filters` set (see docs/ANALYTICS.md); this module delegates to it so there is
exactly one implementation of each metric.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.analytics import metrics as metrics_service
from app.analytics.filters import Filters


def get_kpis(
    db: Session,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    order_status: Optional[str] = None,
) -> dict:
    f = Filters(date_from=date_from, date_to=date_to, order_status=order_status)
    return {
        "filters": {
            "date_from": date_from,
            "date_to": date_to,
            "order_status": order_status,
        },
        "kpis": metrics_service.kpis(db, f),
    }


def month_expr(db: Session, column: str = "purchase_date") -> str:
    """Return a dialect-appropriate year-month expression for `column`."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return f"to_char({column}, 'YYYY-MM')"
    if dialect in {"mysql", "mariadb"}:
        return f"date_format({column}, '%Y-%m')"
    return f"strftime('%Y-%m', {column})"


def monthly_revenue(db: Session, limit: int = 24) -> list[dict]:
    return metrics_service.time_series(db, Filters(), "month")[-limit:]


def revenue_by_category(db: Session, limit: int = 15) -> list[dict]:
    return metrics_service.revenue_by_category(db, Filters(), limit=limit)


def orders_by_status(db: Session) -> list[dict]:
    return metrics_service.orders_by_status(db, Filters())
