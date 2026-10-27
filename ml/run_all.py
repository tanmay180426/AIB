"""Run the full ML pipeline: build datasets, then train every model."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STEPS = [
    "src.data_processing.build_datasets",
    "src.forecasting.train_forecast",
    "src.prediction.train_sales_prediction",
    "src.customer_segmentation.train_customer_segmentation",
    "src.product_segmentation.train_product_segmentation",
    "src.anomaly_detection.train_anomaly",
]


def main() -> None:
    for step in STEPS:
        print(f"\n=== {step} ===")
        runpy.run_module(step, run_name="__main__")


if __name__ == "__main__":
    main()
