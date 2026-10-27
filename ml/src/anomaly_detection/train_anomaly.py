"""Daily order anomaly detection via Isolation Forest.

Flags unusual days in the daily orders series (e.g. spikes/drops). Reports the
contamination rate used and the detected anomaly dates.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.metadata import write_metadata  # noqa: E402
from src.common.paths import models_dir, processed_dir  # noqa: E402

FEATURES = ["orders", "revenue"]
CONTAMINATION = 0.03


def main() -> None:
    df = pd.read_csv(processed_dir() / "daily_series.csv", parse_dates=["date"]).sort_values("date")
    X = df[FEATURES].astype(float)

    model = IsolationForest(n_estimators=200, contamination=CONTAMINATION, random_state=42)
    df["anomaly"] = model.fit_predict(X)  # -1 = anomaly
    df["score"] = model.decision_function(X)

    anomalies = df[df["anomaly"] == -1]
    top = (
        anomalies.sort_values("score")[["date", "orders", "revenue", "score"]]
        .head(20)
        .assign(date=lambda d: d["date"].dt.strftime("%Y-%m-%d"))
        .to_dict(orient="records")
    )

    artifact = models_dir() / "anomaly_detection.joblib"
    joblib.dump({"model": model, "features": FEATURES, "contamination": CONTAMINATION}, artifact)
    df.to_csv(processed_dir() / "daily_anomalies.csv", index=False)

    write_metadata(
        "anomaly_detection",
        target="is_anomaly",
        features=FEATURES,
        metrics={
            "contamination": CONTAMINATION,
            "n_days": int(len(df)),
            "n_anomalies": int(len(anomalies)),
            "top_anomalies": top,
        },
        status="available",
        algorithm="IsolationForest",
        dataset_files=[processed_dir() / "daily_series.csv"],
        artifact=artifact.name,
        notes="Unsupervised; contamination fixed at 3%. Scores are decision_function values.",
    )
    print(f"anomalies: {len(anomalies)}/{len(df)}")
    for a in top[:5]:
        print(a)


if __name__ == "__main__":
    main()
