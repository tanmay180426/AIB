"""Pytest fixtures for the backend API tests."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Keep tests deterministic/fast: never call a live LLM during the test suite,
# even if backend/.env enables the assistant.
os.environ["ENABLE_LLM_ASSISTANT"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tests.database_fixture import test_storage, seed_synthetic_warehouse  # noqa: E402


def pytest_addoption(parser):
    parser.addoption('--reference-db', default=None, help='Optional read-only Olist warehouse snapshot for baseline regressions.')
    parser.addoption('--free-only-network', action='store_true', help='Deny non-loopback DNS/socket connections and strip hosted-provider credentials in this test process.')


def pytest_configure(config):
    if config.getoption('--free-only-network'):
        for name in list(os.environ):
            if any(provider in name.upper() for provider in ('OPENAI', 'ANTHROPIC', 'GEMINI', 'OPENROUTER')) and any(token in name.upper() for token in ('KEY', 'TOKEN')):
                os.environ.pop(name, None)
    storage = test_storage(config.getoption('--reference-db'))
    path = storage.__enter__()
    config._sem5_storage = storage
    config._sem5_test_database = path
    os.environ['DATABASE_URL'] = f'sqlite:///{path.as_posix()}'
    os.environ['AUTH_ADMIN_PASSWORD'] = 'abi_test_admin_only'
    os.environ['AUTH_ANALYST_PASSWORD'] = 'abi_test_analyst_only'
    from app.database.session import engine
    if not config.getoption('--reference-db'):
        seed_synthetic_warehouse(engine)


def pytest_unconfigure(config):
    if hasattr(config, '_sem5_storage'):
        from app.database.session import engine
        engine.dispose()
        config._sem5_storage.__exit__(None, None, None)


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.main import app
    return TestClient(app)


def _warehouse_count(table: str) -> int:
    from sqlalchemy import inspect, text

    from app.database.session import engine

    insp = inspect(engine)
    if table not in insp.get_table_names():
        return 0
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)


@pytest.fixture(scope="session")
def warehouse_ready(request) -> bool:
    return bool(request.config.getoption('--reference-db')) and _warehouse_count("fact_orders") > 0


def _token(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_token(client: TestClient) -> str:
    return _token(client, "admin", "abi_test_admin_only")


@pytest.fixture(scope="session")
def analyst_token(client: TestClient) -> str:
    return _token(client, "analyst", "abi_test_analyst_only")


@pytest.fixture()
def auth(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture()
def analyst_auth(analyst_token: str) -> dict:
    return {"Authorization": f"Bearer {analyst_token}"}


@pytest.fixture(autouse=True)
def free_only_network_guard(request, monkeypatch):
    if not request.config.getoption('--free-only-network'):
        yield
        return
    import socket
    from ipaddress import ip_address
    violations = []
    def check(host):
        if isinstance(host, bytes):
            host = host.decode('ascii')
        if host == 'localhost':
            return
        try:
            if ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        violations.append('Non-loopback network access attempted.')
        raise AssertionError('Non-loopback network access blocked by free-only test guard.')
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_resolve = socket.getaddrinfo
    def connect(sock, address):
        if isinstance(address, tuple):
            check(address[0])
        return original_connect(sock, address)
    def connect_ex(sock, address):
        if isinstance(address, tuple):
            check(address[0])
        return original_connect_ex(sock, address)
    def resolve(host, *args, **kwargs):
        check(host)
        return original_resolve(host, *args, **kwargs)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', connect_ex)
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    yield
    assert not violations, 'Core request attempted external network access, even if its exception was handled.'
