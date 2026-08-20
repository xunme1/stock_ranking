from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import AUTH_COOKIE_SECURE, AUTH_SESSION_HOURS
from app.services.auth_service import (
    SESSION_COOKIE_NAME,
    create_session,
    is_auth_enabled,
    valid_password,
    validate_session,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


def session_payload(request: Request) -> dict[str, object]:
    enabled = is_auth_enabled()
    authenticated = validate_session(request.cookies.get(SESSION_COOKIE_NAME)) if enabled else True
    return {"enabled": enabled, "authenticated": authenticated}


@router.get("/session")
def get_session(request: Request) -> dict[str, object]:
    return session_payload(request)


@router.post("/login")
def login(credentials: LoginRequest, response: Response) -> dict[str, object]:
    if not is_auth_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login is not configured")
    if not valid_password(credentials.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="密码不正确")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session(),
        max_age=AUTH_SESSION_HOURS * 3600,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {"enabled": True, "authenticated": True}


@router.post("/logout")
def logout(response: Response) -> dict[str, object]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"ok": True}
