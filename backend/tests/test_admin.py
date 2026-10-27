def test_system_status_admin_only(client, auth, analyst_auth):
    r = client.get("/api/admin/system/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["app"]
    assert "version" in body and "database" in body

    assert client.get("/api/admin/system/status", headers=analyst_auth).status_code == 403
    assert client.get("/api/admin/system/status").status_code == 401


def test_etl_status_admin_only(client, auth, analyst_auth):
    r = client.get("/api/admin/data/etl/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "loaded" in body
    assert "tables" in body

    assert client.get("/api/admin/data/etl/status", headers=analyst_auth).status_code == 403


def test_warehouse_status_admin_only(client, auth, analyst_auth):
    r = client.get("/api/admin/warehouse/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["dialect"] in {"sqlite", "postgresql"}
    assert "warehouse_tables" in body and "total_rows" in body
    assert "complete" in body

    assert client.get("/api/admin/warehouse/status", headers=analyst_auth).status_code == 403


def test_ml_admin_status_admin_only(client, auth, analyst_auth):
    r = client.get("/api/admin/ml/status", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "artifacts" in body and "features" in body
    assert isinstance(body["artifact_count"], int)

    assert client.get("/api/admin/ml/status", headers=analyst_auth).status_code == 403


def test_system_settings_admin_only_and_secret_free(client, auth, analyst_auth):
    r = client.get("/api/admin/settings", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["roles"] == ["admin", "analyst"]
    assert body["secrets_exposed"] is False

    raw = r.text
    assert "SECRET_KEY" not in raw
    assert "replace_with_test_only_secret" not in raw

    assert client.get("/api/admin/settings", headers=analyst_auth).status_code == 403
