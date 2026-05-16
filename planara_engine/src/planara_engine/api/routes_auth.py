"""Auth endpoints: POST /auth/login, GET /auth/me."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from planara_engine.auth.deps import CurrentUser, SessionDep
from planara_engine.auth.service import authenticate, issue_token
from planara_engine.core.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class MeResponse(BaseModel):
    """Subset of the User row safe to send back to the plugin.

    Deliberately omits ``password_hash``. SQLModel would happily
    serialize the whole row if we returned the ORM object; this
    Pydantic envelope is the boundary that keeps internal columns
    from leaking.
    """

    id: int
    username: str
    is_active: bool
    created_at: datetime


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange username + password for a JWT",
)
def login(req: LoginRequest, session: SessionDep) -> TokenResponse:
    user = authenticate(session, username=req.username, password=req.password)
    token = issue_token(user)
    return TokenResponse(
        token=token,
        expires_in_minutes=get_settings().jwt_ttl_minutes,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the currently authenticated user",
)
def me(user: CurrentUser) -> MeResponse:
    # Caller is authenticated by virtue of CurrentUser resolving.
    return MeResponse(
        id=user.id,  # type: ignore[arg-type]  # always set when loaded from DB
        username=user.username,
        is_active=user.is_active,
        created_at=user.created_at,
    )
