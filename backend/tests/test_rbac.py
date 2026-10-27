"""Direct API verification of the two-role permission matrix.

The table in docs/RBAC.md is the source of truth:

    business intelligence (dashboard, analytics, ML, AI insights, reports)
        -> admin + analyst, anonymous -> 401
    platform administration (users, roles, system, ETL, warehouse, ML admin,
    settings)
        -> admin only, analyst -> 403
"""

BI_GET = [
    "/api/dashboard/kpis",
    "/api/dashboard/monthly-revenue",
    "/api/dashboard/revenue-by-category",
    "/api/dashboard/orders-by-status",
    "/api/analytics/sales",
    "/api/analytics/orders",
    "/api/analytics/customers",
    "/api/analytics/products",
    "/api/analytics/sellers",
    "/api/analytics/delivery",
    "/api/ml/status",
    "/api/ml/anomalies",
    "/api/ml/segments/customers",
    "/api/ml/forecast?periods=7",
    "/api/ml/models/sales_prediction",
    "/api/insights/status",
    "/api/reports/export?report=kpis",
    "/api/reports/export?report=monthly_revenue",
]

PREDICT_PAYLOAD = {
    "purchase_month": 11,
    "purchase_weekday": 4,
    "purchase_hour": 15,
    "n_items": 2,
    "customer_state": "SP",
    "product_category_name": "bed_bath_table",
}

ADMIN_GET = [
    "/api/admin/system/status",
    "/api/admin/data/etl/status",
    "/api/admin/warehouse/status",
    "/api/admin/ml/status",
    "/api/admin/settings",
    "/api/users",
    "/api/auth/admin/users",
]


def test_bi_endpoints_allowed_for_both_roles(client, auth, analyst_auth):
    # Authorization only: never 401/403. 503 is the honest "artifact missing"
    # response on a machine that has not trained the models yet.
    for path in BI_GET:
        for headers in (analyst_auth, auth):
            assert client.get(path, headers=headers).status_code in {200, 404, 503}, path


def test_ml_predict_allowed_for_both_roles_and_denied_for_anonymous(client, auth, analyst_auth):
    assert client.post("/api/ml/predict/sales", json=PREDICT_PAYLOAD, headers=analyst_auth).status_code in {200, 503}
    assert client.post("/api/ml/predict/sales", json=PREDICT_PAYLOAD, headers=auth).status_code in {200, 503}
    assert client.post("/api/ml/predict/sales", json=PREDICT_PAYLOAD).status_code == 401


def test_bi_endpoints_reject_anonymous(client):
    for path in BI_GET:
        assert client.get(path).status_code == 401, path


def test_admin_endpoints_allowed_for_admin(client, auth):
    for path in ADMIN_GET:
        assert client.get(path, headers=auth).status_code == 200, path


def test_admin_endpoints_forbidden_for_analyst(client, analyst_auth):
    for path in ADMIN_GET:
        r = client.get(path, headers=analyst_auth)
        assert r.status_code == 403, f"{path} -> {r.status_code}"
        assert "admin" in r.json()["detail"].lower()


def test_admin_endpoints_reject_anonymous(client):
    for path in ADMIN_GET:
        assert client.get(path).status_code == 401, path


def test_ai_insights_allowed_for_both_and_denied_for_anonymous(client, auth, analyst_auth):
    payload = {"question": "What were total orders?"}
    assert client.post("/api/insights/query", json=payload, headers=analyst_auth).status_code == 200
    assert client.post("/api/insights/query", json=payload, headers=auth).status_code == 200
    assert client.post("/api/insights/query", json=payload).status_code == 401


def test_authorization_ignores_the_jwt_role_claim(client):
    """Backend authority: the role is read from the database per request, so a
    forged/stale `role` claim inside a valid token grants nothing."""
    from app.core.security import create_access_token

    forged = {"Authorization": f"Bearer {create_access_token('analyst', 'admin')}"}
    assert client.get("/api/dashboard/kpis", headers=forged).status_code == 200
    assert client.get("/api/users", headers=forged).status_code == 403
    assert client.get("/api/admin/settings", headers=forged).status_code == 403


def test_role_endpoint_validates_input(client, auth, analyst_auth):
    # analyst cannot change roles
    r = client.patch("/api/users/analyst/role", json={"role": "admin"}, headers=analyst_auth)
    assert r.status_code == 403
    # admin cannot assign an unknown role
    r = client.patch("/api/users/analyst/role", json={"role": "superuser"}, headers=auth)
    assert r.status_code == 422
    r = client.patch("/api/users/analyst/role", json={"role": "viewer"}, headers=auth)
    assert r.status_code == 422
    # assigning a valid role succeeds (analyst -> admin -> back to analyst)
    r = client.patch("/api/users/analyst/role", json={"role": "admin"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
    r = client.patch("/api/users/analyst/role", json={"role": "analyst"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "analyst"
