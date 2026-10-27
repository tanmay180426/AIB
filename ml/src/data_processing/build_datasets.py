"""Build analysis-ready datasets for ML from the raw Olist CSVs.

Outputs (ml/data/processed/, gitignored):
- daily_series.csv     : date, orders, revenue, avg_order_value
- orders_features.csv  : order-level regression features + target (item_revenue)
- customer_rfm.csv     : customer-level RFM features
- product_features.csv : product-level aggregate features

The raw CSVs are never modified.
"""

from __future__ import annotations

import sys
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import olist_dir, processed_dir  # noqa: E402


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(olist_dir() / name)


def _source_inventory() -> dict[str, dict]:
    inventory = {}
    for path in sorted(olist_dir().glob("*.csv")):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        sample = pd.read_csv(path, nrows=1000)
        missing = {str(column): 0 for column in sample.columns}
        rows = 0
        date_columns = [column for column in sample.columns
                        if "date" in str(column).lower() or "timestamp" in str(column).lower()]
        date_bounds = {str(column): [None, None] for column in date_columns}
        for chunk in pd.read_csv(path, chunksize=100_000):
            rows += len(chunk)
            for column, count in chunk.isna().sum().items():
                missing[str(column)] += int(count)
            for column in date_columns:
                parsed = pd.to_datetime(chunk[column], errors="coerce")
                if parsed.notna().any():
                    low, high = parsed.min().isoformat(), parsed.max().isoformat()
                    old_low, old_high = date_bounds[str(column)]
                    date_bounds[str(column)] = [min(old_low, low) if old_low else low,
                                                max(old_high, high) if old_high else high]
        inventory[path.name] = {
            "rows": rows,
            "bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
            "columns": [str(column) for column in sample.columns],
            "dtypes_first_1000_rows": {str(k): str(v) for k, v in sample.dtypes.items()},
            "missing_values_by_column": missing,
            "date_coverage_by_column": date_bounds,
            "classification": ("supplemental generated daily aggregate; audited against source-record targets, not used as a second target series"
                               if path.name == "olist_daily_business_features.csv"
                               else "source-style table; synthetic rows may be present after declared cutoff"),
        }
    return inventory


def _audit_daily_business_features(daily: pd.DataFrame) -> dict | None:
    """Reconcile the supplied derived daily table without using it as targets."""
    path = olist_dir() / "olist_daily_business_features.csv"
    if not path.is_file():
        return None
    features = pd.read_csv(path)
    required = {"date", "orders", "revenue"}
    if not required.issubset(features.columns):
        return {"file": path.name, "rows": int(len(features)),
                "usable_for_reconciliation": False,
                "reason": f"Missing required columns: {sorted(required - set(features.columns))}"}
    features["date"] = pd.to_datetime(features["date"], errors="coerce").dt.normalize()
    valid_features = features.dropna(subset=["date"])
    source = daily[["date", "orders", "revenue"]].copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce").dt.normalize()
    joined = source.merge(valid_features[["date", "orders", "revenue"]], on="date", how="outer",
                          suffixes=("_source", "_feature"), indicator=True)
    overlap = joined["_merge"].eq("both")
    source_only = joined["_merge"].eq("left_only")
    feature_only = joined["_merge"].eq("right_only")
    order_difference = (joined.loc[overlap, "orders_source"].astype(float) -
                        joined.loc[overlap, "orders_feature"].astype(float)).abs()
    revenue_difference = (joined.loc[overlap, "revenue_source"].astype(float) -
                          joined.loc[overlap, "revenue_feature"].astype(float)).abs()
    return {
        "file": path.name, "rows": int(len(features)), "invalid_dates": int(features["date"].isna().sum()),
        "duplicate_dates": int(features["date"].dropna().duplicated().sum()),
        "date_start": valid_features["date"].min().strftime("%Y-%m-%d") if len(valid_features) else None,
        "date_end": valid_features["date"].max().strftime("%Y-%m-%d") if len(valid_features) else None,
        "source_series_rows": int(len(source)), "overlap_dates": int(overlap.sum()),
        "source_dates_absent_from_feature_table": int(source_only.sum()),
        "source_active_dates_absent_from_feature_table": int((source_only & joined["orders_source"].fillna(0).gt(0)).sum()),
        "source_orders_on_dates_absent_from_feature_table": int(joined.loc[source_only, "orders_source"].fillna(0).sum()),
        "feature_only_dates": int(feature_only.sum()),
        "source_orders_total": int(source["orders"].sum()),
        "feature_orders_total": int(pd.to_numeric(features["orders"], errors="coerce").sum()),
        "overlap_dates_with_equal_order_count": int(order_difference.le(1e-8).sum()),
        "overlap_dates_with_different_order_count": int(order_difference.gt(1e-8).sum()),
        "source_item_price_revenue_total": round(float(source["revenue"].sum()), 2),
        "feature_revenue_total": round(float(pd.to_numeric(features["revenue"], errors="coerce").sum()), 2),
        "overlap_dates_with_equal_revenue": int(revenue_difference.le(1e-8).sum()),
        "overlap_dates_with_different_revenue": int(revenue_difference.gt(1e-8).sum()),
        "target_use": "Inventory and reconcile only. The canonical forecasting targets are rebuilt from source orders and order-item prices; this generated daily summary is sparse and does not reconcile exactly, so substituting or summing it would omit activity or double-count records.",
    }


