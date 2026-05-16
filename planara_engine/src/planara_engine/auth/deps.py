"""FastAPI dependencies for auth + DB session.

Routes declare ``user: User = Depends(get_current_user)`` and get
a verified User. Anything that doesn't is unauthenticated by
definition.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from planara_engine.auth.tokens import verify_token
from planara_engine.core.errors import AuthenticationFailed
from planara_engine.persistence.database import session_scope
from planara_engine.persistence.models import User
from planara_engine.persistence.repository import get_user_by_id

# auto_error=False lets us raise our domain exception instead of
# FastAPI's default 403 HTMLResponse on a missing header. The
# PlanaraError handler then turns it into the canonical envelope.
_bearer = HTTPBearer(auto_error=False)


def db_session() -> Iterator[Session]:
    """Request-scoped DB session. Wraps the generator in
    session_scope which commits on success and rolls back on
    exception."""

    yield from session_scope()


SessionDep = Annotated[Session, Depends(db_session)]
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def get_current_user(
    creds: BearerDep,
    session: SessionDep,
) -> User:
    """Verify the bearer JWT and load the corresponding User.

    Raises AuthenticationFailed when:
      * No Authorization header.
      * Header present but malformed / not Bearer.
      * Token signature or claims invalid.
      * User id in token does not match any active row.
    """

    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationFailed("missing or non-bearer Authorization header")

    claims = verify_token(creds.credentials)
    user = get_user_by_id(session, claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationFailed("user not found or disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
