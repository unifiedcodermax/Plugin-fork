"""Password hashing: round-trips, edge cases, rejection rules."""

from __future__ import annotations

import pytest

from planara_engine.auth.passwords import (
    MAX_PASSWORD_BYTES,
    hash_password,
    verify_password,
)
from planara_engine.core.errors import ValidationFailed


def test_hash_then_verify_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("right")
    assert verify_password("wrong", h) is False


def test_hashes_are_salted_per_call() -> None:
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # bcrypt salts each hash uniquely
    assert verify_password("same", h1) is True
    assert verify_password("same", h2) is True


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        hash_password("")


def test_password_at_max_bytes_is_accepted() -> None:
    pw = "a" * MAX_PASSWORD_BYTES
    h = hash_password(pw)
    assert verify_password(pw, h) is True


def test_password_over_max_bytes_is_rejected() -> None:
    with pytest.raises(ValidationFailed):
        hash_password("a" * (MAX_PASSWORD_BYTES + 1))


def test_verify_with_malformed_hash_returns_false() -> None:
    # Don't raise — we want callers to treat "garbage hash" and
    # "wrong password" identically and not leak which one failed.
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_verify_with_empty_inputs_returns_false() -> None:
    assert verify_password("", "$2b$12$" + "a" * 53) is False
    assert verify_password("x", "") is False
