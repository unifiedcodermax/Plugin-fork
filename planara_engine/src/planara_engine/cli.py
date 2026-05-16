"""Command-line entry point for the engine.

Subcommands:
  serve         (default) — boot the FastAPI app under uvicorn.
  create-user   prompt for username + password, insert into the
                local DB.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence

import uvicorn
from sqlmodel import Session

from planara_engine import __version__
from planara_engine.auth.service import register_user
from planara_engine.core.errors import PlanaraError
from planara_engine.core.logging import configure_logging, get_logger
from planara_engine.core.settings import get_settings
from planara_engine.persistence.database import get_engine, init_db


def _serve(_args: argparse.Namespace) -> int:
    settings = get_settings()
    uvicorn.run(
        "planara_engine.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env.value == "dev",
        log_config=None,
        access_log=False,
    )
    return 0


def _create_user(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("planara.cli")

    username = args.username if args.username is not None else input("Username: ").strip()
    if not username:
        print("error: username is required", file=sys.stderr)
        return 2

    if args.password is not None:
        password = args.password
    else:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm:  ")
        if password != confirm:
            print("error: passwords do not match", file=sys.stderr)
            return 2

    init_db()
    try:
        with Session(get_engine()) as session:
            user = register_user(session, username=username, password=password)
            session.commit()
            log.info("user_created", username=user.username, user_id=user.id)
            print(f"Created user {user.username!r} (id={user.id}).")
            return 0
    except PlanaraError as exc:
        # ValidationFailed bubbles up here on duplicate username,
        # empty/too-long password, etc. Print the message but not
        # the full traceback — this is a CLI-facing error, not a
        # bug.
        print(f"error: {exc.message}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="planara-engine",
        description="Planara compliance engine.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    # No subcommand => serve (preserves the "just run it" UX).

    p_serve = sub.add_parser("serve", help="Run the HTTP service (default).")
    p_serve.set_defaults(func=_serve)

    p_create = sub.add_parser("create-user", help="Create a local user account.")
    p_create.add_argument("--username", help="Username. Prompted if omitted.")
    p_create.add_argument(
        "--password",
        help="Password (not recommended on the command line — prompted with confirmation if omitted).",
    )
    p_create.set_defaults(func=_create_user)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        # No subcommand and no func; default to serve.
        return _serve(args)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
