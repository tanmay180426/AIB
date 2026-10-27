"""Product segmentation via engagement features + K-Means.

Features: log1p(total_qty), log1p(total_revenue), avg_price, product_weight_g.
k chosen in [2..6] by (sampled) silhouette score.
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

FEATURES = ["qty_log", "revenue_log", "avg_price", "product_weight_g"]


def main() -> None:
    df = pd.read_csv(processed_dir() / "product_features.csv")
    df["qty_log"] = np.log1p(df["total_qty"].clip(lower=0))
    df["revenue_log"] = np.log1p(df["total_revenue"].clip(lower=0))
    df["product_weight_g"] = df["product_weight_g"].fillna(df["product_weight_g"].median())
    df["avg_price"] = df["avg_price"].fillna(df["avg_price"].median())

    X = df[FEATURES].astype(float)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

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

    df["cluster"] = best_model.labels_
    sizes = df["cluster"].value_counts().sort_index().to_dict()
    summary = (
        df.groupby("cluster")[["total_qty", "total_revenue", "avg_price"]]
        .mean()
        .round(2)
        .to_dict(orient="index")
    )

    artifact = models_dir() / "product_segmentation.joblib"
    joblib.dump({"scaler": scaler, "model": best_model, "features": FEATURES, "k": best_k}, artifact)
    df[["product_id", "cluster"]].to_csv(processed_dir() / "product_segments.csv", index=False)

    write_metadata(
        "product_segmentation",
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
        algorithm="KMeans (product engagement, standardized)",
        dataset_files=[processed_dir() / "product_features.csv"],
        artifact=artifact.name,
        notes="log1p transforms on qty/revenue; k selected by sampled silhouette.",
    )
    print(f"selected k={best_k} silhouette={best_score:.4f} sizes={sizes}")


if __name__ == "__main__":
    main()
