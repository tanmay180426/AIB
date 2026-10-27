"""Customer segmentation via RFM + K-Means.

Features: recency_days, frequency, log1p(monetary) -> StandardScaler.
k chosen in [2..6] by silhouette score. Assigns every customer a cluster label.
"""

from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.metadata import write_metadata  # noqa: E402
from src.common.paths import models_dir, processed_dir  # noqa: E402

FEATURES = ["recency_days", "frequency", "monetary_log"]


def main() -> None:
    df = pd.read_csv(processed_dir() / "customer_rfm.csv")
    df["monetary_log"] = np.log1p(df["monetary"].clip(lower=0))
    X = df[FEATURES].astype(float)

    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    # silhouette is O(n^2): score on a fixed random sample, cluster on all rows
    rng = np.random.default_rng(42)
    sample_idx = rng.choice(len(Xs), size=min(10000, len(Xs)), replace=False)

    scores = {}
    best_k, best_score, best_model = None, -1.0, None
    for k in range(2, 7):
        km = KMeans(n_clusters=k, random_state=42, n_init=5).fit(Xs)
        s = float(silhouette_score(Xs[sample_idx], km.labels_[sample_idx]))
        scores[k] = round(s, 4)
        if s > best_score:
            best_k, best_score, best_model = k, s, km
        print(f"k={k}: silhouette={s:.4f}")

    labels = best_model.labels_
    df["cluster"] = labels
    sizes = df["cluster"].value_counts().sort_index().to_dict()
    summary = (
        df.groupby("cluster")[["recency_days", "frequency", "monetary"]]
        .mean()
        .round(2)
        .to_dict(orient="index")
    )

    artifact = models_dir() / "customer_segmentation.joblib"
    joblib.dump({"scaler": scaler, "model": best_model, "features": FEATURES, "k": best_k}, artifact)
    df[["customer_unique_id", "cluster"]].to_csv(processed_dir() / "customer_segments.csv", index=False)

    write_metadata(
        "customer_segmentation",
        target="cluster_label",
        features=FEATURES,
        metrics={
            "k": best_k,
            "silhouette": round(best_score, 4),
            "silhouette_by_k": scores,
            "cluster_sizes": sizes,
            "cluster_means": summary,
        },
        status="available",
        algorithm="KMeans (RFM, standardized)",
        dataset_files=[processed_dir() / "customer_rfm.csv"],
        artifact=artifact.name,
        notes="monetary log1p-transformed; k selected by silhouette.",
    )
    print(f"selected k={best_k} silhouette={best_score:.4f} sizes={sizes}")


if __name__ == "__main__":
    main()
