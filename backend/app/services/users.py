"""DB-backed user registry with hashed passwords and roles.

Users live in the `app_user` table. Default accounts are seeded on first use
from the AUTH_*_PASSWORD settings. Passwords are stored only as bcrypt hashes.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.database.session import Base, SessionLocal, engine
from app.models.user import User


class LastAdminError(Exception):
    """Raised when an operation would leave the platform with zero admins."""


# Two-role model: every user is either an analyst (business intelligence) or an
# admin (business intelligence + platform administration).
ROLE_RANK = {"analyst": 1, "admin": 2}
VALID_ROLES = frozenset(ROLE_RANK)

_SEED = {
    "admin": ("admin", settings.AUTH_ADMIN_PASSWORD),
    "analyst": ("analyst", settings.AUTH_ANALYST_PASSWORD),
}

LEGACY_ROLE_MIGRATION = {"viewer": "analyst", "user": "analyst"}


def validate_role(role: str) -> str:
    """Reject anything that is not `analyst` or `admin` (never trust the caller)."""
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role}. Valid roles: {sorted(VALID_ROLES)}")
    return role


def _migrate_legacy_roles(db) -> None:
    """Move retired roles to analyst. Viewer users are never promoted to admin."""
    # Authentication is read-heavy. Do not acquire SQLite's writer lock for
    # empty migration updates on every concurrent analytical request.
    if db.scalar(select(User.id).where(User.role.in_(LEGACY_ROLE_MIGRATION)).limit(1)) is None:
        return
    for old, new in LEGACY_ROLE_MIGRATION.items():
        db.query(User).filter(User.role == old).update({User.role: new}, synchronize_session=False)


def _validate_seed_credentials() -> None:
    """Require private first-run passwords rather than shipping known defaults."""
    for _, (role, password) in _SEED.items():
        normalized = password.strip().casefold() if isinstance(password, str) else ""
        if not normalized or normalized.startswith(("replace_with_", "change_me_")):
            raise RuntimeError(
                f"Set a unique AUTH_{role.upper()}_PASSWORD in the local environment before first use."
            )


def _ensure_schema() -> None:
    Base.metadata.create_all(engine, tables=[User.__table__])
    with SessionLocal() as db:
        _migrate_legacy_roles(db)
        if db.scalar(select(User.id).limit(1)) is None:
            _validate_seed_credentials()
            for username, (role, password) in _SEED.items():
                db.add(User(username=username, role=role, hashed_password=hash_password(password)))
        db.commit()


def count_users(role: str | None = None) -> int:
    _ensure_schema()
    with SessionLocal() as db:
        stmt = select(func.count()).select_from(User)
        if role:
            stmt = stmt.where(User.role == role)
        return int(db.scalar(stmt) or 0)


def _to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat() if user.created_at else None
    }


def get_user(username: str) -> dict | None:
    _ensure_schema()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        return _to_dict(user) if user else None


def list_users() -> list[dict]:
    _ensure_schema()
    with SessionLocal() as db:
        return [_to_dict(u) for u in db.scalars(select(User).order_by(User.id)).all()]


def authenticate(username: str, password: str) -> dict | None:
    _ensure_schema()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user and user.is_active and verify_password(password, user.hashed_password):
            return _to_dict(user)
    return None


def create_user(username: str, password: str, role: str = "analyst") -> dict:
    _ensure_schema()
    validate_role(role)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise ValueError("username already exists")
        user = User(username=username, role=role, hashed_password=hash_password(password))
        db.add(user)
        db.commit()
        db.refresh(user)
        return _to_dict(user)


def update_password(username: str, new_password: str) -> bool:
    _ensure_schema()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            return False
        user.hashed_password = hash_password(new_password)
        db.commit()
        return True


def update_role(username: str, role: str) -> dict | None:
    _ensure_schema()
    validate_role(role)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            return None
        if user.role == "admin" and user.is_active and role != "admin":
            admins = int(
                db.scalar(
                    select(func.count()).select_from(User).where(User.role == "admin", User.is_active == 1)
                )
                or 0
            )
            if admins <= 1:
                raise LastAdminError(
                    "cannot demote the last active admin; promote another active admin first"
                )
        user.role = role
        db.commit()
        return _to_dict(user)


def has_role(user: dict, *roles: str) -> bool:
    return user.get("role") in roles


def role_at_least(user: dict, min_role: str) -> bool:
    return ROLE_RANK.get(user.get("role", ""), 0) >= ROLE_RANK.get(min_role, 99)


def update_status(username: str, is_active: bool) -> dict | None:
    _ensure_schema()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            return None
        if user.role == "admin" and not is_active:
            admins = int(
                db.scalar(
                    select(func.count()).select_from(User).where(User.role == "admin", User.is_active == 1)
                )
                or 0
            )
            # If they are the last active admin, don't let them deactivate themselves
            if admins <= 1 and user.is_active:
                raise LastAdminError(
                    "cannot deactivate the last active admin"
                )
        user.is_active = 1 if is_active else 0
        db.commit()
        return _to_dict(user)
