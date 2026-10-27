# Model metadata schema (conceptual)
# {
#   "name": "sales_forecast",
#   "version": "0.1.0",
#   "target": "daily_orders",
#   "trained_at": "ISO8601",
#   "dataset_fingerprint": "sha256 of processed data",
#   "features_schema": [...],
#   "metrics": {"mae": 0, "rmse": 0, "mape": null},
#   "status": "planned|training|testing|integration|available|failed"
# }

Each deployed model also has a `contract`: required and optional semantic
roles, expected data types, training domain, monetary units, minimum
observations, frequency, feature transformations, supported filters, and output
type. The backend checks this contract before loading artifacts. A compatible
schema is not a measurement of generalization accuracy on a new dataset.
Training/evaluation metrics retain their original Olist scope.
