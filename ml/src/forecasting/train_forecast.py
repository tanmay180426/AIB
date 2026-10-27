"""Sales/demand forecasting on the daily orders series.

- Target: daily order count (also trains on daily revenue as second target).
- Baseline: seasonal naive (value 7 days earlier).
- Model: Linear Regression on lag/rolling features (sklearn).
- Split: chronological 80/20 (no shuffling -> no leakage).

Saves artifacts + metadata to ml/models (gitignored). Honest metrics only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.metadata import write_metadata  # noqa: E402
from src.common.paths import models_dir, processed_dir  # noqa: E402
from src.evaluation.metrics import regression_metrics  # noqa: E402


def make_features(series: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"y": series})
    for lag in (1, 7, 14, 30):
        df[f"lag{lag}"] = df["y"].shift(lag)
    df["roll7"] = df["y"].shift(1).rolling(7).mean()
    df["roll30"] = df["y"].shift(1).rolling(30).mean()
    return df


def train_target(name: str, series: pd.Series) -> dict:
    df = make_features(series).dropna()
    feature_cols = [c for c in df.columns if c != "y"]

    split = int(len(df) * 0.8)
    train, test = df.iloc[:split], df.iloc[split:]
    Xtr, ytr = train[feature_cols], train["y"]
    Xte, yte = test[feature_cols], test["y"]

    # seasonal naive baseline: value 7 days earlier
    naive_pred = test["lag7"]
    baseline = regression_metrics(yte, naive_pred)

    model = LinearRegression().fit(Xtr, ytr)
    pred = model.predict(Xte)
    metrics = regression_metrics(yte, pred)

    artifact = models_dir() / f"{name}.joblib"
    joblib.dump({"model": model, "features": feature_cols}, artifact)

    meta = write_metadata(
        name,
        target=name,
        features=feature_cols,
        metrics={"model": metrics, "seasonal_naive_baseline": baseline, "n_train": len(train), "n_test": len(test)},
        status="available",
        algorithm="LinearRegression (lag/rolling features)",
        dataset_files=[processed_dir() / "daily_series.csv"],
        artifact=artifact.name,
        notes="Chronological split; seasonal naive baseline included. Historical data only.",
    )
    return {"name": name, "metrics": metrics, "baseline": baseline, "metadata": str(meta)}


def main() -> None:
    daily = pd.read_csv(processed_dir() / "daily_series.csv", parse_dates=["date"]).sort_values("date")
    results = []
    results.append(train_target("sales_forecast_orders", daily["orders"].astype(float)))
    results.append(train_target("sales_forecast_revenue", daily["revenue"].astype(float)))
    for r in results:
        print(f"{r['name']}: model={r['metrics']} baseline={r['baseline']}")


if __name__ == "__main__":
    main()
