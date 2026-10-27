"""Release regressions for inactive accounts and the last active administrator."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.user import User
from app.services import users


@pytest.fixture
def isolated_users(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'users.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(users, 'engine', engine)
    monkeypatch.setattr(users, 'SessionLocal', factory)
    with TestClient(app) as client:
        tokens = client.post('/api/auth/login', data={
            'username': 'admin', 'password': 'abi_test_admin_only'}).json()
        yield client, factory, {'Authorization': f"Bearer {tokens['access_token']}"}
    engine.dispose()


def test_last_active_admin_cannot_be_demoted_with_inactive_admin(isolated_users):
    client, factory, auth = isolated_users
    users.create_user('inactive_admin', 'testpass1', 'admin')
    with factory() as db:
        db.query(User).filter(User.username == 'inactive_admin').update({'is_active': 0})
        db.commit()
    response = client.patch('/api/users/admin/role', json={'role': 'analyst'}, headers=auth)
    assert response.status_code == 409
    assert users.get_user('admin')['role'] == 'admin'


def test_last_active_admin_cannot_deactivate_itself(isolated_users):
    client, _, auth = isolated_users
    response = client.patch('/api/users/admin/status', json={'is_active': False}, headers=auth)
    assert response.status_code == 409
    assert users.get_user('admin')['is_active'] is True


def test_inactive_user_cannot_login_access_or_refresh(isolated_users):
    client, _, auth = isolated_users
    tokens = client.post('/api/auth/login', data={
        'username': 'analyst', 'password': 'abi_test_analyst_only'}).json()
    assert client.patch('/api/users/analyst/status', json={'is_active': False}, headers=auth).status_code == 200
    assert client.post('/api/auth/login', data={
        'username': 'analyst', 'password': 'abi_test_analyst_only'}).status_code == 401
    assert client.get('/api/auth/me', headers={
        'Authorization': f"Bearer {tokens['access_token']}"}).status_code == 401
    assert client.post('/api/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code == 401


def test_multiple_active_admins_can_be_modified_without_lockout(isolated_users):
    client, _, auth = isolated_users
    users.create_user('second_admin', 'testpass1', 'admin')
    tokens = client.post('/api/auth/login', data={
        'username': 'second_admin', 'password': 'testpass1'}).json()
    second = {'Authorization': f"Bearer {tokens['access_token']}"}
    assert client.patch('/api/users/admin/status', json={'is_active': False}, headers=auth).status_code == 200
    assert client.patch('/api/users/admin/role', json={'role': 'analyst'}, headers=second).status_code == 200
    assert client.patch('/api/users/second_admin/role', json={'role': 'analyst'}, headers=second).status_code == 409
    assert client.patch('/api/users/second_admin/status', json={'is_active': False}, headers=second).status_code == 409
    assert client.get('/api/users', headers=second).status_code == 200
