"""Create or upgrade a platform admin user.

Usage (inside the user-service container):

    docker compose exec user-service python -m app.scripts.create_admin \
        --username admin \
        --email admin@htqweb.local \
        --password 's3cret!' \
        --first-name Admin \
        --last-name Root

If a user with the given username OR email already exists, it is upgraded
to admin (status=ACTIVE, is_staff=True, is_superuser=True) and, if
`--password` is supplied, the password is replaced.

Env vars (picked up by `app.core.settings` like the running service):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMA
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import async_session_factory
from app.models.user import User, UserStatus
from app.services.auth_service import hash_password


async def _create_admin(
    username: str,
    email: str,
    password: str | None,
    first_name: str,
    last_name: str,
) -> int:
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(
                (User.email == email.lower()) | (User.username == username)
            )
        )
        user = result.scalar_one_or_none()

        if user is None:
            if not password:
                raise SystemExit("Password required for new users (--password)")
            user = User(
                username=username,
                email=email.lower(),
                password_hash=hash_password(password),
                first_name=first_name,
                last_name=last_name,
                display_name=(first_name + " " + last_name).strip() or username,
                status=UserStatus.ACTIVE,
                is_staff=True,
                is_superuser=True,
                date_joined=datetime.now(timezone.utc),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"[create_admin] Created admin user id={user.id} username={user.username}")
        else:
            user.status = UserStatus.ACTIVE
            user.is_staff = True
            user.is_superuser = True
            if password:
                user.password_hash = hash_password(password)
            await session.commit()
            print(
                f"[create_admin] Upgraded existing user id={user.id} username={user.username} "
                f"(password {'updated' if password else 'unchanged'})"
            )
        return user.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or upgrade a platform admin user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None, help="Omit to keep existing password when upgrading")
    parser.add_argument("--first-name", default="")
    parser.add_argument("--last-name", default="")
    args = parser.parse_args()

    try:
        asyncio.run(
            _create_admin(
                username=args.username,
                email=args.email,
                password=args.password,
                first_name=args.first_name,
                last_name=args.last_name,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[create_admin] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
