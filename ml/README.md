# Machine Learning

Parallel track to the website. Models are trained on the Olist dataset and served
by the FastAPI backend. Raw data lives outside the repo; processed data, model
artifacts, and reports are local (gitignored). Only metadata JSON is committed.

## Pipeline
1. `python -m src.data_processing.build_datasets`  -> builds analysis-ready datasets
2. Train:
   - `python -m src.forecasting.train_forecast`                  (sales/demand forecast)
   - `python -m src.prediction.train_sales_prediction`           (order item revenue)
   - `python -m src.customer_segmentation.train_customer_segmentation`
   - `python -m src.product_segmentation.train_product_segmentation`
   - `python -m src.anomaly_detection.train_anomaly`
3. Or run everything: `python run_all.py`

All commands run from the `ml/` directory. Requires the raw Olist CSVs at
`%USERPROFILE%/Downloads/olist` (override with `OLIST_DIR`).

## Layout
- `src/common/`              paths, metadata writer
- `src/data_processing/`     dataset builders
- `src/forecasting/`         time-series forecasting
- `src/prediction/`          sales regression
- `src/customer_segmentation/`, `src/product_segmentation/`
- `src/anomaly_detection/`
- `src/evaluation/`          metric helpers
- `models/`                  artifacts (`*.joblib`) + `*.metadata.json`
- `data/processed/`          generated datasets
- `reports/`                 metric reports

## Model status
Status progresses: `planned -> data_preparation -> training -> testing ->
integration -> available`. The website reads `models/*.metadata.json` and only
shows `available` when real metrics and the local artifact both exist.
