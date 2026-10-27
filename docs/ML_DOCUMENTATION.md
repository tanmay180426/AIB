# ML_DOCUMENTATION.md

## Objectives (all implemented)
- Sales/demand forecasting (time-series)
- Sales prediction (regression)
- Customer segmentation (clustering, RFM-informed)
- Product segmentation (clustering)
- Anomaly detection (unsupervised)

## Data
- Source: Olist (external). Processed datasets in `ml/data/processed/` (gitignored).
- Series spans 2016-09 to 2018-10 (634 days); 99,441 orders, 112,650 line items.
- Forecasting uses a chronological 80/20 split (no shuffling). Regression uses a
  random 80/20 split (seed 42). Clustering/anomaly use all rows (unsupervised).

## Datasets (`ml/src/data_processing/build_datasets.py`)
| File | Rows | Contents |
|---|---|---|
| daily_series.csv | 634 | date, orders, revenue, avg_order_value |
| orders_features.csv | 98,666 | checkout features + item_revenue target |
| customer_rfm.csv | 96,096 | recency_days, frequency, monetary |
| product_features.csv | 32,951 | qty, revenue, avg_price, weight, category |

## Models (see `docs/ML_BASELINES.md` for metrics; metadata in `ml/models/*.metadata.json`)
| Feature | Algorithm | Status |
|---|---|---|
| sales_forecast | LinearRegression (lag/rolling) | available |
| sales_prediction | best of LinearRegression / RandomForest | available |
| customer_segmentation | KMeans on RFM | available |
| product_segmentation | KMeans on engagement features | available |
| anomaly_detection | IsolationForest | available |

## Interfaces (contracts)
- Model metadata JSON: `{name, version, target, algorithm, trained_at,
  dataset_fingerprint, features_schema, metrics, status, artifact, notes}`.
- Backend service: `backend/app/services/ml.py` reads metadata and lazily loads
  artifacts (`ML_MODELS_DIR`, `ML_DATA_DIR` overridable).
- API (under `/api/ml`):
  - `GET /status` — per-feature real status + metrics
  - `GET /models/{name}` — full metadata
  - `GET /forecast?periods=N&target=[orders|revenue]` — recursive daily order or revenue forecast
  - `GET /segments/customers` — customer cluster summary
  - `GET /product-segmentation` — filter-aware inference using the saved scaler and KMeans
  - `GET /anomalies` — anomaly metrics
  - `POST /predict/sales` — order item revenue prediction

## Statuses
`planned | data_preparation | training | testing | integration | available | failed`

The API reports `available` only when metadata says so AND the local artifact
exists; on a fresh clone (artifacts gitignored) it reports `integration`.

## Integration
- Models serialized with joblib. Backend loads on demand; heavy deps (pandas,
  numpy, scikit-learn, joblib) declared in `backend/requirements.txt`.
- No fake predictions/metrics anywhere: UI shows honest status and real values.

## Known constraints
- Historical only; no external signals (holidays, marketing).
- Delivery timestamps missing for 2,965 orders; excluded from delivery metrics.
- Original training-environment note (Python 3.14): statsmodels/XGBoost unavailable -> sklearn-only.
- MAPE is high on sparse/skewed targets and is reported transparently.

## Selected datasets and contracts
All inference routes use the authorized selected dataset and shared filters.
Compatibility is checked before loading an artifact. Incompatible data returns
Not Applicable; upload never starts training. Existing transformations and saved
models are reused. Offline Olist metrics are not upload-specific evaluations.
See [Universal datasets](UNIVERSAL_DATASETS.md) for each model contract, units,
minimum history, feature completeness and known limitations. The current ML UI
provides Metrics, Product Segmentation and Revenue Forecast pages; all six model
artifacts remain accessible through their existing API endpoints.
