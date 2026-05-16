"""Password hashing.

bcrypt directly (no passlib). bcrypt has a 72-byte input limit
that is silently truncated; we reject longer passwords explicitly
so a user is never surprised by their 80-char passphrase being
effectively shorter than it looks.
"""

from __future__ import annotations

import bcrypt

from planara_engine.core.errors import ValidationFailed

# bcrypt truncates inputs longer than 72 bytes (after UTF-8 encoding).
# Rather than silently truncate, we reject — see module docstring.
MAX_PASSWORD_BYTES = 72

# Cost factor for bcrypt rounds. 12 = ~250ms on a modern laptop —
# slow enough to defeat offline guessing, fast enough for an
# interactive desktop login.
DEFAULT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Return a bcrypt hash string suitable for storing.

    Raises ValidationFailed on empty input or input longer than
    72 UTF-8 bytes (bcrypt's hard limit).
    """

    if not plain:
        raise ValidationFailed("password must not be empty")

    encoded = plain.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValidationFailed(
            f"password too long: {len(encoded)} bytes (bcrypt max is {MAX_PASSWORD_BYTES})"
        )

    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=DEFAULT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison via bcrypt.

    Returns False rather than raising on malformed inputs so the
    auth flow can treat "wrong password" and "garbage stored hash"
    identically (don't leak which one failed).
    """

    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False
