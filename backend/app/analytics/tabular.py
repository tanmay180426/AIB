"""Typed-table source adapter for the existing analytics metric layer.

SQL aggregation stays in the warehouse; only bounded aggregate results leave
the database. No source column name is interpolated into a query.
"""
from __future__ import annotations

import json
from functools import wraps

from fastapi import HTTPException
from sqlalchemy import DateTime, String, case, cast, func, select

from app.analytics.filters import Filters, period_expr
from app.services.datasets import key, storage_table


def _technical_column(column):
    name = "".join(ch.lower() for ch in str(column.get("name", "")) if ch.isalnum())
    return (column.get("role") == "technical_metadata" or
            name in {"generationseed", "sourcedataflag", "sourceflag", "dataorigin", "datasource",
                     "generationversion", "syntheticversion", "synthetic", "issynthetic", "syntheticflag",
                     "generationflag", "generatedflag", "rowid", "index"} or
            name.endswith("generationseed"))


class TabularSource:
    def __init__(self, db, f=None):
        self.db = db
        self.ds = db.info["dataset"]
        self.table = storage_table(self.ds, db)
        self.columns = self.ds.profile["columns"]
        self.by_name = {c["name"]: self.table.c[c["storage"]] for c in self.columns}
        self.fields = self.ds.semantics.get("fields", {})
        self.fields = dict(self.fields)
        # Existing dataset registry records predate the explicit order_count
        # role. Recover only a unique, numeric, known daily-count name without
        # mutating the saved schema or confusing it with an order identifier.
        if "order_count" not in self.fields:
            candidates = [c["name"] for c in self.columns
                          if c.get("dtype") == "numeric" and key(c.get("name", "")) in
                          {"orders", "ordercount", "dailyorders", "totalorders", "numberoforders", "distinctorders"}]
            if len(candidates) == 1:
                self.fields["order_count"] = candidates[0]
        if "user" in self.fields:
            self.fields.setdefault("customer", self.fields["user"])
        self.f = f or Filters()
        self.where = []
        date = self.field("date")
        if self.f.date_from or self.f.date_to:
            if date is None:
                raise HTTPException(422, "Date filters require a confirmed analytical date field.")
            if self.f.date_from:
                self.where.append(date >= self.f.date_from)
            if self.f.date_to:
                self.where.append(date < self.f.date_to + "T99")
        roles = {"category": "category", "customer_state": "location", "seller_state": "seller_location",
                 "order_status": "status", "payment_type": "payment_type", "review_score": "rating"}
        for parameter, role in roles.items():
            value = getattr(self.f, parameter)
            if value is not None:
                column = self.field(role)
                if column is None:
                    raise HTTPException(422, f"{parameter} is unavailable for this dataset.")
                self.where.append(column == value)
        for name, value in json.loads(self.f.column_filters or "{}").items():
            if name not in self.by_name:
                raise HTTPException(422, "A filter field does not belong to this dataset.")
            self.where.append(self.by_name[name] == value)

    def field(self, role):
        return self.by_name.get(self.fields.get(role))

    def statement(self, *expressions):
        return select(*expressions).select_from(self.table).where(*self.where)

    def rows(self, statement):
        return [dict(r) for r in self.db.execute(statement).mappings()]

    def provenance(self):
        """Return compact provenance counts without making provenance a KPI/feature."""
        total = self.scalar(func.count()) or 0
        origin_meta = next((column for column in self.columns
                            if "".join(ch.lower() for ch in column.get("name", "") if ch.isalnum())
                            in {"dataorigin", "datasource"}), None)
        origins = []
        if origin_meta is not None:
            origin = self.by_name[origin_meta["name"]]
            origins = [{"value": str(row["label"]), "rows": int(row["rows"])}
                       for row in self.rows(self.statement(origin.label("label"), func.count().label("rows"))
                                            .where(origin.is_not(None)).group_by(origin).order_by(origin).limit(20))]
        synthetic_meta = next((column for column in self.columns
                               if "".join(ch.lower() for ch in column.get("name", "") if ch.isalnum())
                               in {"synthetic", "issynthetic", "syntheticflag", "generationflag", "generatedflag"}), None)
        synthetic_rows = None
        if synthetic_meta is not None:
            flag = self.by_name[synthetic_meta["name"]]
            normalized = func.lower(cast(flag, String))
            synthetic_rows = int(self.scalar(func.sum(case((normalized.in_(["true", "1", "yes"]), 1), else_=0))) or 0)
        return {"rows": int(total), "origin_field": origin_meta["name"] if origin_meta else None,
                "origins": origins, "synthetic_field": synthetic_meta["name"] if synthetic_meta else None,
                "synthetic_rows": synthetic_rows,
                "synthetic_share_pct": round(100 * synthetic_rows / total, 2) if total and synthetic_rows is not None else None}

    def scalar(self, expression):
        return self.db.scalar(self.statement(expression))

    def count(self, role):
        col = self.field(role)
        return self.scalar(func.count(func.distinct(col))) if col is not None else None

    def amount(self):
        # Currency/amount columns are not item revenue unless the dataset
        # explicitly maps them to the revenue role.
        return self.field("revenue")

    def kpis(self):
        n = self.scalar(func.count())
        amount, quantity, rating = self.field("revenue"), self.field("quantity"), self.field("rating")
        revenue = self.scalar(func.sum(amount)) if amount is not None else None
        order_count = self.field("order_count")
        total_orders = (self.scalar(case((func.count(order_count) == n, func.sum(order_count)), else_=None))
                        if order_count is not None else self.count("order"))
        return {"row_count": n, "total_orders": total_orders,
                "total_revenue": revenue,
                "unique_customers": self.count("customer"),
                "products_sold": self.count("product"), "active_sellers": self.count("seller"),
                "items_sold": self.scalar(func.sum(quantity)) if quantity is not None else None,
                "avg_order_value": None, "avg_review_score": self.scalar(func.avg(rating)) if rating is not None else None,
                "avg_delivery_days": None}

    def numeric_stats(self, col):
        c = self.by_name[col["name"]]
        stats = self.rows(self.statement(func.count(c).label("count"), func.sum(c).label("sum"),
                                         func.avg(c).label("mean"), func.min(c).label("min"), func.max(c).label("max")))[0]
        ordered = self.statement(c.label("v")).where(c.is_not(None)).order_by(c).subquery()
        n = stats["count"]
        if n:
            middle = select(ordered.c.v).offset((n - 1) // 2).limit(2 if n % 2 == 0 else 1).subquery()
            stats["median"] = self.db.scalar(select(func.avg(middle.c.v)))
        else:
            stats["median"] = None
        return {"field": col["name"], **stats}

    def group(self, col, limit=20):
        amount = self.amount()
        expressions = [col.label("label"), func.count().label("rows")]
        if amount is not None:
            expressions.append(func.sum(amount).label("amount"))
        return self.rows(self.statement(*expressions).where(col.is_not(None)).group_by(col)
                         .order_by(func.count().desc(), col).limit(limit))

    def time_series(self, grain="month", limit=400):
        from sqlalchemy import literal_column
        col = self.field("date")
        if col is None:
            return []
        # Identifiers are generated c0..c99; dialect function is whitelisted.
        expression = f"{self.table.name}.{col.name}"
        if self.db.get_bind().dialect.name == "postgresql":
            expression = f"CAST({expression} AS timestamp)"
        period = literal_column(period_expr(self.db, expression, grain))
        cols = [period.label("period"), func.count().label("rows")]
        amount, order, order_count = self.amount(), self.field("order"), self.field("order_count")
        if amount is not None:
            cols.append(func.sum(amount).label("revenue" if self.field("revenue") is not None else "amount"))
        if order_count is not None:
            # If a period contains any unknown source count, its aggregate is
            # unknown rather than a deceptively low partial total.
            cols.append(case((func.count(order_count) == func.count(), func.sum(order_count)),
                             else_=None).label("orders"))
        elif order is not None:
            cols.append(func.count(func.distinct(order)).label("orders"))
        return self.rows(self.statement(*cols).where(col.is_not(None)).group_by(period).order_by(period.desc())
                         .limit(limit))[::-1]

    def filters(self):
        filters = []
        for c in self.columns:
            if c["dtype"] in {"text", "boolean"} and c["role"] != "identifier" and c["unique"] <= 100:
                col = self.by_name[c["name"]]
                values = [str(r["value"]) for r in self.rows(self.statement(col.label("value")).where(col.is_not(None))
                                                           .distinct().order_by(col).limit(100))]
                filters.append({"field": c["name"], "label": c["name"], "values": values})
        date = self.field("date")
        dates = self.rows(self.statement(func.min(date).label("min"), func.max(date).label("max")))[0] if date is not None else {"min": "", "max": ""}
        return {"dataset_id": self.ds.id, "dynamic": filters, "has_date": date is not None,
                "date_range": {k: str(v or "") for k, v in dates.items()}, "categories": [], "customer_states": [],
                "seller_states": [], "order_statuses": [], "payment_types": [], "review_scores": []}

    def view(self, section):
        capability = self.ds.capabilities.get(section, {"available": True})
        if section == "orders" and self.field("order_count") is not None:
            capability = {"available": True, "reason": None}
        if not capability["available"]:
            return {"dataset_id": self.ds.id, "status": "not_applicable", "reason": capability["reason"],
                    "metric_cards": [], "section": section}
        numeric = [self.numeric_stats(c) for c in self.columns
                   if c["dtype"] == "numeric" and not _technical_column(c) and c["role"] != "identifier"]
        kpis = self.kpis()
        cards = [{"label": "Rows", "value": kpis["row_count"]}]
        for role, label in (("customer", "Customers"), ("product", "Products"), ("seller", "Sellers"), ("order", "Orders / transactions")):
            if role == "customer" and "customer" not in self.ds.semantics.get("fields", {}) and "user" in self.fields:
                label = "Users / accounts"
            count = self.count(role)
            if count is not None:
                cards.append({"label": label, "value": count})
        if self.field("order_count") is not None:
            cards.append({"label": "Orders", "value": kpis["total_orders"]})
        if kpis["total_revenue"] is not None:
            cards.append({"label": "Revenue", "value": kpis["total_revenue"]})
        if kpis["items_sold"] is not None:
            cards.append({"label": "Units sold", "value": kpis["items_sold"]})
        # Keep generic numeric profiles for audit/detail only; never promote an
        # arbitrary numeric field to a business KPI.
        distributions = []
        for c in self.columns:
            if c["dtype"] in {"text", "boolean"} and not _technical_column(c) and c["role"] != "identifier" and 1 < c["unique"] <= 100:
                distributions.append({"field": c["name"], "series": self.group(self.by_name[c["name"]])})
        entity_role = {"customers": "customer", "products": "product", "sellers": "seller", "orders": "order"}.get(section)
        entities = self.group(self.field(entity_role), 50) if entity_role else []
        delivery = None
        if section == "delivery":
            from sqlalchemy import literal_column
            from app.analytics.filters import date_diff_expr
            date, delivered = self.field("date"), self.field("delivery_date")
            difference = literal_column(date_diff_expr(self.db, f"{self.table.name}.{delivered.name}", f"{self.table.name}.{date.name}"))
            from sqlalchemy import case
            valid = delivered.is_not(None) & date.is_not(None) & (difference >= 0)
            delivery = self.rows(self.statement(func.count(case((valid, 1))).label("delivered_rows"),
                                                func.avg(case((valid, difference))).label("average_days")))[0]
            estimated = self.field("estimated_date")
            if estimated is not None:
                delivery["on_time_percentage"] = self.scalar(func.avg(case((~valid | estimated.is_(None) | (estimated < date), None),
                                                                             (delivered <= estimated, 100.0), else_=0.0)))
            cards.extend({"label": name.replace("_", " "), "value": value} for name, value in delivery.items())
        order_field = self.field("order")
        order_count_field = self.field("order_count")
        date_field = self.field("date")
        date_observations = self.scalar(func.count(date_field)) if date_field is not None else 0
        order_observations = (self.scalar(func.count(order_count_field)) if order_count_field is not None
                              else self.scalar(func.count(order_field)) if order_field is not None else 0)
        incomplete_order_values = max(0, int(date_observations or 0) - int(order_observations or 0))
        if date_field is None:
            order_quality_reason = "A confirmed date field is required to chart orders."
        elif order_field is None and order_count_field is None:
            order_quality_reason = "No order ID or daily order-count field is mapped. Map a purchase timestamp and order ID, or an explicit daily orders measure, in Dataset Manager."
        elif not order_observations:
            order_quality_reason = "Order fields are mapped, but no non-missing order observations fall in the selected filters. Missing values are not treated as zero."
        elif incomplete_order_values:
            order_quality_reason = f"{incomplete_order_values:,} dated row(s) have a missing order value. Affected period totals are left blank; missing values are not treated as zero."
        else:
            order_quality_reason = None
        order_quality = {
            "available": date_field is not None and bool(order_observations),
            "date_field": self.fields.get("date"),
            "order_id_field": self.fields.get("order"),
            "order_count_field": self.fields.get("order_count"),
            "date_observations": int(date_observations or 0),
            "order_observations": int(order_observations or 0),
            "incomplete_order_values": incomplete_order_values,
            "reason": order_quality_reason,
        }
        return {"dataset_id": self.ds.id, "dataset_name": self.ds.name, "status": "available", "section": section,
                "filters": self.f.as_dict(), "kpis": kpis, "metric_cards": cards, "numeric_statistics": numeric,
                "distributions": distributions, "entities": entities, "time_series": self.time_series(),
                "order_series_quality": order_quality, "provenance": self.provenance(),
                "currency_code": self.ds.semantics.get("currency_code"), "capabilities": self.ds.capabilities,
                "quality": self.ds.quality, "delivery": delivery}


def dataset_metric(function):
    """Select a warehouse source once at the shared metric boundary."""
    @wraps(function)
    def wrapped(db, *args, **kwargs):
        ds = db.info.get("dataset")
        if ds is None or ds.adapter == "star_schema":
            f = args[0] if args and isinstance(args[0], Filters) else None
            if f and f.column_filters:
                raise HTTPException(422, "Column filters are not supported by this reference warehouse.")
            return function(db, *args, **kwargs)
        f = args[0] if args and isinstance(args[0], Filters) else kwargs.get("f")
        if ds.source_type == 'bundle':
            from app.analytics.bundle import BundleSource
            source = BundleSource(db,f)
            name = function.__name__
            if name == 'kpis': return source.kpis()
            if name == 'filter_options': return source.filters()
            if name == 'time_series': return source.time_series(args[1] if len(args)>1 else kwargs.get('grain','month'),kwargs.get('limit',400))
            if name == 'revenue_by_category': return source.category(kwargs.get('limit',15))
            if name == 'orders_by_status': return source.statuses()
            if name in {'overview','sales','orders','customers','products','sellers','delivery'}: return source.view(name)
            raise HTTPException(422,'This metric is unavailable for the selected bundle. Select a table for generic analysis.')
        source = TabularSource(db, f)
        name = function.__name__
        if name == "kpis":
            return source.kpis()
        if name == "filter_options":
            return source.filters()
        if name == "time_series":
            return source.time_series(args[1] if len(args) > 1 else kwargs.get("grain", "month"), kwargs.get("limit", 400))
        if name == "revenue_by_category":
            col = source.field("category")
            return [{"category": r["label"], "revenue": r.get("amount"), "items": r["rows"]} for r in source.group(col)] if col is not None else []
        if name == "orders_by_status":
            col = source.field("status")
            return [{"status": r["label"], "orders": r["rows"]} for r in source.group(col)] if col is not None else []
        if name in {"overview", "sales", "orders", "customers", "products", "sellers", "delivery"}:
            return source.view("dashboard" if name == "overview" else name)
        # Specialized legacy submetrics cannot read the reference warehouse.
        raise HTTPException(422, f"{name.replace('_', ' ')} requires reference-specific fields.")
    return wrapped
