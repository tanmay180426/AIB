# ML_BASELINES.md

Real, locally-produced baseline results. All numbers come from the training
scripts in `ml/` and are also stored in `ml/models/*.metadata.json`.
Reproduce with `cd ml && python run_all.py`.

Dataset: Olist Brazilian e-commerce (raw CSVs at `%USERPROFILE%/Downloads/olist`).
Daily series spans 2016-09 to 2018-10 (634 days).

## 1. Sales / demand forecast — daily orders
- Algorithm: Linear Regression on lag/rolling features (lag1, lag7, lag14, lag30, roll7, roll30)
- Split: chronological 80/20 (no shuffling -> no leakage); n_train=483, n_test=121
- Model: MAE 35.28, RMSE 44.07, MAPE 302.93*
- Baseline: seasonal naive (value 7 days earlier) MAE 56.07, RMSE 74.80
- Verdict: beats the naive baseline on MAE/RMSE.

## 2. Sales forecast — daily revenue
- Same features/split on daily revenue.
- Model: MAE 5390.81, RMSE 6860.65, MAPE 77.30
- Baseline: seasonal naive MAE 7793.53, RMSE 10652.29

## 3. Sales prediction — order item revenue
- Features (checkout-time): purchase month/weekday/hour, customer_state, n_items, dominant product category
- Split: random 80/20, seed=42; n_train=78,932, n_test=19,734
- Linear Regression: MAE 96.05, RMSE 215.93, MAPE 139.46  (selected)
- Random Forest (100 trees, depth 12): MAE 97.12, RMSE 217.55, MAPE 142.36
- Verdict: linear model marginally better; selected.

## 4. Customer segmentation (RFM + K-Means)
- Features: recency_days, frequency, log1p(monetary), standardized
- k selected by silhouette (sampled 10k): k=2 -> 0.686 (best); k=3 0.363; k=4 0.362; k=5 0.330; k=6 0.330
- Clusters: 0 = 93,099 (regular), 1 = 2,997 (high-value/repeat)

## 5. Product segmentation (K-Means)
- Features: log1p(total_qty), log1p(total_revenue), avg_price, product_weight_g
- k selected by silhouette: k=4 -> 0.480 (best)
- Cluster sizes: 2,187 / 6,746 / 23,279 / 739

## 6. Anomaly detection — daily orders/revenue
- Algorithm: Isolation Forest, contamination=0.03
- 19/634 days flagged. Top anomaly: 2017-11-24 (Black Friday, 1,176 orders).

## Limitations (honest)
- High MAPE on order/revenue series is driven by near-zero days and heavy skew; it is reported, not hidden.
- Statistical models (statsmodels/SARIMA) and gradient boosting (XGBoost) are not installed on the current
  Python 3.14 environment; sklearn-only implementations were used and are documented as such.
- Predictions use historical data only; no external signals (marketing, holidays calendar).
