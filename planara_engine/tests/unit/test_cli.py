"""CLI argument parsing + create-user flow (non-prompt path)."""

from __future__ import annotations

from pathlib import Path

import pytest

from planara_engine.cli import build_parser, main
from planara_engine.persistence.database import get_engine
from planara_engine.persistence.repository import get_user_by_username
from sqlmodel import Session


def test_parser_recognizes_subcommands() -> None:
    parser = build_parser()
    args = parser.parse_args(["create-user", "--username", "alice", "--password", "hunter2pass"])
    assert args.command == "create-user"
    assert args.username == "alice"
    assert args.password == "hunter2pass"


def test_parser_serve_is_default(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.command is None
    # No assertion error => parse succeeded
    _ = capsys  # silence unused


def test_create_user_non_interactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("PLANARA_DB_URL", db_url)
    monkeypatch.setenv("PLANARA_JWT_SECRET", "cli-test-secret-of-sufficient-length")
    get_engine.cache_clear()

    rc = main(["create-user", "--username", "alice", "--password", "hunter2pass"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Created user 'alice'" in out

    with Session(get_engine()) as s:
        user = get_user_by_username(s, "alice")
        assert user is not None
        assert user.is_active is True

    get_engine().dispose()
    get_engine.cache_clear()


def test_create_user_rejects_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("PLANARA_DB_URL", db_url)
    monkeypatch.setenv("PLANARA_JWT_SECRET", "cli-test-secret-of-sufficient-length")
    get_engine.cache_clear()

    assert main(["create-user", "--username", "bob", "--password", "hunter2pass"]) == 0
    rc = main(["create-user", "--username", "bob", "--password", "other-pass-ok"])
    assert rc == 1

    err = capsys.readouterr().err
    assert "already exists" in err

    get_engine().dispose()
    get_engine.cache_clear()


def test_create_user_rejects_short_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("PLANARA_DB_URL", db_url)
    monkeypatch.setenv("PLANARA_JWT_SECRET", "cli-test-secret-of-sufficient-length")
    get_engine.cache_clear()

    # Empty password — ValidationFailed from hash_password
    rc = main(["create-user", "--username", "carol", "--password", ""])
    assert rc == 1
    err = capsys.readouterr().err
    assert "password must not be empty" in err

    get_engine().dispose()
    get_engine.cache_clear()
