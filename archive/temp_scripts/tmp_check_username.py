#!/usr/bin/env python3
import asyncio
import sys
from sqlalchemy import select, func
from database.config import AsyncSessionLocal
from database.models import User


async def main():
    if len(sys.argv) < 2:
        print("Usage: tmp_check_username.py <username_or_@username>")
        return
    raw = sys.argv[1].strip()
    username = raw[1:] if raw.startswith('@') else raw

    async with AsyncSessionLocal() as s:
        q = await s.execute(select(User).where(func.lower(User.username) == username.lower()))
        u = q.scalar_one_or_none()
        if not u:
            print("USER_NOT_FOUND", username)
            return
        print({
            'id': u.id,
            'telegram_id': u.telegram_id,
            'username': u.username,
            'is_blocked': u.is_blocked,
            'is_active': u.is_active,
            'created_at': str(u.created_at),
            'updated_at': str(u.updated_at),
        })


if __name__ == "__main__":
    asyncio.run(main())