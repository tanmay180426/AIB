import pytest


def test_kpis_csv_export(client, analyst_auth, warehouse_ready):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded (run backend ETL)")
    r = client.get("/api/reports/export?report=kpis", headers=analyst_auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "metric,value" in r.text


def test_all_reports_available_to_both_roles(client, analyst_auth, auth, warehouse_ready):
    if not warehouse_ready:
        pytest.skip("warehouse not loaded (run backend ETL)")

    for report in ("kpis", "monthly_revenue", "revenue_by_category", "orders_by_status"):
        assert (
            client.get(f"/api/reports/export?report={report}", headers=analyst_auth).status_code
            == 200
        )
        assert (
            client.get(f"/api/reports/export?report={report}", headers=auth).status_code == 200
        )


def test_export_requires_authentication(client):
    assert client.get("/api/reports/export?report=kpis").status_code == 401


def test_unknown_report_returns_404(client, auth):
    assert client.get("/api/reports/export?report=does_not_exist", headers=auth).status_code == 404
