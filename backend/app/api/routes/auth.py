from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, require_roles
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    NewPassword,
)
from app.services import users as user_service

router = APIRouter()


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: NewPassword = Field(..., min_length=6, max_length=128)
    role: str = Field("analyst", pattern="^(analyst|admin)$")


def _public(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


def _tokens(user: dict) -> dict:
    return {
        "access_token": create_access_token(user["username"], user["role"]),
        "refresh_token": create_refresh_token(user["username"], user["role"]),
        "token_type": "bearer",
        "user": _public(user),
    }


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = user_service.authenticate(form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _tokens(user)


@router.post("/refresh")
def refresh(payload: RefreshRequest):
    data = decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = user_service.get_user(data.get("sub", ""))
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or unknown user")
    return {
        "access_token": create_access_token(user["username"], user["role"]),
        "token_type": "bearer",
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"user": _public(user)}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, _: dict = Depends(require_roles("admin"))):
    try:
        return {"user": user_service.create_user(payload.username, payload.password, payload.role)}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/admin/users")
def admin_users(_: dict = Depends(require_roles("admin"))):
    return {"users": user_service.list_users()}
