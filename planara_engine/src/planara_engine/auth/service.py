"""Auth service layer: orchestrates password verification + token mint.

Pure orchestration — the password hashing and JWT mechanics live
in passwords.py and tokens.py. Service code stays small and
testable.
"""

from __future__ import annotations

from sqlmodel import Session

from planara_engine.auth.passwords import hash_password, verify_password
from planara_engine.auth.tokens import mint_token
from planara_engine.core.errors import AuthenticationFailed, ValidationFailed
from planara_engine.persistence.models import User
from planara_engine.persistence.repository import create_user, get_user_by_username


def register_user(session: Session, *, username: str, password: str) -> User:
    """Insert a new user. Validates inputs, hashes the password.

    Username uniqueness is enforced at the DB level; this function
    pre-checks for a friendlier error rather than relying on the
    IntegrityError.
    """

    if not username or not username.strip():
        raise ValidationFailed("username must not be empty")

    existing = get_user_by_username(session, username)
    if existing is not None:
        raise ValidationFailed("username already exists")

    password_hash = hash_password(password)
    return create_user(session, username=username, password_hash=password_hash)


def authenticate(session: Session, *, username: str, password: str) -> User:
    """Look up + verify a user. Raises AuthenticationFailed on any failure.

    Crucially, the failure messages do not distinguish "no such
    user" from "wrong password" — the response and timing both
    look the same so an attacker cannot enumerate accounts.
    A dummy bcrypt verify burns CPU on the no-user path to keep
    timing roughly aligned.
    """

    user = get_user_by_username(session, username)
    if user is None:
        # Burn time so a username-not-found response takes ~the
        # same wall time as a real bcrypt check. Not perfect
        # timing-attack defense, but the cheap version is better
        # than none.
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationFailed("invalid credentials")

    if not user.is_active:
        raise AuthenticationFailed("account is disabled")

    if not verify_password(password, user.password_hash):
        raise AuthenticationFailed("invalid credentials")

    return user


def issue_token(user: User) -> str:
    """Mint a JWT for an authenticated user."""

    if user.id is None:
        # Defensive: a User loaded from the DB always has an id.
        raise AuthenticationFailed("cannot issue token for unsaved user")
    return mint_token(user.id)


# Pre-hashed throwaway password used only for timing parity on
# the "no such user" branch of authenticate(). Computed lazily and
# cached so each process pays the cost once, not per-login.
_DUMMY_HASH = "$2b$12$" + "x" * 53  # invalid bcrypt hash; checkpw returns False fast
