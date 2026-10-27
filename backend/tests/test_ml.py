EXPECTED_FEATURES = {
    "sales_forecast",
    "sales_prediction",
    "customer_segmentation",
    "product_segmentation",
    "anomaly_detection",
}


def test_ml_status_lists_all_features(client, analyst_auth):
    r = client.get("/api/ml/status", headers=analyst_auth)
    assert r.status_code == 200
    names = {f["name"] for f in r.json()["features"]}
    assert EXPECTED_FEATURES <= names


def test_ml_status_is_honest(client, analyst_auth):
    for f in client.get("/api/ml/status", headers=analyst_auth).json()["features"]:
        assert f["status"] in {
            "planned",
            "data_preparation",
            "training",
            "testing",
            "integration",
            "available",
            "failed",
        }


def test_ml_requires_authentication(client):
    assert client.get("/api/ml/status").status_code == 401


def test_ml_endpoints_available_to_both_roles(client, analyst_auth, auth):
    for headers in (analyst_auth, auth):
        assert client.get("/api/ml/status", headers=headers).status_code == 200
        assert client.get("/api/ml/anomalies", headers=headers).status_code == 200
        assert client.get("/api/ml/segments/customers", headers=headers).status_code == 200
        assert client.get("/api/ml/product-segmentation", headers=headers).status_code == 200
        assert client.get("/api/ml/forecast?target=orders", headers=headers).status_code == 200
        assert client.get("/api/ml/forecast?target=revenue", headers=headers).status_code == 200

def test_ml_invalid_forecast_target(client, analyst_auth):
    assert client.get("/api/ml/forecast?target=invalid", headers=analyst_auth).status_code == 400