def build_daily_series(orders: pd.DataFrame) -> pd.DataFrame:
    o = orders.copy()
    o["ts"] = pd.to_datetime(o["order_purchase_timestamp"], errors="coerce")
    o = o.dropna(subset=["ts"])
    daily = o.set_index("ts").resample("D").size().rename("orders").to_frame()
    return daily.reset_index().rename(columns={"ts": "date"})


def build_daily_series_with_revenue(
    orders: pd.DataFrame, items: pd.DataFrame
) -> pd.DataFrame:
    rev = items.groupby("order_id")["price"].sum().rename("revenue")
    o = orders.copy()
    o["ts"] = pd.to_datetime(o["order_purchase_timestamp"], errors="coerce")
    o = o.dropna(subset=["ts"]).merge(rev, on="order_id", how="left")
    o["revenue"] = o["revenue"].fillna(0.0)
    o["date"] = o["ts"].dt.normalize()
    daily = (
        o.groupby("date")
        .agg(orders=("order_id", "nunique"), revenue=("revenue", "sum"))
        .sort_index()
    )
    missing_calendar_days = 0
    # For the source-defined Olist observation window, a calendar day without
    # an order row means zero observed activity. This does not fill before/after
    # the first/last valid purchase date or alter any source records.
    if not daily.empty:
        calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D", name="date")
        missing_calendar_days = len(calendar.difference(daily.index))
        daily = daily.reindex(calendar, fill_value=0).rename_axis("date").reset_index()
    daily["avg_order_value"] = np.where(
        daily["orders"] > 0, daily["revenue"] / daily["orders"], 0.0
    )
    return daily


def build_orders_features(
    orders: pd.DataFrame, items: pd.DataFrame, customers: pd.DataFrame, products: pd.DataFrame
) -> pd.DataFrame:
    o = orders.copy()
    o["ts"] = pd.to_datetime(o["order_purchase_timestamp"], errors="coerce")
    o = o.dropna(subset=["ts"])
    o["purchase_month"] = o["ts"].dt.month
    o["purchase_weekday"] = o["ts"].dt.weekday
    o["purchase_hour"] = o["ts"].dt.hour

    # target: order item revenue
    rev = items.groupby("order_id").agg(
        item_revenue=("price", "sum"),
        n_items=("order_item_id", "count"),
    )
    base = o.merge(rev, on="order_id", how="inner")
    base = base.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left")

    # dominant category per order (first item category)
    first_item = (
        items.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
        .sort_values(["order_id", "order_item_id"])
        .groupby("order_id")
        .first()[["product_category_name"]]
    )
    base = base.merge(first_item, on="order_id", how="left")

    out = base[
        [
            "order_id",
            "purchase_month",
            "purchase_weekday",
            "purchase_hour",
            "customer_state",
            "n_items",
            "product_category_name",
            "item_revenue",
        ]
    ].copy()
    out = out.dropna(subset=["item_revenue"])
    return out


