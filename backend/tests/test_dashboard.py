import pytest


def test_kpis_admin(client, warehouse_ready, auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded (run backend ETL)")

    r = client.get("/api/dashboard/kpis", headers=auth)
    assert r.status_code == 200
    k = r.json()["kpis"]
    assert k["total_orders"] > 0
    assert k["total_revenue"] > 0
    assert k["avg_order_value"] > 0


def test_kpis_analyst(client, warehouse_ready, analyst_auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded (run backend ETL)")

    r = client.get("/api/dashboard/kpis", headers=analyst_auth)
    assert r.status_code == 200
    assert r.json()["kpis"]["total_orders"] > 0


def test_dashboard_requires_authentication(client):
    assert client.get("/api/dashboard/kpis").status_code == 401


def test_monthly_revenue_series(client, warehouse_ready, analyst_auth):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded (run backend ETL)")

    r = client.get("/api/dashboard/monthly-revenue", headers=analyst_auth)
    assert r.status_code == 200
    series = r.json()["series"]
    assert len(series) >= 12
    assert {"period", "orders", "revenue"} <= set(series[0].keys())
