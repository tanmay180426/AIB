"""Shared analytics filter parsing and SQL fragments.

Every analytics endpoint accepts the same optional filter set (see
docs/ANALYTICS.md). Values are always bound as SQL parameters - never
interpolated - so filters cannot inject SQL. Grain/alias strings that must be
interpolated are chosen from fixed whitelists.

Dialect helpers mirror `kpis.month_expr` so the queries stay portable across
SQLite (dev) and PostgreSQL (documented target).
"""

from __future__ import annotations

import re
import json
import math
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

GRAINS = ("day", "week", "month", "quarter", "year")


def order_from(f: Optional["Filters"] = None, with_customer: bool = False) -> str:
    """FROM clause for order-grain queries.

    dim_customer is joined only when the customer_state filter or caller-
    selected columns need it - dimension probes dominate query cost, so
    queries that never touch a dimension must not join one.
    """
    if (f is not None and f.customer_state) or with_customer:
        return (
            "fact_orders o\n"
            "    LEFT JOIN dim_customer c ON c.customer_unique_id = o.customer_unique_id"
        )
    return "fact_orders o"


def item_from(
    f: Optional["Filters"] = None,
    *,
    with_order: bool = False,
    with_product: bool = False,
    with_seller: bool = False,
    with_customer: bool = False,
) -> str:
    """FROM clause for item-grain queries.

    - fact_orders is joined only when order attributes (status, payment type,
      review score, delivery fields) are filtered or selected; purchase dates
      live on fact_order_items as well.
    - dim_customer joins directly via fact_order_items.customer_unique_id.
    - Dimensions are joined only when their columns are used.
    """
    joins = ["fact_order_items i"]
    needs_order = with_order or (
        f is not None and (f.order_status or f.payment_type or f.review_score is not None)
    )
    if needs_order:
        joins.append("JOIN fact_orders o ON o.order_id = i.order_id")
    if with_product:
        joins.append("LEFT JOIN dim_product p ON p.product_id = i.product_id")
    if with_seller or (f is not None and f.seller_state):
        joins.append("LEFT JOIN dim_seller s ON s.seller_id = i.seller_id")
    if with_customer or (f is not None and f.customer_state):
        joins.append(
            "LEFT JOIN dim_customer c ON c.customer_unique_id = i.customer_unique_id"
        )
    return "\n".join(joins)


@dataclass(frozen=True)
class Filters:
    """Validated analytics filters (all optional)."""

    date_from: Optional[str] = None
    date_to: Optional[str] = None
    category: Optional[str] = None
    customer_state: Optional[str] = None
    seller_state: Optional[str] = None
    order_status: Optional[str] = None
    payment_type: Optional[str] = None
    review_score: Optional[int] = None
    column_filters: Optional[str] = None

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def is_empty(self) -> bool:
        return all(v is None for v in self.as_dict().values())


def _valid_date(value: Optional[str], name: str) -> Optional[str]:
    if not value:
        return None
    if not DATE_RE.match(value):
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO date (YYYY-MM-DD)")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} is not a valid calendar date") from None


def _bounded(value: Optional[str], name: str, max_len: int) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > max_len:
        raise HTTPException(status_code=422, detail=f"{name} is too long (max {max_len} characters)")
    return value


def parse_filters(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category: Optional[str] = None,
    customer_state: Optional[str] = None,
    seller_state: Optional[str] = None,
    order_status: Optional[str] = None,
    payment_type: Optional[str] = None,
    review_score: Optional[int] = None,
    grain: Optional[str] = None,
    column_filters: Optional[str] = None,
) -> Filters:
    """Validate raw query values into a `Filters` instance (422 on bad input)."""
    d_from = _valid_date(date_from, "date_from")
    d_to = _valid_date(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")

    if review_score is not None and not (1 <= review_score <= 5):
        raise HTTPException(status_code=422, detail="review_score must be between 1 and 5")

    if grain is not None and grain not in GRAINS:
        raise HTTPException(status_code=422, detail=f"grain must be one of {', '.join(GRAINS)}")

    if column_filters:
        try:
            values = json.loads(column_filters)
            if not isinstance(values, dict) or len(values) > 20 or any(
                not isinstance(k, str) or not isinstance(v, (str, int, float, bool)) or len(str(v)) > 200
                for k, v in values.items()
            ):
                raise ValueError()
            if any(isinstance(v, float) and not math.isfinite(v) for v in values.values()):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "Column filters must be a small JSON object of field/value pairs.") from None

    return Filters(
        date_from=d_from,
        date_to=d_to,
        category=_bounded(category, "category", 100),
        customer_state=_bounded(customer_state, "customer_state", 100),
        seller_state=_bounded(seller_state, "seller_state", 100),
        order_status=_bounded(order_status, "order_status", 32),
        payment_type=_bounded(payment_type, "payment_type", 32),
        review_score=review_score,
        column_filters=column_filters,
    )


