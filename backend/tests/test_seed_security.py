import pytest

from app.services import users


def test_first_run_seed_requires_private_non_placeholder_passwords(monkeypatch):
    monkeypatch.setattr(users, "_SEED", {
        "admin": ("admin", "REPLACE_WITH_UNIQUE_ADMIN_PASSWORD"),
        "analyst": ("analyst", "REPLACE_WITH_UNIQUE_ANALYST_PASSWORD"),
    })

    with pytest.raises(RuntimeError, match="Set a unique AUTH_ADMIN_PASSWORD"):
        users._validate_seed_credentials()


def test_first_run_seed_accepts_configured_passwords(monkeypatch):
    monkeypatch.setattr(users, "_SEED", {
        "admin": ("admin", "independent-private-admin-secret"),
        "analyst": ("analyst", "independent-private-analyst-secret"),
    })

    users._validate_seed_credentials()
