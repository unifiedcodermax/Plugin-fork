"""JWT mint + verify.

Single algorithm (HS256), TTL from Settings, subject = user id.
Anything more elaborate (RS256, refresh tokens, kid headers)
arrives when there's a real reason — premature crypto complexity
is its own attack surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from planara_engine.core.errors import AuthenticationFailed
from planara_engine.core.settings import Settings, get_settings


@dataclass(frozen=True)
class TokenClaims:
    """Subset of JWT claims this app cares about.

    sub:   user id (string at the JWT layer, parsed back to int)
    exp:   absolute expiry (datetime, UTC)
    iat:   issued-at (datetime, UTC)
    """

    user_id: int
    issued_at: datetime
    expires_at: datetime


def mint_token(user_id: int, *, settings: Settings | None = None) -> str:
    """Mint a JWT for ``user_id`` with TTL from settings."""

    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_ttl_minutes)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def verify_token(token: str, *, settings: Settings | None = None) -> TokenClaims:
    """Decode + validate a JWT. Raises AuthenticationFailed on any problem.

    Catches every PyJWT error path and collapses them into one
    domain exception — callers (route handlers) should not have to
    care whether the signature was wrong or the token had expired,
    they just know "this caller is not authenticated".
    """

    settings = settings or get_settings()
    try:
        decoded = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationFailed("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationFailed("invalid token") from exc

    try:
        user_id = int(decoded["sub"])
        issued_at = datetime.fromtimestamp(decoded["iat"], tz=timezone.utc)
        expires_at = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationFailed("malformed token claims") from exc

    return TokenClaims(user_id=user_id, issued_at=issued_at, expires_at=expires_at)