def analytics_filters(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    category: Optional[str] = None,
    customer_state: Optional[str] = None,
    seller_state: Optional[str] = None,
    order_status: Optional[str] = None,
    payment_type: Optional[str] = None,
    review_score: Optional[int] = None,
    column_filters: Optional[str] = None,
) -> Filters:
    """FastAPI dependency: validated filter set for an analytics endpoint."""
    return parse_filters(
        date_from=date_from,
        date_to=date_to,
        category=category,
        customer_state=customer_state,
        seller_state=seller_state,
        order_status=order_status,
        payment_type=payment_type,
        review_score=review_score,
        column_filters=column_filters,
    )


def order_where(f: Filters, o: str = "o") -> tuple[str, dict]:
    """Order-grain WHERE clause (date, status, payment type, review score)."""
    clauses = [f"{o}.order_id IS NOT NULL"]
    params: dict = {}
    if f.date_from:
        clauses.append(f"{o}.purchase_date >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        clauses.append(f"{o}.purchase_date <= :date_to")
        params["date_to"] = f.date_to
    if f.order_status:
        clauses.append(f"{o}.order_status = :order_status")
        params["order_status"] = f.order_status
    if f.payment_type:
        clauses.append(f"{o}.payment_type = :payment_type")
        params["payment_type"] = f.payment_type
    if f.review_score is not None:
        # review_score is a per-order mean; select the nearest integer bucket.
        clauses.append(
            f"({o}.review_score >= :review_lo AND {o}.review_score < :review_hi AND {o}.review_score IS NOT NULL)"
        )
        params["review_lo"] = f.review_score - 0.5
        params["review_hi"] = f.review_score + 0.5
    if f.customer_state:
        clauses.append(f"c.customer_state = :customer_state")
        params["customer_state"] = f.customer_state
    if f.category or f.seller_state:
        # Restrict order-grain metrics to orders containing matching items,
        # without multiplying orders by their item count.
        source = "fact_order_items fi"
        matching = []
        if f.category:
            matching.append("COALESCE(fi.product_category_name_en, 'unknown') = :category")
            params["category"] = f.category
        if f.seller_state:
            source += " JOIN dim_seller fs ON fs.seller_id = fi.seller_id"
            matching.append("fs.seller_state = :seller_state")
            params["seller_state"] = f.seller_state
        # Uncorrelated membership scans the item scope once, including on
        # legacy warehouses without a foreign-key index.
        clauses.append(f"{o}.order_id IN (SELECT fi.order_id FROM {source} WHERE {' AND '.join(matching)})")
    return " AND ".join(clauses), params


def item_where(f: Filters, i: str = "i", o: str = "o") -> tuple[str, dict]:
    """Item-grain WHERE clause.

    Dates and the order id use the fact_order_items aliases (which exist
    there too, so queries without the fact_orders join stay valid); status,
    payment type and review score come from the joined fact_orders row, and
    customer geography from dim_customer - `item_from` joins those tables
    whenever this clause references them.
    """
    clauses = [f"{i}.order_id IS NOT NULL"]
    params: dict = {}
    if f.date_from:
        clauses.append(f"{i}.purchase_date >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to:
        clauses.append(f"{i}.purchase_date <= :date_to")
        params["date_to"] = f.date_to
    if f.order_status:
        clauses.append(f"{o}.order_status = :order_status")
        params["order_status"] = f.order_status
    if f.payment_type:
        clauses.append(f"{o}.payment_type = :payment_type")
        params["payment_type"] = f.payment_type
    if f.review_score is not None:
        clauses.append(
            f"({o}.review_score >= :review_lo AND {o}.review_score < :review_hi "
            f"AND {o}.review_score IS NOT NULL)"
        )
        params["review_lo"] = f.review_score - 0.5
        params["review_hi"] = f.review_score + 0.5
    if f.customer_state:
        clauses.append("c.customer_state = :customer_state")
        params["customer_state"] = f.customer_state
    if f.category:
        clauses.append("COALESCE(i.product_category_name_en, 'unknown') = :category")
        params["category"] = f.category
    if f.seller_state:
        clauses.append("s.seller_state = :seller_state")
        params["seller_state"] = f.seller_state
    return " AND ".join(clauses), params


def order_monetary_scope(f: Filters, with_customer: bool = False) -> tuple[str, str]:
    """One row per order, with amounts restricted to the shared item scope."""
    source = order_from(f, with_customer=with_customer)
    if not (f.category or f.seller_state):
        return source, "COALESCE(o.item_revenue, 0)"
    where, _ = item_where(f)
    source += f""" LEFT JOIN (
        SELECT i.order_id, SUM(i.price) AS amount
        FROM {item_from(f)} WHERE {where} GROUP BY i.order_id
    ) filtered_items ON filtered_items.order_id = o.order_id"""
    return source, "COALESCE(filtered_items.amount, 0)"


def period_expr(db: Session, column: str, grain: str = "month") -> str:
    """Dialect-aware grouping expression for `column` (fixed grain whitelist)."""
    if grain not in GRAINS:
        raise ValueError(f"unsupported grain: {grain}")
    dialect = db.get_bind().dialect.name
    if grain == "quarter":
        if dialect == "postgresql":
            return f"to_char({column}, 'YYYY') || '-Q' || EXTRACT(QUARTER FROM {column})::text"
        if dialect in {"mysql", "mariadb"}:
            return f"CONCAT(YEAR({column}), '-Q', QUARTER({column}))"
        return f"strftime('%Y', {column}) || '-Q' || CAST((CAST(strftime('%m', {column}) AS INTEGER) + 2) / 3 AS INTEGER)"
    fmt = {
        "day": "%Y-%m-%d",
        "week": "%Y-W%W",
        "month": "%Y-%m",
        "year": "%Y",
    }[grain]
    if dialect == "postgresql":
        pg_fmt = {
            "day": "YYYY-MM-DD",
            "week": 'IYYY-"W"IW',
            "month": "YYYY-MM",
            "year": "YYYY",
        }[grain]
        return f"to_char({column}, '{pg_fmt}')"
    if dialect in {"mysql", "mariadb"}:
        return f"date_format({column}, '{fmt}')"
    return f"strftime('{fmt}', {column})"


def date_diff_expr(db: Session, later: str, earlier: str) -> str:
    """Dialect-aware day difference between two date columns."""
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return f"(({later})::date - ({earlier})::date)"
    if dialect in {"mysql", "mariadb"}:
        return f"DATEDIFF({later}, {earlier})"
    return f"julianday({later}) - julianday({earlier})"


def median_expr(
    db: Session,
    column: str,
    scope_where: str,
    from_sql: Optional[str] = None,
    params: Optional[dict] = None,
) -> tuple[str, dict]:
    """Median of `column` over rows matching `scope_where`.

    Implemented with window functions, which SQLite and PostgreSQL both
    support. NULLs must already be excluded by `scope_where`. `from_sql` is
    the FROM clause to scan (pass `order_from(f)` so dimension joins are only
    paid for when the scope references them).
    """
    return (
        f"""
        WITH scoped AS (
            SELECT {column} AS v
            FROM {from_sql or "fact_orders o"}
            WHERE {scope_where}
        ),
        ranked AS (
            SELECT v, ROW_NUMBER() OVER (ORDER BY v) AS rn, COUNT(*) OVER () AS total
            FROM scoped
            WHERE v IS NOT NULL
        )
        SELECT AVG(v) AS median FROM ranked
        WHERE rn IN ((total + 1) / 2, (total + 2) / 2)
        """,
        params or {},
    )
