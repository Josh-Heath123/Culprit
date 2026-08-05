"""Create the first admin, or any other user, on the host (Phase 16).

Deliberately runs here, not as a public bootstrap HTTP endpoint — an
unauthenticated "create the first admin" endpoint would be a window in
which anyone who finds it can create an admin account. This script is
the only way to create a user before at least one admin already exists
to use POST /users instead.

Run via `just create-user <username> [--role admin|member]` or directly:
`cd api && uv run python -m scripts.create_user <username> [--role admin|member]`.
Prompts for the password (and a confirmation) rather than taking it as
an argument — a password on the command line ends up in shell history
and process listings.
"""

import argparse
import asyncio
import getpass
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Same convention as app/main.py / api/scripts/apply_services.py -- this
# script imports app.auth.* directly (not app.main), so nothing else
# loads api/.env for it first.
load_dotenv()

from app.auth.config import AUTH_SERVICE_DATABASE_URL  # noqa: E402
from app.auth.repository import create_user, get_user_by_username  # noqa: E402
from app.auth.security import WeakPassword, hash_password, validate_password  # noqa: E402


async def run(username: str, role: str) -> int:
    engine = create_async_engine(AUTH_SERVICE_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            if await get_user_by_username(session, username) is not None:
                print(f"error: username {username!r} already exists", file=sys.stderr)
                return 1

            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("error: passwords don't match", file=sys.stderr)
                return 1

            try:
                validate_password(password, username)
            except WeakPassword as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

            user = await create_user(
                session, username=username, password_hash=hash_password(password), role=role
            )
            print(f"created {user.role} user {user.username!r}")
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--role", choices=["admin", "member"], default="admin")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.username, args.role)))


if __name__ == "__main__":
    main()
