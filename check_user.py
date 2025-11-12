#!/usr/bin/env python3
import asyncio
import sys


async def main():
    # Expect username passed, may include leading '@'
    if len(sys.argv) < 2:
        print("Usage: check_user.py <username_or_@username>")
        return
    raw = sys.argv[1].strip()
    username = raw[1:] if raw.startswith('@') else raw

    try:
        from database.config import AsyncSessionLocal
        from database.crud import get_user_by_username
        from sqlalchemy import select, func
        from database.models import User

        async with AsyncSessionLocal() as s:
            # Exact match
            u_exact = await get_user_by_username(s, username)

            # Case-insensitive match
            result = await s.execute(
                select(User).where(func.lower(User.username) == username.lower())
            )
            u_ci = result.scalar_one_or_none()

            def info(u):
                if not u:
                    return None
                return {
                    'id': u.id,
                    'telegram_id': u.telegram_id,
                    'username': u.username,
                    'first_name': u.first_name,
                    'last_name': u.last_name,
                    'is_active': u.is_active,
                }

            print("INPUT:", raw)
            print("EXACT:", info(u_exact))
            print("CASE_INSENSITIVE:", info(u_ci))

    except Exception as e:
        print("ERROR:", e)


if __name__ == "__main__":
    asyncio.run(main())