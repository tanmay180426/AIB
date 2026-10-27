def _login(client):
    return client.post("/api/auth/login", data={"username": "admin", "password": "abi_test_admin_only"}).json()


def test_login_returns_refresh_and_refresh_works(client):
    tokens = _login(client)
    assert "refresh_token" in tokens

    r = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_access_token_cannot_be_used_to_refresh(client):
    tokens = _login(client)
    r = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401
