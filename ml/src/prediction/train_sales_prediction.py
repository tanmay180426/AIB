"""Order-level sales (item revenue) prediction.

Features are available at checkout time: purchase month/weekday/hour, customer
state, basket size (n_items), and dominant product category. The target is the
order's total item revenue. Delivery/review/payment fields are excluded to avoid
leakage.

Models: Linear Regression (baseline) and Random Forest Regressor.
Split: random 80/20 with fixed seed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.metadata import write_metadata  # noqa: E402
from src.common.paths import models_dir, processed_dir  # noqa: E402
from src.evaluation.metrics import regression_metrics  # noqa: E402

NUM = ["purchase_month", "purchase_weekday", "purchase_hour", "n_items"]
CAT = ["customer_state", "product_category_name"]
TARGET = "item_revenue"


def build_pipeline(model) -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUM),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), CAT),
        ]
    )
    return Pipeline([("pre", pre), ("model", model)])


def main() -> None:
    df = pd.read_csv(processed_dir() / "orders_features.csv")
    df = df.dropna(subset=[TARGET])
    X = df[NUM + CAT].copy()
    X[CAT] = X[CAT].fillna("unknown")
    y = df[TARGET].astype(float)

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)

    results = {}
    best = None
    best_mae = float("inf")
    for name, model in [
        ("linear_regression", LinearRegression()),
        ("random_forest", RandomForestRegressor(n_estimators=100, max_depth=12, random_state=42, n_jobs=-1)),
    ]:
        pipe = build_pipeline(model).fit(Xtr, ytr)
        pred = pipe.predict(Xte)
        m = regression_metrics(yte, pred)
        results[name] = m
        print(f"{name}: {m}")
        if m["mae"] < best_mae:
            best_mae = m["mae"]
            best = (name, pipe)

    name, pipe = best
    artifact = models_dir() / "sales_prediction.joblib"
    joblib.dump({"pipeline": pipe, "features": NUM + CAT, "target": TARGET}, artifact)

    write_metadata(
        "sales_prediction",
        target=TARGET,
        features=NUM + CAT,
        metrics={"selected": name, "candidates": results, "n_train": len(Xtr), "n_test": len(Xte)},
        status="available",
        algorithm=f"best of [LinearRegression, RandomForest] -> {name}",
        dataset_files=[processed_dir() / "orders_features.csv"],
        artifact=artifact.name,
        notes="Random split seed=42. No leakage features. Historical data only.",
    )
    print(f"selected: {name}")


if __name__ == "__main__":
    main()
