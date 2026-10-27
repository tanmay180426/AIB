"""Password hashing and JWT token helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Annotated

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import AfterValidator

from app.core.config import settings

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_new_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes.")
    return password


NewPassword = Annotated[str, AfterValidator(validate_new_password)]


def hash_password(password: str) -> str:
    validate_new_password(password)
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def _encode(subject: str, role: str, token_type: str, expires_minutes: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {"sub": subject, "role": role, "type": token_type, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    return _encode(
        subject, role, "access", expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )


def create_refresh_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    return _encode(
        subject, role, "refresh", expires_minutes or settings.REFRESH_TOKEN_EXPIRE_MINUTES
    )


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
