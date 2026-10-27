import pytest
from pydantic import ValidationError

from app.api.routes.auth import RegisterRequest
from app.api.routes.users import CreateUser, PasswordChange
from app.core.security import hash_password, pwd_context, verify_password


@pytest.mark.parametrize('password', ['A' * 72, 'é' * 36, 'short123'])
def test_safe_password_boundaries(password):
    assert verify_password(password, hash_password(password))
    assert RegisterRequest(username='valid', password=password).password == password


@pytest.mark.parametrize('password', ['A' * 73, 'A' * 128, 'é' * 36 + 'a', 'é' * 37,
                                      'A' * 72 + 'first', 'A' * 72 + 'second'])
def test_new_passwords_reject_over_72_bytes(password):
    with pytest.raises(ValueError, match='72 UTF-8 bytes'):
        hash_password(password)
    for schema, payload in [(RegisterRequest, {'username': 'valid', 'password': password}),
                            (CreateUser, {'username': 'valid', 'password': password, 'role': 'analyst'}),
                            (PasswordChange, {'current_password': 'oldpass', 'new_password': password})]:
        with pytest.raises(ValidationError, match='72 UTF-8 bytes'):
            schema(**payload)


def test_existing_bcrypt_hashes_are_not_migrated_or_rejected():
    legacy = pwd_context.hash('A' * 72 + 'legacy')
    assert verify_password('A' * 72 + 'legacy', legacy)
    assert verify_password('short123', pwd_context.hash('short123'))


def test_existing_seeded_logins_still_work(client):
    for name, password in [('admin', 'abi_test_admin_only'), ('analyst', 'abi_test_analyst_only')]:
        assert client.post('/api/auth/login', data={'username': name, 'password': password}).status_code == 200


def test_existing_long_password_login_remains_compatible(client):
    from app.database.session import SessionLocal
    from app.models.user import User
    password = 'A' * 72 + 'legacy'
    with SessionLocal() as db:
        db.add(User(username='legacy-long-password', role='analyst', hashed_password=pwd_context.hash(password)))
        db.commit()
    assert client.post('/api/auth/login', data={'username': 'legacy-long-password', 'password': password}).status_code == 200


def test_registration_and_password_change_reject_oversized_passwords(client, auth):
    password = 'é' * 37
    assert client.post('/api/auth/register', headers=auth, json={'username': 'oversize', 'password': password}).status_code == 422
    assert client.post('/api/users', headers=auth, json={'username': 'oversize', 'role': 'analyst', 'password': password}).status_code == 422
    assert client.patch('/api/users/me', headers=auth, json={'current_password': 'abi_test_admin_only', 'new_password': password}).status_code == 422