def build_customer_rfm(
    orders: pd.DataFrame, items: pd.DataFrame, customers: pd.DataFrame
) -> pd.DataFrame:
    o = orders.copy()
    o["ts"] = pd.to_datetime(o["order_purchase_timestamp"], errors="coerce")
    o = o.dropna(subset=["ts"])
    o = o.merge(customers[["customer_id", "customer_unique_id"]], on="customer_id", how="left")

    rev = items.groupby("order_id")["price"].sum().rename("order_revenue")
    o = o.merge(rev, on="order_id", how="left")
    o["order_revenue"] = o["order_revenue"].fillna(0.0)

    snapshot = o["ts"].max() + pd.Timedelta(days=1)
    rfm = o.groupby("customer_unique_id").agg(
        last_purchase=("ts", "max"),
        frequency=("order_id", "nunique"),
        monetary=("order_revenue", "sum"),
    )
    rfm["recency_days"] = (snapshot - rfm["last_purchase"]).dt.days
    return rfm.reset_index()[
        ["customer_unique_id", "recency_days", "frequency", "monetary"]
    ]


def build_product_features(
    items: pd.DataFrame, products: pd.DataFrame
) -> pd.DataFrame:
    agg = items.groupby("product_id").agg(
        total_qty=("order_item_id", "count"),
        total_revenue=("price", "sum"),
        avg_price=("price", "mean"),
    )
    prod = products[["product_id", "product_category_name", "product_weight_g"]].copy()
    out = agg.merge(prod, on="product_id", how="left")
    return out.reset_index(drop=True)


