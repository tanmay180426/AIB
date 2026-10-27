"""Filter-aware metric queries - the single source of truth for analytics.

Every page (Dashboard, Sales, Orders, Customers, Products, Sellers, Delivery)
derives its numbers from these functions, so the same metric always reconciles
across pages for the same filter context (see docs/ANALYTICS.md).

Rules:
- All values come from the authorized selected dataset; nothing is fabricated.
- Aggregation happens in SQL (SUM/COUNT/AVG/GROUP BY) - rows are never loaded
  into Python for computation.
- Every dynamic value is bound as a SQL parameter.
"""

from __future__ import annotations

from app.analytics.tabular import dataset_metric

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.filters import (
    Filters,
    date_diff_expr,
    item_from,
    item_where,
    median_expr,
    order_from,
    order_where,
    order_monetary_scope,
    period_expr,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rows(db: Session, sql: str, params: Optional[dict] = None) -> list[dict]:
    return [dict(r) for r in db.execute(text(sql), params or {}).mappings().all()]


def _one(db: Session, sql: str, params: Optional[dict] = None) -> dict:
    return dict(db.execute(text(sql), params or {}).mappings().one())


def _round(value, digits: int = 2):
    return round(float(value), digits) if value is not None else None


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _with_share(rows: list[dict], value_key: str, total: float) -> list[dict]:
    """Attach share_pct = value / total (total must be the FULL filtered total,
    not the sum of a truncated top-N list)."""
    for r in rows:
        r["share_pct"] = _pct(float(r.get(value_key) or 0), total)
    return rows


def _revenue_total(db: Session, f: Filters) -> float:
    where, params = item_where(f)
    row = _one(
        db, f"SELECT COALESCE(SUM(i.price), 0) AS v FROM {item_from(f)} WHERE {where}", params
    )
    return float(row["v"] or 0.0)


def _orders_total(db: Session, f: Filters) -> int:
    where, params = order_where(f)
    row = _one(db, f"SELECT COUNT(*) AS v FROM {order_from(f)} WHERE {where}", params)
    return int(row["v"] or 0)


def _state_clause(f: Filters) -> tuple[str, dict]:
    if f.customer_state:
        return "c.customer_state = :customer_state", {"customer_state": f.customer_state}
    return "1=1", {}


# ---------------------------------------------------------------------------
# KPI core (shared by Dashboard and every analytics page)
# ---------------------------------------------------------------------------


@dataset_metric
def kpis(db: Session, f: Filters) -> dict:
    """Headline metrics for the current filter context."""
    where, params = order_where(f)
    row = _one(
        db,
        f"""
        SELECT
            COUNT(*) AS total_orders,
            COALESCE(SUM(o.item_revenue), 0) AS total_revenue,
            COALESCE(SUM(o.freight_value), 0) AS total_freight,
            COUNT(DISTINCT o.customer_unique_id) AS unique_customers,
            AVG(o.review_score) AS avg_review_score,
            AVG(CASE WHEN o.order_status = 'delivered' AND o.delivered_customer_date IS NOT NULL
                      AND o.delivery_days >= 0 THEN o.delivery_days END) AS avg_delivery_days,
            SUM(CASE WHEN o.order_status = 'delivered' THEN 1 ELSE 0 END) AS delivered_orders,
            SUM(CASE WHEN o.order_status = 'canceled' THEN 1 ELSE 0 END) AS cancelled_orders,
            SUM(CASE WHEN o.order_status NOT IN ('delivered', 'canceled') THEN 1 ELSE 0 END) AS in_progress_orders,
            SUM(CASE WHEN o.order_status = 'delivered' AND o.delivery_days >= 0 AND o.delivered_customer_date IS NOT NULL
                      AND o.is_late THEN 1 ELSE 0 END) AS late_orders,
            SUM(CASE WHEN o.order_status = 'delivered' AND o.delivery_days >= 0 AND o.delivered_customer_date IS NOT NULL
                      AND o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate,
            SUM(CASE WHEN o.delivered_customer_date IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_delivery
        FROM {order_from(f)}
        WHERE {where}
        """,
        params,
    )

    iwhere, iparams = item_where(f)
    items = _one(
        db,
        f"""
        SELECT
            COUNT(*) AS items_sold,
            COALESCE(SUM(i.price), 0) AS total_revenue,
            COALESCE(SUM(i.freight_value), 0) AS total_freight,
            COUNT(DISTINCT i.product_id) AS products_sold,
            COUNT(DISTINCT i.seller_id) AS active_sellers
        FROM {item_from(f)}
        WHERE {iwhere}
        """,
        iparams,
    )

    # repeat customers: >= 2 orders inside the current filter context
    repeat = _one(
        db,
        f"""
        SELECT COUNT(*) AS repeat_customers FROM (
            SELECT o.customer_unique_id
            FROM {order_from(f)}
            WHERE {where} AND o.customer_unique_id IS NOT NULL
            GROUP BY o.customer_unique_id
            HAVING COUNT(*) >= 2
        ) t
        """,
        params,
    )

    # new customers: customers whose FIRST order ever falls inside the period
    state_sql, state_params = _state_clause(f)
    new_sql = f"""
        SELECT COUNT(*) AS new_customers FROM (
            SELECT o.customer_unique_id AS cid, MIN(o.purchase_date) AS first_order
            FROM {order_from(f)}
            WHERE {{state_sql}}
            GROUP BY o.customer_unique_id
        ) t
        WHERE t.cid IN (
            SELECT o.customer_unique_id FROM {order_from(f)} WHERE {where}
        )
    """.format(
        state_sql=state_sql
    )
    new_params = {**state_params, **params}
    if f.date_from:
        new_sql += " AND t.first_order >= :new_from"
        new_params["new_from"] = f.date_from
    if f.date_to:
        new_sql += " AND t.first_order <= :new_to"
        new_params["new_to"] = f.date_to
    new = _one(db, new_sql, new_params)

    total_orders = int(row["total_orders"] or 0)
    total_revenue = float(items["total_revenue"] or 0.0)
    with_estimate = int(row["orders_with_estimate"] or 0)
    late = int(row["late_orders"] or 0)
    on_time_rate = _pct(with_estimate - late, with_estimate) if with_estimate else None

    median_sql, median_params = median_expr(
        db, "o.delivery_days", f"({where}) AND {DELIVERY_SCOPE}", from_sql=order_from(f), params=params
    )
    median_days = db.execute(text(median_sql), median_params).scalar()

    return {
        "total_orders": total_orders,
        "total_revenue": round(total_revenue, 2),
        "total_freight": round(float(items["total_freight"] or 0.0), 2),
        "avg_order_value": round(total_revenue / total_orders, 2) if total_orders else 0.0,
        "unique_customers": int(row["unique_customers"] or 0),
        "new_customers": int(new["new_customers"] or 0),
        "repeat_customers": int(repeat["repeat_customers"] or 0),
        "items_sold": int(items["items_sold"] or 0),
        "avg_items_per_order": round(int(items["items_sold"] or 0) / total_orders, 2)
        if total_orders
        else 0.0,
        "products_sold": int(items["products_sold"] or 0),
        "active_sellers": int(items["active_sellers"] or 0),
        "avg_review_score": _round(row["avg_review_score"], 3),
        "avg_delivery_days": _round(row["avg_delivery_days"], 2),
        "median_delivery_days": _round(median_days, 2),
        "delivered_orders": int(row["delivered_orders"] or 0),
        "cancelled_orders": int(row["cancelled_orders"] or 0),
        "in_progress_orders": int(row["in_progress_orders"] or 0),
        "orders_with_delivery": int(row["orders_with_delivery"] or 0),
        "orders_with_estimate": with_estimate,
        "late_orders": late,
        "on_time_rate": on_time_rate,
        "late_rate": _pct(late, with_estimate) if with_estimate else None,
    }


# ---------------------------------------------------------------------------
# time series
# ---------------------------------------------------------------------------


@dataset_metric
def time_series(db: Session, f: Filters, grain: str = "month", limit: int = 400) -> list[dict]:
    """Orders/customers (order grain) + revenue (item grain) per period.

    Both grains are merged on the period key so revenue always sums to the
    KPI total for the same filters.
    """
    where, params = order_where(f)
    orders = _rows(
        db,
        f"""
        SELECT * FROM (
            SELECT {period_expr(db, "o.purchase_date", grain)} AS period,
                   COUNT(*) AS orders,
                   COUNT(DISTINCT o.customer_unique_id) AS customers
            FROM {order_from(f)}
            WHERE {where}
            GROUP BY period
            ORDER BY period DESC
            LIMIT :limit
        ) t
        ORDER BY period ASC
        """,
        {**params, "limit": limit},
    )

    iwhere, iparams = item_where(f)
    revenue = {
        r["period"]: r["revenue"]
        for r in _rows(
            db,
            f"""
            SELECT {period_expr(db, "i.purchase_date", grain)} AS period,
                   COALESCE(SUM(i.price), 0) AS revenue
            FROM {item_from(f)}
            WHERE {iwhere}
            GROUP BY period
            """,
            iparams,
        )
    }

    return [
        {
            "period": r["period"],
            "orders": int(r["orders"] or 0),
            "customers": int(r["customers"] or 0),
            "revenue": round(float(revenue.get(r["period"], 0.0)), 2),
        }
        for r in orders
    ]


# ---------------------------------------------------------------------------
# rankings / distributions
# ---------------------------------------------------------------------------


@dataset_metric
def revenue_by_category(db: Session, f: Filters, limit: int = 20) -> list[dict]:
    where, params = item_where(f)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(i.product_category_name_en, 'unknown') AS category,
               COALESCE(SUM(i.price), 0) AS revenue,
               COUNT(*) AS quantity,
               COUNT(DISTINCT i.order_id) AS orders
        FROM {item_from(f)}
        WHERE {where}
        GROUP BY category
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
    return _with_share(rows, "revenue", _revenue_total(db, f))


def revenue_by_state(db: Session, f: Filters, dimension: str = "customer", limit: int = 30) -> list[dict]:
    """Revenue by customer state or seller state (item grain)."""
    where, params = item_where(f)
    if dimension == "seller":
        group_col, label = "s.seller_state", "seller_state"
        count_col = "COUNT(DISTINCT i.seller_id) AS sellers"
        from_sql = item_from(f, with_seller=True)
    else:
        group_col, label = "c.customer_state", "state"
        count_col = "COUNT(DISTINCT i.customer_unique_id) AS customers"
        from_sql = item_from(f, with_customer=True)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE({group_col}, 'unknown') AS {label},
               COALESCE(SUM(i.price), 0) AS revenue,
               COUNT(DISTINCT i.order_id) AS orders,
               {count_col}
        FROM {from_sql}
        WHERE {where}
        GROUP BY {group_col}
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
    return _with_share(rows, "revenue", _revenue_total(db, f))


@dataset_metric
def orders_by_status(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(o.order_status, 'unknown') AS status, COUNT(*) AS orders
        FROM {order_from(f)}
        WHERE {where}
        GROUP BY o.order_status
        ORDER BY orders DESC
        """,
        params,
    )
    for r in rows:
        r["orders"] = int(r["orders"] or 0)
    total = sum(r["orders"] for r in rows)
    for r in rows:
        r["share_pct"] = _pct(r["orders"], total)
    return rows


@dataset_metric
def status_over_time(db: Session, f: Filters, grain: str = "month", limit: int = 120) -> list[dict]:
    where, params = order_where(f)
    return _rows(
        db,
        f"""
        SELECT * FROM (
            SELECT {period_expr(db, "o.purchase_date", grain)} AS period,
                   COALESCE(o.order_status, 'unknown') AS status,
                   COUNT(*) AS orders
            FROM {order_from(f)}
            WHERE {where}
            GROUP BY period, o.order_status
            ORDER BY period DESC
            LIMIT :limit
        ) t
        ORDER BY period ASC
        """,
        {**params, "limit": limit},
    )


def review_distribution(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    rows = _rows(
        db,
        f"""
        SELECT CAST(ROUND(o.review_score) AS INTEGER) AS score, COUNT(*) AS orders
        FROM {order_from(f)}
        WHERE {where} AND o.review_score IS NOT NULL
        GROUP BY CAST(ROUND(o.review_score) AS INTEGER)
        ORDER BY score
        """,
        params,
    )
    total = sum(int(r["orders"] or 0) for r in rows)
    out = []
    for score in range(1, 6):
        match = next((r for r in rows if int(r["score"]) == score), None)
        count = int(match["orders"]) if match else 0
        out.append({"score": score, "orders": count, "share_pct": _pct(count, total)})
    return out


def top_customer_states(db: Session, f: Filters, limit: int = 10) -> list[dict]:
    """Customer concentration by state (customer counts)."""
    where, params = order_where(f)
    source, amount = order_monetary_scope(f, with_customer=True)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(c.customer_state, 'unknown') AS state,
               COUNT(DISTINCT o.customer_unique_id) AS customers,
               COUNT(*) AS orders,
               COALESCE(SUM({amount}), 0) AS revenue
        FROM {source}
        WHERE {where}
        GROUP BY c.customer_state
        ORDER BY customers DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
    return rows


def payment_types(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    source, amount = order_monetary_scope(f, with_customer=False)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(o.payment_type, 'unknown') AS payment_type,
               COUNT(*) AS orders,
               COALESCE(SUM({amount}), 0) AS revenue,
               COALESCE(AVG(o.payment_installments), 0) AS avg_installments
        FROM {source}
        WHERE {where}
        GROUP BY o.payment_type
        ORDER BY revenue DESC
        """,
        params,
    )
    total = sum(float(r["revenue"] or 0) for r in rows)
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["orders"] = int(r["orders"] or 0)
        r["avg_installments"] = round(float(r["avg_installments"] or 0), 1)
        r["share_pct"] = _pct(float(r["revenue"]), total)
    return rows


def payment_installments(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    source, amount = order_monetary_scope(f, with_customer=False)
    rows = _rows(
        db,
        f"""
        SELECT
            CASE
                WHEN o.payment_installments IS NULL OR o.payment_installments <= 1 THEN '1'
                WHEN o.payment_installments = 2 THEN '2'
                WHEN o.payment_installments BETWEEN 3 AND 4 THEN '3-4'
                WHEN o.payment_installments BETWEEN 5 AND 6 THEN '5-6'
                WHEN o.payment_installments BETWEEN 7 AND 10 THEN '7-10'
                ELSE '11+'
            END AS installments,
            COUNT(*) AS orders,
            COALESCE(SUM({amount}), 0) AS revenue
        FROM {source}
        WHERE {where}
        GROUP BY installments
        ORDER BY orders DESC
        """,
        params,
    )
    for r in rows:
        r["orders"] = int(r["orders"] or 0)
        r["revenue"] = round(float(r["revenue"] or 0), 2)
    return _with_share(rows, "orders", sum(r["orders"] for r in rows))


def order_value_distribution(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    rows = _rows(
        db,
        f"""
        SELECT CASE
                   WHEN COALESCE(o.item_revenue, 0) < 50 THEN 'R$ 0-49'
                   WHEN o.item_revenue < 100 THEN 'R$ 50-99'
                   WHEN o.item_revenue < 200 THEN 'R$ 100-199'
                   WHEN o.item_revenue < 500 THEN 'R$ 200-499'
                   WHEN o.item_revenue < 1000 THEN 'R$ 500-999'
                   ELSE 'R$ 1000+'
               END AS bucket,
               COUNT(*) AS orders
        FROM {order_from(f)}
        WHERE {where}
        GROUP BY bucket
        ORDER BY orders DESC
        """,
        params,
    )
    for r in rows:
        r["orders"] = int(r["orders"] or 0)
    return _with_share(rows, "orders", sum(r["orders"] for r in rows))


def items_per_order(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    rows = _rows(
        db,
        f"""
        SELECT CASE
                   WHEN n = 1 THEN '1 item'
                   WHEN n = 2 THEN '2 items'
                   WHEN n BETWEEN 3 AND 4 THEN '3-4 items'
                   WHEN n BETWEEN 5 AND 8 THEN '5-8 items'
                   ELSE '9+ items'
               END AS bucket,
               COUNT(*) AS orders
        FROM (
            SELECT o.order_id AS order_id, COUNT(i.row_id) AS n
            FROM {order_from(f)}
            LEFT JOIN fact_order_items i ON i.order_id = o.order_id
            WHERE {where}
            GROUP BY o.order_id
        ) t
        GROUP BY bucket
        ORDER BY orders DESC
        """,
        params,
    )
    for r in rows:
        r["orders"] = int(r["orders"] or 0)
    return _with_share(rows, "orders", sum(r["orders"] for r in rows))


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------


def customers_by_state(db: Session, f: Filters, limit: int = 30) -> list[dict]:
    where, params = order_where(f)
    source, amount = order_monetary_scope(f, with_customer=True)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(c.customer_state, 'unknown') AS state,
               COUNT(DISTINCT o.customer_unique_id) AS customers,
               COUNT(*) AS orders,
               COALESCE(SUM({amount}), 0) AS revenue
        FROM {source}
        WHERE {where}
        GROUP BY c.customer_state
        ORDER BY customers DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["orders"] = int(r["orders"] or 0)
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["avg_order_value"] = round(r["revenue"] / r["orders"], 2) if r["orders"] else 0.0
    return rows


def customer_spend_distribution(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    source, amount = order_monetary_scope(f, with_customer=False)
    rows = _rows(
        db,
        f"""
        SELECT bucket, COUNT(*) AS customers, SUM(spend) AS revenue FROM (
            SELECT o.customer_unique_id,
                   SUM({amount}) AS spend,
                   CASE
                       WHEN SUM({amount}) < 100 THEN 'R$ 0-99'
                       WHEN SUM({amount}) < 300 THEN 'R$ 100-299'
                       WHEN SUM({amount}) < 600 THEN 'R$ 300-599'
                       WHEN SUM({amount}) < 1000 THEN 'R$ 600-999'
                       WHEN SUM({amount}) < 2000 THEN 'R$ 1000-1999'
                       ELSE 'R$ 2000+'
                   END AS bucket
            FROM {source}
            WHERE {where}
            GROUP BY o.customer_unique_id
        ) t
        GROUP BY bucket
        ORDER BY customers DESC
        """,
        params,
    )
    total = sum(int(r["customers"] or 0) for r in rows)
    for r in rows:
        r["customers"] = int(r["customers"] or 0)
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["share_pct"] = _pct(r["customers"], total)
    return rows


def order_frequency(db: Session, f: Filters) -> list[dict]:
    where, params = order_where(f)
    rows = _rows(
        db,
        f"""
        SELECT bucket, COUNT(*) AS customers FROM (
            SELECT o.customer_unique_id,
                   CASE
                       WHEN COUNT(*) = 1 THEN '1 order'
                       WHEN COUNT(*) = 2 THEN '2 orders'
                       WHEN COUNT(*) BETWEEN 3 AND 4 THEN '3-4 orders'
                       ELSE '5+ orders'
                   END AS bucket
            FROM {order_from(f)}
            WHERE {where}
            GROUP BY o.customer_unique_id
        ) t
        GROUP BY bucket
        ORDER BY customers DESC
        """,
        params,
    )
    total = sum(int(r["customers"] or 0) for r in rows)
    for r in rows:
        r["customers"] = int(r["customers"] or 0)
        r["share_pct"] = _pct(r["customers"], total)
    return rows


def top_customers(db: Session, f: Filters, limit: int = 20) -> list[dict]:
    where, params = order_where(f)
    source, amount = order_monetary_scope(f, with_customer=True)
    rows = _rows(
        db,
        f"""
        SELECT SUBSTR(o.customer_unique_id, 1, 8) AS customer,
               COALESCE(c.customer_state, 'unknown') AS state,
               COUNT(*) AS orders,
               COALESCE(SUM({amount}), 0) AS revenue,
               MAX(o.purchase_date) AS last_order
        FROM {source}
        WHERE {where}
        GROUP BY o.customer_unique_id, c.customer_state
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
    return _with_share(rows, "revenue", _revenue_total(db, f))


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


def products_by_category(db: Session, f: Filters, limit: int = 20) -> list[dict]:
    where, params = item_where(f)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(i.product_category_name_en, 'unknown') AS category,
               COALESCE(SUM(i.price), 0) AS revenue,
               COUNT(*) AS quantity,
               COUNT(DISTINCT i.order_id) AS orders,
               COUNT(DISTINCT i.product_id) AS products,
               AVG(i.price) AS avg_price,
               AVG(p.product_weight_g) AS avg_weight_g
        FROM {item_from(f, with_product=True)}
        WHERE {where}
        GROUP BY category
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["avg_price"] = _round(r["avg_price"], 2)
        r["avg_weight_g"] = _round(r["avg_weight_g"], 1)
    return _with_share(rows, "revenue", _revenue_total(db, f))


def top_products(db: Session, f: Filters, order_by: str = "revenue", limit: int = 20) -> list[dict]:
    order_col = {"revenue": "revenue", "quantity": "quantity", "orders": "orders"}[order_by]
    where, params = item_where(f)
    rows = _rows(
        db,
        f"""
        SELECT SUBSTR(i.product_id, 1, 8) AS product,
               COALESCE(i.product_category_name_en, 'unknown') AS category,
               COALESCE(SUM(i.price), 0) AS revenue,
               COUNT(*) AS quantity,
               COUNT(DISTINCT i.order_id) AS orders,
               AVG(i.price) AS avg_price
        FROM {item_from(f)}
        WHERE {where}
        GROUP BY i.product_id, category
        ORDER BY {order_col} DESC, revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["avg_price"] = _round(r["avg_price"], 2)
    return rows


def catalog_stats(db: Session) -> dict:
    """Whole-catalog context (unfiltered): product count and category count."""
    row = _one(
        db,
        """
        SELECT COUNT(*) AS products,
               COUNT(DISTINCT product_category_name_en) AS categories,
               AVG(product_weight_g) AS avg_weight_g,
               SUM(CASE WHEN product_weight_g IS NOT NULL THEN 1 ELSE 0 END) AS products_with_weight
        FROM dim_product
        """,
    )
    return {
        "products": int(row["products"] or 0),
        "categories": int(row["categories"] or 0),
        "avg_weight_g": _round(row["avg_weight_g"], 1),
        "products_with_weight": int(row["products_with_weight"] or 0),
    }


# ---------------------------------------------------------------------------
# sellers
# ---------------------------------------------------------------------------


def top_sellers(db: Session, f: Filters, limit: int = 20) -> list[dict]:
    where, params = item_where(f)
    rows = _rows(
        db,
        f"""
        SELECT SUBSTR(i.seller_id, 1, 8) AS seller,
               COALESCE(s.seller_state, 'unknown') AS state,
               COUNT(DISTINCT i.order_id) AS orders,
               COUNT(*) AS quantity,
               COALESCE(SUM(i.price), 0) AS revenue,
               AVG(o.review_score) AS avg_review_score,
               AVG(o.delivery_days) AS avg_delivery_days,
               SUM(CASE WHEN o.is_late THEN 1 ELSE 0 END) AS late_orders,
               SUM(CASE WHEN o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate
        FROM {item_from(f, with_order=True, with_seller=True)}
        WHERE {where}
        GROUP BY i.seller_id, s.seller_state
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["avg_review_score"] = _round(r["avg_review_score"], 2)
        r["avg_delivery_days"] = _round(r["avg_delivery_days"], 1)
        est = int(r["orders_with_estimate"] or 0)
        late = int(r["late_orders"] or 0)
        r["on_time_rate"] = _pct(est - late, est) if est else None
    return _with_share(rows, "revenue", _revenue_total(db, f))


def sellers_by_state(db: Session, f: Filters, limit: int = 30) -> list[dict]:
    where, params = item_where(f)
    rows = _rows(
        db,
        f"""
        SELECT COALESCE(s.seller_state, 'unknown') AS state,
               COUNT(DISTINCT i.seller_id) AS sellers,
               COUNT(DISTINCT i.order_id) AS orders,
               COALESCE(SUM(i.price), 0) AS revenue
        FROM {item_from(f, with_seller=True)}
        WHERE {where}
        GROUP BY s.seller_state
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    )
    for r in rows:
        r["orders"] = int(r["orders"] or 0)
        r["sellers"] = int(r["sellers"] or 0)
        r["revenue"] = round(float(r["revenue"] or 0), 2)
        r["revenue_per_seller"] = round(r["revenue"] / r["sellers"], 2) if r["sellers"] else 0.0
    return _with_share(rows, "revenue", _revenue_total(db, f))


@dataset_metric
def top_sellers_series(db: Session, f: Filters, top_n: int = 5, grain: str = "month", limit: int = 400) -> list[dict]:
    """Rank on the complete filtered item scope before bounding chart points."""
    where, params = item_where(f)
    return _rows(db, f"""
        WITH leaders AS (
            SELECT i.seller_id, SUM(i.price) AS revenue
            FROM {item_from(f)} WHERE {where} AND i.seller_id IS NOT NULL
            GROUP BY i.seller_id ORDER BY revenue DESC, i.seller_id LIMIT :top_n
        )
        SELECT period, seller, ROUND(revenue, 2) AS revenue FROM (
            SELECT {period_expr(db, "i.purchase_date", grain)} AS period,
                   i.seller_id AS seller, SUM(i.price) AS revenue
            FROM {item_from(f)} JOIN leaders ON leaders.seller_id = i.seller_id
            WHERE {where}
            GROUP BY period, i.seller_id ORDER BY period DESC, i.seller_id LIMIT :limit
        ) chart_points ORDER BY period, seller
        """, {**params, "top_n": top_n, "limit": limit})


# ---------------------------------------------------------------------------
# delivery
# ---------------------------------------------------------------------------

DELIVERY_SCOPE = (
    "o.delivered_customer_date IS NOT NULL AND o.order_status = 'delivered' AND o.delivery_days >= 0"
)


def delivery_metrics(db: Session, f: Filters) -> dict:
    where, params = order_where(f)
    scope = f"({where}) AND {DELIVERY_SCOPE}"

    stats = _one(
        db,
        f"""
        SELECT
            COUNT(*) AS orders_in_scope,
            AVG(o.delivery_days) AS avg_delivery_days,
            SUM(CASE WHEN o.is_late THEN 1 ELSE 0 END) AS late_orders,
            SUM(CASE WHEN o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate,
            AVG({date_diff_expr(db, "o.delivered_customer_date", "o.estimated_delivery_date")}) AS avg_delay_days,
            MIN(o.delivery_days) AS min_delivery_days,
            MAX(o.delivery_days) AS max_delivery_days
        FROM {order_from(f)}
        WHERE {scope}
        """,
        params,
    )

    quality = _one(
        db,
        f"""
        SELECT
            SUM(CASE WHEN o.delivered_customer_date IS NULL THEN 1 ELSE 0 END) AS orders_without_delivery,
            SUM(CASE WHEN o.delivered_customer_date IS NOT NULL
                      AND o.is_late IS NULL THEN 1 ELSE 0 END) AS orders_without_estimate,
            SUM(CASE WHEN o.order_status = 'canceled' THEN 1 ELSE 0 END) AS cancelled_orders
        FROM {order_from(f)}
        WHERE {where}
        """,
        params,
    )

    median_sql, median_params = median_expr(
        db, "o.delivery_days", scope, from_sql=order_from(f), params=params
    )
    median_days = db.execute(text(median_sql), median_params).scalar()

    in_scope = int(stats["orders_in_scope"] or 0)
    with_estimate = int(stats["orders_with_estimate"] or 0)
    late = int(stats["late_orders"] or 0)

    distribution = _rows(
        db,
        f"""
        SELECT CASE
                   WHEN o.delivery_days < 7 THEN '0-6 days'
                   WHEN o.delivery_days < 14 THEN '7-13 days'
                   WHEN o.delivery_days < 21 THEN '14-20 days'
                   WHEN o.delivery_days < 30 THEN '21-29 days'
                   WHEN o.delivery_days < 45 THEN '30-44 days'
                   ELSE '45+ days'
               END AS bucket,
               COUNT(*) AS orders
        FROM {order_from(f)}
        WHERE {scope}
        GROUP BY bucket
        ORDER BY orders DESC
        """,
        params,
    )
    for r in distribution:
        r["orders"] = int(r["orders"] or 0)

    over_time = _rows(
        db,
        f"""
        SELECT period, COUNT(*) AS orders,
               AVG(o.delivery_days) AS avg_delivery_days,
               SUM(CASE WHEN o.is_late THEN 1 ELSE 0 END) AS late_orders,
               SUM(CASE WHEN o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate
        FROM (
            SELECT {period_expr(db, "o.purchase_date", "month")} AS period, o.*
            FROM {order_from(f)}
            WHERE {scope}
        ) o
        GROUP BY period
        ORDER BY period ASC
        LIMIT 400
        """,
        params,
    )
    for r in over_time:
        est = int(r["orders_with_estimate"] or 0)
        r["orders"] = int(r["orders"] or 0)
        r["avg_delivery_days"] = _round(r["avg_delivery_days"], 2)
        r["on_time_rate"] = _pct(est - int(r["late_orders"] or 0), est) if est else None

    by_state = _rows(
        db,
        f"""
        SELECT COALESCE(c.customer_state, 'unknown') AS state,
               COUNT(*) AS orders,
               AVG(o.delivery_days) AS avg_delivery_days,
               SUM(CASE WHEN o.is_late THEN 1 ELSE 0 END) AS late_orders,
               SUM(CASE WHEN o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate
        FROM {order_from(f, with_customer=True)}
        WHERE {scope}
        GROUP BY c.customer_state
        ORDER BY orders DESC
        LIMIT 30
        """,
        params,
    )
    for r in by_state:
        est = int(r["orders_with_estimate"] or 0)
        r["orders"] = int(r["orders"] or 0)
        r["avg_delivery_days"] = _round(r["avg_delivery_days"], 2)
        r["on_time_rate"] = _pct(est - int(r["late_orders"] or 0), est) if est else None

    # Membership is distinct per order/group before joining delivery facts.
    # Multiple items from one seller/category must not weight that order's
    # duration or lateness more heavily than another eligible order.
    iwhere, iparams = item_where(f)
    seller_membership = f"""SELECT DISTINCT i.order_id, i.seller_id,
        COALESCE(s.seller_state, 'unknown') AS state
        FROM {item_from(f, with_seller=True)} WHERE {iwhere}"""
    by_seller = _rows(
        db,
        f"""
        SELECT SUBSTR(membership.seller_id, 1, 8) AS seller,
               membership.state AS state,
               COUNT(*) AS orders,
               AVG(o.delivery_days) AS avg_delivery_days,
               SUM(CASE WHEN o.is_late THEN 1 ELSE 0 END) AS late_orders,
               SUM(CASE WHEN o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate
        FROM {order_from(f)}
        JOIN ({seller_membership}) membership ON membership.order_id = o.order_id
        WHERE {scope}
        GROUP BY membership.seller_id, membership.state
        HAVING COUNT(*) >= 20
        ORDER BY orders DESC
        LIMIT 50
        """,
        {**params, **iparams},
    )
    for r in by_seller:
        est = int(r["orders_with_estimate"] or 0)
        r["orders"] = int(r["orders"] or 0)
        r["avg_delivery_days"] = _round(r["avg_delivery_days"], 2)
        r["on_time_rate"] = _pct(est - int(r["late_orders"] or 0), est) if est else None

    category_membership = f"""SELECT DISTINCT i.order_id,
        COALESCE(i.product_category_name_en, 'unknown') AS category
        FROM {item_from(f)} WHERE {iwhere}"""
    by_category = _rows(
        db,
        f"""
        SELECT membership.category AS category,
               COUNT(*) AS orders,
               AVG(o.delivery_days) AS avg_delivery_days,
               SUM(CASE WHEN o.is_late THEN 1 ELSE 0 END) AS late_orders,
               SUM(CASE WHEN o.is_late IS NOT NULL THEN 1 ELSE 0 END) AS orders_with_estimate
        FROM {order_from(f)}
        JOIN ({category_membership}) membership ON membership.order_id = o.order_id
        WHERE {scope}
        GROUP BY category
        ORDER BY orders DESC
        LIMIT 20
        """,
        {**params, **iparams},
    )
    for r in by_category:
        est = int(r["orders_with_estimate"] or 0)
        r["orders"] = int(r["orders"] or 0)
        r["avg_delivery_days"] = _round(r["avg_delivery_days"], 2)
        r["on_time_rate"] = _pct(est - int(r["late_orders"] or 0), est) if est else None

    return {
        "kpis": {
            "orders_in_scope": in_scope,
            "avg_delivery_days": _round(stats["avg_delivery_days"], 2),
            "median_delivery_days": _round(median_days, 2),
            "min_delivery_days": _round(stats["min_delivery_days"], 2),
            "max_delivery_days": _round(stats["max_delivery_days"], 2),
            "on_time_rate": _pct(with_estimate - late, with_estimate) if with_estimate else None,
            "late_rate": _pct(late, with_estimate) if with_estimate else None,
            "avg_delay_days": _round(stats["avg_delay_days"], 2),
        },
        "data_quality": {
            "orders_without_delivery": int(quality["orders_without_delivery"] or 0),
            "orders_without_estimate": int(quality["orders_without_estimate"] or 0),
            "cancelled_orders_excluded": int(quality["cancelled_orders"] or 0),
            "note": "Orders without a delivered timestamp are excluded, never counted as late. "
            "Cancelled orders are excluded from delivery metrics.",
        },
        "duration_distribution": distribution,
        "over_time": over_time,
        "by_state": by_state,
        "by_seller": by_seller,
        "by_category": by_category,
    }


# ---------------------------------------------------------------------------
# combined views
# ---------------------------------------------------------------------------


@dataset_metric
def sales(db: Session, f: Filters) -> dict:
    k = kpis(db, f)
    categories = revenue_by_category(db, f)
    return {
        "kpis": k,
        "revenue_series": time_series(db, f, "month"),
        "orders_by_category": categories,
        "revenue_by_customer_state": revenue_by_state(db, f, "customer"),
        "revenue_by_seller_state": revenue_by_state(db, f, "seller"),
        "revenue_by_payment_type": payment_types(db, f),
        "top_categories": categories[:10],
        "top_products": top_products(db, f, "revenue"),
        "top_sellers": top_sellers(db, f, limit=10),
        "top_states": revenue_by_state(db, f, "customer", limit=10),
    }


@dataset_metric
def orders(db: Session, f: Filters) -> dict:
    return {
        "kpis": kpis(db, f),
        "by_status": orders_by_status(db, f),
        "status_over_time": status_over_time(db, f),
        "orders_series": time_series(db, f, "month"),
        "items_per_order": items_per_order(db, f),
        "payment_types": payment_types(db, f),
        "payment_installments": payment_installments(db, f),
        "order_value_distribution": order_value_distribution(db, f),
    }


@dataset_metric
def customers(db: Session, f: Filters) -> dict:
    k = kpis(db, f)
    unique = k["unique_customers"]
    repeat = k["repeat_customers"]
    return {
        "kpis": {
            **k,
            "repeat_rate": _pct(repeat, unique) if unique else 0.0,
            "avg_spend_per_customer": round(k["total_revenue"] / unique, 2) if unique else 0.0,
            "avg_orders_per_customer": round(k["total_orders"] / unique, 2) if unique else 0.0,
        },
        "by_state": customers_by_state(db, f),
        "spend_distribution": customer_spend_distribution(db, f),
        "order_frequency": order_frequency(db, f),
        "top_customers": top_customers(db, f),
        "top_states": top_customer_states(db, f),
        "new_vs_repeat": [
            {"segment": "Single-purchase customers", "customers": unique - repeat},
            {"segment": "Repeat customers", "customers": repeat},
        ],
    }


@dataset_metric
def products(db: Session, f: Filters) -> dict:
    k = kpis(db, f)
    category_rows = products_by_category(db, f)
    where, params = item_where(f)
    category_count = db.scalar(text(
        f"SELECT COUNT(DISTINCT COALESCE(i.product_category_name_en, 'unknown')) "
        f"FROM {item_from(f)} WHERE {where}"
    ), params)
    quantity = k["items_sold"]
    return {
        "kpis": {
            **k,
            "category_count": category_count,
            "catalog": catalog_stats(db),
            "avg_product_revenue": round(k["total_revenue"] / k["products_sold"], 2)
            if k["products_sold"]
            else 0.0,
            "avg_price": round(k["total_revenue"] / quantity, 2) if quantity else 0.0,
        },
        "by_category": category_rows,
        "top_by_revenue": top_products(db, f, "revenue"),
        "top_by_quantity": top_products(db, f, "quantity"),
        "top_by_orders": top_products(db, f, "orders"),
    }


@dataset_metric
def sellers(db: Session, f: Filters) -> dict:
    k = kpis(db, f)
    n_sellers = k["active_sellers"]
    return {
        "kpis": {
            **k,
            "avg_revenue_per_seller": round(k["total_revenue"] / n_sellers, 2) if n_sellers else 0.0,
            "avg_orders_per_seller": round(k["total_orders"] / n_sellers, 2) if n_sellers else 0.0,
            "avg_review_per_seller": k["avg_review_score"],
        },
        "by_state": sellers_by_state(db, f),
        "top_sellers": top_sellers(db, f),
        "top_sellers_series": top_sellers_series(db, f),
        "top_states": revenue_by_state(db, f, "seller", limit=10),
    }


@dataset_metric
def delivery(db: Session, f: Filters) -> dict:
    return delivery_metrics(db, f)


@dataset_metric
def overview(db: Session, f: Filters) -> dict:
    """Everything the Dashboard needs, in one filtered request."""
    delivery_view = delivery_metrics(db, f)
    return {
        "filters": f.as_dict(),
        "kpis": kpis(db, f),
        "revenue_series": time_series(db, f, "month"),
        "orders_by_status": orders_by_status(db, f),
        "revenue_by_category": revenue_by_category(db, f),
        "top_customer_states": top_customer_states(db, f),
        "review_distribution": review_distribution(db, f),
        "delivery": {
            "kpis": delivery_view["kpis"],
            "duration_distribution": delivery_view["duration_distribution"][:4],
        },
        "revenue_by_payment_type": payment_types(db, f),
    }


@dataset_metric
def filter_options(db: Session) -> dict:
    """Distinct filter values for the frontend filter controls."""
    def values(sql: str) -> list[str]:
        return [r[0] for r in db.execute(text(sql)).all() if r[0]]

    date_range = _one(
        db,
        "SELECT MIN(purchase_date) AS min_date, MAX(purchase_date) AS max_date FROM fact_orders",
    )
    return {
        "categories": values(
            "SELECT DISTINCT product_category_name_en FROM dim_product "
            "WHERE product_category_name_en IS NOT NULL ORDER BY 1"
        ),
        "customer_states": values(
            "SELECT DISTINCT customer_state FROM dim_customer "
            "WHERE customer_state IS NOT NULL ORDER BY 1"
        ),
        "seller_states": values(
            "SELECT DISTINCT seller_state FROM dim_seller "
            "WHERE seller_state IS NOT NULL ORDER BY 1"
        ),
        "order_statuses": values(
            "SELECT DISTINCT order_status FROM fact_orders "
            "WHERE order_status IS NOT NULL ORDER BY 1"
        ),
        "payment_types": values(
            "SELECT DISTINCT payment_type FROM fact_orders "
            "WHERE payment_type IS NOT NULL ORDER BY 1"
        ),
        "review_scores": [1, 2, 3, 4, 5],
        "date_range": {"min": str(date_range["min_date"] or ""), "max": str(date_range["max_date"] or "")},
    }
