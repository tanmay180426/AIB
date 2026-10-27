"""Computational artifact smoke test; run ONLY in the isolated audit container.

This is not the missing training pipeline or a performance evaluation.
The container mounts only the candidate and this script read-only, has no network,
runs as non-root, drops capabilities and uses a read-only root filesystem.
"""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn


root = Path("/candidate")
artifact = root / "gradient_boosting_sales_model.joblib"
manifest = json.loads((root / "provenance.json").read_text())
assert hashlib.sha256(artifact.read_bytes()).hexdigest() == manifest["artifact_sha256"]
assert sklearn.__version__ == "1.6.1"
metadata = json.loads((root / "source_model_metadata.json").read_text())
registry = json.loads((root / "source_registry_metadata.json").read_text())
features = metadata["features"]
assert features == registry["features_schema"]

model = joblib.load(artifact)
assert type(model).__module__ == "sklearn.ensemble._gb"
assert type(model).__name__ == "GradientBoostingRegressor"
assert int(model.n_features_in_) == len(features) == 27
assert list(model.feature_names_in_) == features
for key in ("n_estimators", "learning_rate", "max_depth", "random_state"):
    assert getattr(model, key) == metadata[key]

# Constructed feature-level vector in the claimed daily-commerce domain.
# Training transformations, real/synthetic composition and accuracy remain unknown.
values = {name: 10000.0 for name in features}
values.update(year=2024, month=9, quarter=3, day_of_week=3,
              week_of_year=36, day_of_month=5, is_weekend=0)
values.update({name: 70.0 for name in features if name.startswith("orders_lag")})
values.update({name: 1000.0 for name in features if "roll_std" in name})
row = pd.DataFrame([[values[name] for name in features]], columns=features)
result = model.predict(row)
assert result.shape == (1,)
assert np.isfinite(result).all()

# Estimator boundary validation, not API or pipeline compatibility testing.
malformed_rejected = False
try:
    model.predict(row.iloc[:, :-1])
except ValueError:
    malformed_rejected = True
assert malformed_rejected
nonfinite_rejected = False
try:
    invalid = row.astype(float).copy()
    invalid.iloc[0, 0] = np.inf
    model.predict(invalid)
except ValueError:
    nonfinite_rejected = True
assert nonfinite_rejected

print(json.dumps({
    "scope": "constructed feature-level computational smoke only",
    "estimator": type(model).__name__, "features": features,
    "configuration_matches_metadata": True, "feature_order_matches": True,
    "versions": {"sklearn": sklearn.__version__, "numpy": np.__version__,
                 "pandas": pd.__version__, "joblib": joblib.__version__},
    "input": row.iloc[0].to_dict(), "output_shape": list(result.shape),
    "prediction": result.tolist(), "finite": True,
    "malformed_rejected": malformed_rejected, "nonfinite_rejected": nonfinite_rejected,
    "training_preprocessing_verified": False, "performance_evaluated": False,
    "activation_status": "blocked"
}, allow_nan=False))