def main() -> None:
    out = processed_dir()
    orders = _read("olist_orders_dataset.csv")
    items = _read("olist_order_items_dataset.csv")
    customers = _read("olist_customers_dataset.csv")
    products = _read("olist_products_dataset.csv")

    # A documented extension cutoff is provenance only. The user's requested
    # training population is the full, unified source window, including rows
    # the provider identifies as synthetic.
    summary_path = olist_dir() / "generation_summary.txt"
    extension_start = None
    if summary_path.is_file():
        summary = summary_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"Synthetic extension starts\s*:?\s*(\d{4}-\d{2}-\d{2})", summary, re.I)
        if match:
            extension_start = pd.Timestamp(match.group(1))
    parsed_dates = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
    valid_dates = parsed_dates.dropna()
    if valid_dates.empty:
        raise ValueError("No valid purchase timestamps found; cannot build the unified daily series.")
    first_purchase = valid_dates.min().normalize()
    last_purchase = valid_dates.max().normalize()
    observed_days = valid_dates.dt.normalize().drop_duplicates()
    missing_calendar_days = len(pd.date_range(first_purchase, last_purchase, freq="D")) - len(observed_days)

    # One primary workflow, one full-window series. Calendar gaps inside the
    # source's observed window represent no order rows and are zero activity.
    daily = build_daily_series_with_revenue(orders, items)
    daily.to_csv(out / "daily_series.csv", index=False)

    numeric_price = pd.to_numeric(items["price"], errors="coerce")
    finite_price = numeric_price[np.isfinite(numeric_price)]
    price_q1, price_q3 = finite_price.quantile([0.25, 0.75])
    price_iqr = price_q3 - price_q1
    quality = {
        "source": str(olist_dir()),
        "generation_summary": ({"file": summary_path.name,
                                "sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                                "text": summary_path.read_text(encoding="utf-8", errors="replace")}
                               if summary_path.is_file() else None),
        "source_files": _source_inventory(),
        "supplemental_daily_business_features_audit": _audit_daily_business_features(daily),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance_window": {
            "documented_original_window_end_inclusive": (extension_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d") if extension_start is not None else None,
            "synthetic_extension_start": extension_start.strftime("%Y-%m-%d") if extension_start is not None else None,
            "orders_extended_window": int((parsed_dates >= extension_start).sum()) if extension_start is not None else 0,
            "all_valid_timestamp_orders_in_unified_series": int(parsed_dates.notna().sum()),
            "synthetic_rows_included_in_unified_training_and_evaluation": int((parsed_dates >= extension_start).sum()) if extension_start is not None else 0,
            "note": "The generation summary identifies post-cutoff observations as synthetic/generated. They are retained in the unified primary series as requested; mixed-data scores do not establish real-world accuracy.",
        },
        "daily_series": {
            "rows": int(len(daily)), "date_start": daily.date.min().strftime("%Y-%m-%d") if len(daily) else None,
            "date_end": daily.date.max().strftime("%Y-%m-%d") if len(daily) else None,
            "duplicate_dates": int(daily.date.duplicated().sum()),
            "missing_calendar_days_filled_as_zero": int(missing_calendar_days),
            "orders_total": int(daily.orders.sum()), "item_price_revenue_total": round(float(daily.revenue.sum()), 2),
        },
        "orders": {
            "missing_values_by_column": {str(k): int(v) for k, v in orders.isna().sum().items()},
            "exact_duplicate_rows": int(orders.duplicated().sum()),
            "duplicate_order_ids": int(orders.order_id.duplicated().sum()),
            "missing_order_ids": int(orders.order_id.isna().sum()),
            "invalid_purchase_timestamps_excluded": int(parsed_dates.isna().sum()),
            "valid_purchase_date_start": parsed_dates.min().date().isoformat() if parsed_dates.notna().any() else None,
            "valid_purchase_date_end": parsed_dates.max().date().isoformat() if parsed_dates.notna().any() else None,
        },
        "order_items": {
            "missing_values_by_column": {str(k): int(v) for k, v in items.isna().sum().items()},
            "exact_duplicate_rows": int(items.duplicated().sum()),
            "duplicate_order_item_pairs": int(items.duplicated(["order_id", "order_item_id"]).sum()),
            "missing_prices": int(numeric_price.isna().sum()),
            "negative_prices": int((finite_price < 0).sum()),
            "nonfinite_prices": int((~np.isfinite(numeric_price.dropna())).sum()),
            "price_iqr_outlier_count": int(((numeric_price < price_q1 - 1.5 * price_iqr) |
                                             (numeric_price > price_q3 + 1.5 * price_iqr)).sum()) if pd.notna(price_iqr) else 0,
            "price_summary": {"min": float(finite_price.min()), "median": float(finite_price.median()),
                              "max": float(finite_price.max())} if len(finite_price) else None,
        },
        "unified_daily_series": {"rows": int(len(daily)), "date_start": daily.date.min().strftime("%Y-%m-%d") if len(daily) else None,
                                 "date_end": daily.date.max().strftime("%Y-%m-%d") if len(daily) else None,
                                 "source_order_rows_included": int(parsed_dates.notna().sum()),
                                 "source_order_rows_excluded_invalid_timestamp": int(parsed_dates.isna().sum()),
                                 "missing_calendar_days_filled_as_zero": int(missing_calendar_days)},
        "target_definition": "unified daily count of unique orders; unified daily sum of order-item price (Olist price, BRL), excluding freight, tax, payment totals, and profit. Documented synthetic extension is included in the primary series.",
        "limitations": ["Olist is a historical Brazilian ecommerce sample and does not establish present-day business patterns.",
                       "Invalid purchase timestamps are excluded from daily aggregation.",
                       "Missing calendar dates inside the valid source period are interpreted as zero orders.",
                       "Revenue uses item price only; it is not payment value, freight-inclusive sales, or profit.",
                       "The supplied generation summary labels records from the declared extension cutoff as synthetic/generated. Those observations are included in the unified dataset and all forecast partitions; this mixed provenance limits claims of real-world generalization."],
    }
    (processed_dir() / "data_quality_report.json").write_text(json.dumps(quality, indent=2), encoding="utf-8")

    orders_feat = build_orders_features(orders, items, customers, products)
    orders_feat.to_csv(out / "orders_features.csv", index=False)

    rfm = build_customer_rfm(orders, items, customers)
    rfm.to_csv(out / "customer_rfm.csv", index=False)

    prod_feat = build_product_features(items, products)
    prod_feat.to_csv(out / "product_features.csv", index=False)

    print(f"daily_series: {daily.shape}")
    print(f"orders_features: {orders_feat.shape}")
    print(f"customer_rfm: {rfm.shape}")
    print(f"product_features: {prod_feat.shape}")


if __name__ == "__main__":
    main()
