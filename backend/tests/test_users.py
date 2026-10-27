import uuid


def test_get_me(client, auth):
    r = client.get("/api/users/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "admin"


def test_list_users_admin_only(client, auth, analyst_auth):
    r = client.get("/api/users", headers=auth)
    assert r.status_code == 200
    assert all(u["role"] in {"admin", "analyst"} for u in r.json()["users"])
    assert client.get("/api/users", headers=analyst_auth).status_code == 403
    assert client.get("/api/users").status_code == 401


def test_register_and_change_password(client, auth):
    username = "u" + uuid.uuid4().hex[:8]
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "initial1", "role": "analyst"},
        headers=auth,
    )
    assert reg.status_code == 201

    token = client.post(
        "/api/auth/login", data={"username": username, "password": "initial1"}
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    wrong = client.patch(
        "/api/users/me",
        json={"current_password": "nope", "new_password": "newpass1"},
        headers=h,
    )
    assert wrong.status_code == 400

    ok = client.patch(
        "/api/users/me",
        json={"current_password": "initial1", "new_password": "newpass1"},
        headers=h,
    )
    assert ok.status_code == 200
    assert client.post(
        "/api/auth/login", data={"username": username, "password": "newpass1"}
    ).status_code == 200


def test_analyst_cannot_register_users(client, analyst_auth):
    r = client.post(
        "/api/auth/register",
        json={"username": "nope" + uuid.uuid4().hex[:6], "password": "pw123456", "role": "analyst"},
        headers=analyst_auth,
    )
    assert r.status_code == 403


def test_retired_and_unknown_roles_rejected(client, auth):
    username = "v" + uuid.uuid4().hex[:8]
    r = client.post(
        "/api/auth/register",
        json={"username": username, "password": "pw123456", "role": "viewer"},
        headers=auth,
    )
    assert r.status_code == 422

    username2 = "g" + uuid.uuid4().hex[:8]
    client.post(
        "/api/auth/register",
        json={"username": username2, "password": "pw123456", "role": "analyst"},
        headers=auth,
    )
    bad = client.patch(f"/api/users/{username2}/role", json={"role": "viewer"}, headers=auth)
    assert bad.status_code == 422


def test_admin_can_change_role(client, auth):
    username = "r" + uuid.uuid4().hex[:8]
    created = client.post(
        "/api/auth/register",
        json={"username": username, "password": "pw123456", "role": "analyst"},
        headers=auth,
    )
    assert created.status_code == 201
    r = client.patch(f"/api/users/{username}/role", json={"role": "admin"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"

    # put the test user back so the platform keeps exactly one seeded admin
    r = client.patch(f"/api/users/{username}/role", json={"role": "analyst"}, headers=auth)
    assert r.status_code == 200


def test_last_admin_cannot_be_demoted(client, auth):
    """Never allow the platform to reach zero admins."""
    tmp = "l" + uuid.uuid4().hex[:8]
    created = client.post(
        "/api/auth/register",
        json={"username": tmp, "password": "pw123456", "role": "admin"},
        headers=auth,
    )
    assert created.status_code == 201

    # step 1: demote the seeded admin -> only `tmp` remains an admin
    demote_self = client.patch(
        "/api/users/admin/role", json={"role": "analyst"}, headers=auth
    )
    assert demote_self.status_code == 200

    # step 2: the last admin may not demote itself
    tmp_token = client.post(
        "/api/auth/login", data={"username": tmp, "password": "pw123456"}
    ).json()["access_token"]
    tmp_auth = {"Authorization": f"Bearer {tmp_token}"}
    blocked = client.patch(f"/api/users/{tmp}/role", json={"role": "analyst"}, headers=tmp_auth)
    assert blocked.status_code == 409
    assert "last" in blocked.json()["detail"].lower()

    # step 3: restore the seeded admin, then demote the temporary admin
    restore = client.patch("/api/users/admin/role", json={"role": "admin"}, headers=tmp_auth)
    assert restore.status_code == 200
    cleanup = client.patch(f"/api/users/{tmp}/role", json={"role": "analyst"}, headers=tmp_auth)
    assert cleanup.status_code == 200

    me = client.get("/api/auth/me", headers=auth)
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "admin"
