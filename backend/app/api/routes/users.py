from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, require_roles
from app.services import users as user_service
from app.core.security import NewPassword

router = APIRouter()


class PasswordChange(BaseModel):
    current_password: str
    new_password: NewPassword = Field(..., min_length=6, max_length=128)


class RoleChange(BaseModel):
    role: str = Field(..., pattern="^(analyst|admin)$")


class CreateUser(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: NewPassword = Field(..., min_length=6, max_length=128)
    role: str = Field(..., pattern="^(analyst|admin)$")


class UserStatus(BaseModel):
    is_active: bool


@router.get("/me")
def read_me(user: dict = Depends(get_current_user)):
    return {"user": user}


@router.patch("/me")
def update_me(payload: PasswordChange, user: dict = Depends(get_current_user)):
    if not user_service.authenticate(user["username"], payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user_service.update_password(user["username"], payload.new_password)
    return {"status": "password_updated"}


@router.put("/me")
def replace_me(payload: PasswordChange, user: dict = Depends(get_current_user)):
    return update_me(payload, user)


@router.get("")
def list_all(_: dict = Depends(require_roles("admin"))):
    return {"users": user_service.list_users()}


@router.patch("/{username}/role")
def set_role(username: str, payload: RoleChange, _: dict = Depends(require_roles("admin"))):
    try:
        updated = user_service.update_role(username, payload.role)
    except user_service.LastAdminError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"user": updated}


@router.post("")
def create_new_user(payload: CreateUser, _: dict = Depends(require_roles("admin"))):
    try:
        user = user_service.create_user(payload.username, payload.password, payload.role)
        return {"user": user}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{username}/status")
def set_status(username: str, payload: UserStatus, _: dict = Depends(require_roles("admin"))):
    try:
        updated = user_service.update_status(username, payload.is_active)
    except user_service.LastAdminError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"user": updated}


@router.get("/roles/metadata")
def list_roles(_: dict = Depends(require_roles("admin"))):
    return {
        "roles": [
            {
                "name": "admin",
                "description": "Full administrative access including user, system, ETL, warehouse, ML administration and settings.",
                "permissions": {
                    "Dashboard": True,
                    "Analytics": True,
                    "ML Analysis": True,
                    "Reports": True,
                    "User Management": True,
                    "Role Management": True,
                    "System Health": True,
                    "ETL/Data": True,
                    "Warehouse": True,
                    "ML Admin": True,
                    "Settings": True,
                }
            },
            {
                "name": "analyst",
                "description": "Business intelligence, analytics, ML analysis and reporting access.",
                "permissions": {
                    "Dashboard": True,
                    "Analytics": True,
                    "ML Analysis": True,
                    "Reports": True,
                    "User Management": False,
                    "Role Management": False,
                    "System Health": False,
                    "ETL/Data": False,
                    "Warehouse": False,
                    "ML Admin": False,
                    "Settings": False,
                }
            }
        ]
    }
