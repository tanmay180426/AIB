"""Authentication and authorization dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.security import decode_token
from app.services import users as user_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_optional_user(token: str | None = Depends(oauth2_scheme)) -> dict | None:
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    user = user_service.get_user(payload.get("sub", ""))
    return user if user and user.get("is_active") else None


def get_current_user(user: dict | None = Depends(get_optional_user)) -> dict:
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: str):
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role in {roles}",
            )
        return user

    return checker


def require_bi_user(user: dict = Depends(get_current_user)) -> dict:
    """Business intelligence access: admin and analyst only.

    Applied to dashboard / analytics / ML / AI insights / reports routers so that
    anonymous callers get 401 and any non-BI role gets 403, regardless of the
    AUTH_REQUIRED flag.
    """
    if not user_service.role_at_least(user, "analyst"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires analyst or admin role",
        )
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Platform administration access: admin only."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires admin role",
        )
    return user


def require_min_role(min_role: str):
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if not user_service.role_at_least(user, min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {min_role} or higher",
            )
        return user

    return checker


def auth_gate(user: dict | None = Depends(get_optional_user)) -> None:
    """Global gate: enforce authentication on protected routers when enabled.

    In dev (AUTH_REQUIRED=false) requests pass through unauthenticated so the
    app is usable. Set AUTH_REQUIRED=true to enforce auth on all protected
    routers. Admin/sensitive endpoints enforce roles regardless.
    """
    if settings.AUTH_REQUIRED and not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
