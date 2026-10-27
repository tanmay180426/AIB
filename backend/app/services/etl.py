"""ETL pipeline: read the raw Olist CSVs, validate, transform, and load the
analytical warehouse.

Design rules (see docs/DATA_QUALITY.md and docs/DATABASE_DESIGN.md):
- The raw CSVs are NEVER modified. They are read from the external Olist
  directory (env OLIST_DIR or %USERPROFILE%/Downloads/olist).
- The load is idempotent: warehouse tables are dropped and rebuilt so re-runs
  do not duplicate data.
- Missing delivery timestamps are preserved as NULL and excluded from delivery
  metrics rather than imputed.
- Revenue is defined as the sum of order item prices. Freight is tracked
  separately. No profit/margin is derived.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from app.database.session import Base, engine
import app.models.warehouse as warehouse  # noqa: F401  (register models)

logger = logging.getLogger("etl")

REQUIRED_FILES: Dict[str, List[str]] = {
    "olist_customers_dataset.csv": [
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state",
    ],
    "olist_orders_dataset.csv": [
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "olist_order_items_dataset.csv": [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value",
    ],
    "olist_order_payments_dataset.csv": [
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value",
    ],
    "olist_order_reviews_dataset.csv": [
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp",
    ],
    "olist_products_dataset.csv": [
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
    "olist_sellers_dataset.csv": [
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state",
    ],
    "product_category_name_translation.csv": [
        "product_category_name",
        "product_category_name_english",
    ],
}


def olist_dir() -> str:
    env = os.getenv("OLIST_DIR")
    if env:
        return env
    return os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "olist")


@dataclass
class ETLReport:
    rows: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors


def _read_csv(path: str, required: List[str], report: ETLReport) -> pd.DataFrame:
    name = os.path.basename(path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    missing = [c for c in required if c not in df.columns]
    if missing:
        report.errors.append(f"{name}: missing required columns {missing}")
    report.rows[name] = len(df)
    return df


def extract(report: ETLReport) -> Dict[str, pd.DataFrame]:
    base = olist_dir()
    if not os.path.isdir(base):
        report.errors.append(f"Olist directory not found: {base}")
        return {}

    data: Dict[str, pd.DataFrame] = {}
    for fname, required in REQUIRED_FILES.items():
        path = os.path.join(base, fname)
        if not os.path.isfile(path):
            report.errors.append(f"Missing file: {path}")
            continue
        data[fname] = _read_csv(path, required, report)
    return data


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def transform(data: Dict[str, pd.DataFrame], report: ETLReport) -> Dict[str, pd.DataFrame]:
    orders = data["olist_orders_dataset.csv"].copy()
    items = data["olist_order_items_dataset.csv"].copy()
    payments = data["olist_order_payments_dataset.csv"].copy()
    reviews = data["olist_order_reviews_dataset.csv"].copy()
    customers = data["olist_customers_dataset.csv"].copy()
    products = data["olist_products_dataset.csv"].copy()
    sellers = data["olist_sellers_dataset.csv"].copy()
    translation = data["product_category_name_translation.csv"].copy()

    # --- orders: parse timestamps, compute delivery delay ---
    orders["order_purchase_timestamp"] = _to_dt(orders["order_purchase_timestamp"])
    orders["order_delivered_customer_date"] = _to_dt(orders["order_delivered_customer_date"])
    orders["order_estimated_delivery_date"] = _to_dt(orders["order_estimated_delivery_date"])

    missing_delivery = orders["order_delivered_customer_date"].isna().sum()
    if missing_delivery:
        report.warnings.append(
            f"orders: {missing_delivery} rows without delivered_customer_date "
            "(excluded from delivery-time metrics)"
        )

    orders["delivery_days"] = (
        orders["order_delivered_customer_date"] - orders["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400.0
    orders.loc[orders["delivery_days"] < 0, "delivery_days"] = float("nan")

    both_dates = (
        orders["order_delivered_customer_date"].notna()
        & orders["order_estimated_delivery_date"].notna()
    )
    orders["is_late"] = pd.Series(pd.NA, index=orders.index, dtype="boolean")
    orders.loc[both_dates, "is_late"] = (
        orders.loc[both_dates, "order_delivered_customer_date"]
        > orders.loc[both_dates, "order_estimated_delivery_date"]
    )

    orders["purchase_date"] = orders["order_purchase_timestamp"].dt.date
    orders["delivered_customer_date"] = orders["order_delivered_customer_date"].dt.date
    orders["estimated_delivery_date"] = orders["order_estimated_delivery_date"].dt.date

    # --- payments: total per order + the primary payment method ---
    # Primary payment = the order's highest-value payment (ties broken by the
    # earliest sequence); its type/installments describe how the order was
    # settled. payment_value stays the sum across all payments of the order.
    payments["payment_value"] = pd.to_numeric(payments["payment_value"], errors="coerce")
    payments["payment_sequential"] = pd.to_numeric(
        payments["payment_sequential"], errors="coerce"
    )
    payments["payment_installments"] = pd.to_numeric(
        payments["payment_installments"], errors="coerce"
    ).astype("Int64")

    pay_agg = payments.groupby("order_id", as_index=False).agg(
        payment_value=("payment_value", "sum"),
    )
    primary = (
        payments.dropna(subset=["payment_value"])
        .sort_values(
            ["order_id", "payment_value", "payment_sequential"],
            ascending=[True, False, True],
        )
        .drop_duplicates(subset=["order_id"], keep="first")[
            ["order_id", "payment_type", "payment_installments"]
        ]
    )
    pay_agg = pay_agg.merge(primary, on="order_id", how="left")

    # --- reviews: average score per order ---
    rev_agg = (
        reviews.assign(review_score=pd.to_numeric(reviews["review_score"], errors="coerce"))
        .groupby("order_id", as_index=False)["review_score"]
        .mean()
    )

    # --- order item revenue/freight per order ---
    items["price"] = pd.to_numeric(items["price"], errors="coerce").fillna(0.0)
    items["freight_value"] = pd.to_numeric(items["freight_value"], errors="coerce").fillna(0.0)
    items["order_item_id"] = pd.to_numeric(items["order_item_id"], errors="coerce")

    item_agg = items.groupby("order_id", as_index=False).agg(
        item_revenue=("price", "sum"),
        freight_value=("freight_value", "sum"),
    )

    # --- dimensions ---
    dim_customer = customers.rename(
        columns={
            "customer_unique_id": "customer_unique_id",
            "customer_zip_code_prefix": "customer_zip_code_prefix",
            "customer_city": "customer_city",
            "customer_state": "customer_state",
        }
    )[
        ["customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"]
    ].drop_duplicates(subset=["customer_unique_id"])

    product_en = products.merge(
        translation,
        how="left",
        left_on="product_category_name",
        right_on="product_category_name",
    )
    dim_product = product_en.rename(
        columns={
            "product_category_name": "product_category_name_pt",
            "product_category_name_english": "product_category_name_en",
        }
    )[
        [
            "product_id",
            "product_category_name_pt",
            "product_category_name_en",
            "product_weight_g",
        ]
    ].copy()
    dim_product["product_weight_g"] = pd.to_numeric(
        dim_product["product_weight_g"], errors="coerce"
    )

    dim_seller = sellers[
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"]
    ].drop_duplicates(subset=["seller_id"])

    # --- fact_orders ---
    orders_map = orders.merge(
        customers[["customer_id", "customer_unique_id"]], on="customer_id", how="left"
    )
    fact_orders = orders_map.merge(item_agg, on="order_id", how="left").merge(
        pay_agg, on="order_id", how="left"
    ).merge(rev_agg, on="order_id", how="left")

    fact_orders = fact_orders[
        [
            "order_id",
            "customer_unique_id",
            "order_status",
            "purchase_date",
            "delivered_customer_date",
            "estimated_delivery_date",
            "delivery_days",
            "is_late",
            "review_score",
            "payment_value",
            "payment_type",
            "payment_installments",
            "item_revenue",
            "freight_value",
        ]
    ].copy()

    # --- fact_order_items (line grain) ---
    # items dataset has no customer_id; join via orders
    items_enriched = (
        items.merge(orders[["order_id", "purchase_date", "customer_id"]], on="order_id", how="left")
        .merge(customers[["customer_id", "customer_unique_id"]], on="customer_id", how="left")
        .merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
        .merge(
            translation,
            how="left",
            left_on="product_category_name",
            right_on="product_category_name",
        )
        .rename(columns={"product_category_name_english": "product_category_name_en"})
    )

    fact_items = items_enriched[
        [
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "customer_unique_id",
            "purchase_date",
            "price",
            "freight_value",
            "product_category_name_en",
        ]
    ].copy()

    # --- dim_date from order purchase dates ---
    dates = pd.to_datetime(fact_orders["purchase_date"], errors="coerce").dropna().unique()
    dim_date = pd.DataFrame({"date_key": pd.to_datetime(sorted(dates))})
    dim_date["year"] = dim_date["date_key"].dt.year
    dim_date["month"] = dim_date["date_key"].dt.month
    dim_date["day"] = dim_date["date_key"].dt.day
    dim_date["quarter"] = dim_date["date_key"].dt.quarter
    dim_date["weekday"] = dim_date["date_key"].dt.weekday

    return {
        "dim_customer": dim_customer,
        "dim_product": dim_product,
        "dim_seller": dim_seller,
        "dim_date": dim_date,
        "fact_orders": fact_orders,
        "fact_order_items": fact_items,
    }


def load(tables: Dict[str, pd.DataFrame], report: ETLReport) -> None:
    # Rebuild ONLY the warehouse tables (never the application's user tables)
    # so schema changes - e.g. new fact columns - are applied on re-runs.
    # Explicit order: children first for the drop, parents first for the create.
    warehouse_tables = [
        warehouse.FactOrderItems.__table__,
        warehouse.FactOrders.__table__,
        warehouse.DimDate.__table__,
        warehouse.DimSeller.__table__,
        warehouse.DimProduct.__table__,
        warehouse.DimCustomer.__table__,
    ]
    Base.metadata.drop_all(bind=engine, tables=warehouse_tables)
    Base.metadata.create_all(bind=engine, tables=list(reversed(warehouse_tables)))
    with engine.begin() as conn:
        for name in ["dim_customer", "dim_product", "dim_seller", "dim_date"]:
            tables[name].to_sql(name, con=conn, if_exists="append", index=False)
        tables["fact_orders"].to_sql("fact_orders", con=conn, if_exists="append", index=False)
        tables["fact_order_items"].to_sql(
            "fact_order_items", con=conn, if_exists="append", index=False
        )
    for name, df in tables.items():
        report.rows[f"warehouse.{name}"] = len(df)


def run() -> ETLReport:
    report = ETLReport()
    data = extract(report)
    if not report.ok():
        return report
    try:
        tables = transform(data, report)
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"transform failed: {exc}")
        logger.exception("ETL transform failed")
        return report
    if not report.ok():
        return report
    load(tables, report)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run()
    print("ETL rows:")
    for k, v in rep.rows.items():
        print(f"  {k}: {v}")
    for w in rep.warnings:
        print("WARN:", w)
    for e in rep.errors:
        print("ERROR:", e)
    print("OK" if rep.ok() else "FAILED")
