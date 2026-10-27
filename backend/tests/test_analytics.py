import pytest


def test_filters_endpoint(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    r = client.get("/api/analytics/filters", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "categories" in data
    assert "customer_states" in data
    assert "date_range" in data
    assert "review_scores" in data


def test_analytics_endpoints_auth(client, warehouse_ready):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    endpoints = [
        "/api/analytics/overview",
        "/api/analytics/sales",
        "/api/analytics/orders",
        "/api/analytics/customers",
        "/api/analytics/products",
        "/api/analytics/sellers",
        "/api/analytics/delivery",
    ]
    for ep in endpoints:
        assert client.get(ep).status_code == 401


def test_analytics_endpoints_success_admin(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    endpoints = [
        "/api/analytics/overview",
        "/api/analytics/sales",
        "/api/analytics/orders",
        "/api/analytics/customers",
        "/api/analytics/products",
        "/api/analytics/sellers",
        "/api/analytics/delivery",
    ]
    for ep in endpoints:
        r = client.get(ep, headers=auth)
        assert r.status_code == 200


def test_analytics_endpoints_success_analyst(client, warehouse_ready, analyst_auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    endpoints = [
        "/api/analytics/overview",
        "/api/analytics/sales",
        "/api/analytics/orders",
        "/api/analytics/customers",
        "/api/analytics/products",
        "/api/analytics/sellers",
        "/api/analytics/delivery",
    ]
    for ep in endpoints:
        r = client.get(ep, headers=analyst_auth)
        assert r.status_code == 200


def test_filters_validation(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    # Valid filters
    r = client.get("/api/analytics/sales?date_from=2018-01-01&date_to=2018-12-31", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?category=health_beauty", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?grain=week", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?customer_state=SP", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?seller_state=SP", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?order_status=delivered", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?payment_type=credit_card", headers=auth)
    assert r.status_code == 200

    r = client.get("/api/analytics/sales?review_score=5", headers=auth)
    assert r.status_code == 200

    # Malformed dates
    r = client.get("/api/analytics/sales?date_from=not-a-date", headers=auth)
    assert r.status_code == 422

    # Invalid date range
    r = client.get("/api/analytics/sales?date_from=2018-01-01&date_to=2017-01-01", headers=auth)
    assert r.status_code == 422

    # Invalid review score
    r = client.get("/api/analytics/sales?review_score=6", headers=auth)
    assert r.status_code == 422

    r = client.get("/api/analytics/sales?review_score=0", headers=auth)
    assert r.status_code == 422

    # Invalid grain
    r = client.get("/api/analytics/sales?grain=decade", headers=auth)
    assert r.status_code == 422

    # Invalid categorical filters (depends on DB options, assuming "made_up_status" is not valid)
    r = client.get("/api/analytics/sales?order_status=made_up_status", headers=auth)
    assert r.status_code == 200  # Returns empty data, not 422


def test_reconciliation(client, warehouse_ready, auth):
    """Filtered totals reconcile across endpoints."""
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    # We use a filter to restrict data, e.g. year=2018
    f = "?date_from=2018-01-01&date_to=2018-12-31"

    # Overview
    r1 = client.get(f"/api/analytics/overview{f}", headers=auth)
    kpis1 = r1.json()["kpis"]

    # Sales
    r2 = client.get(f"/api/analytics/sales{f}", headers=auth)
    kpis2 = r2.json()["kpis"]

    # Orders
    r3 = client.get(f"/api/analytics/orders{f}", headers=auth)
    kpis3 = r3.json()["kpis"]

    assert kpis1["total_revenue"] == kpis2["total_revenue"] == kpis3["total_revenue"]
    assert kpis1["total_orders"] == kpis2["total_orders"] == kpis3["total_orders"]

def test_delivery_scope(client, warehouse_ready, auth):
    """Verify delivery metric logic."""
    if not warehouse_ready:
        pytest.skip("warehouse not loaded")

    r = client.get("/api/analytics/delivery", headers=auth)
    assert r.status_code == 200
    data = r.json()

    # Cancelled orders and missing delivery timestamps should not be included in late rate
    # Verify that they are noted in data_quality
    assert "orders_without_delivery" in data["data_quality"]
    assert "cancelled_orders_excluded" in data["data_quality"]
