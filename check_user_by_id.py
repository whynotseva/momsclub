#!/usr/bin/env python3
import asyncio
import sys


async def main():
    if len(sys.argv) < 2:
        print("Usage: check_user_by_id.py <user_id>")
        return

    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print("user_id must be integer")
        return

    from sqlalchemy import select
    from database.config import AsyncSessionLocal
    from database.models import User, Subscription

    async with AsyncSessionLocal() as s:
        uq = await s.execute(select(User).where(User.id == user_id))
        u = uq.scalar_one_or_none()
        print("USER:", {
            'found': bool(u),
            'id': getattr(u, 'id', None),
            'telegram_id': getattr(u, 'telegram_id', None),
            'username': getattr(u, 'username', None),
            'first_name': getattr(u, 'first_name', None),
            'last_name': getattr(u, 'last_name', None),
        })

        if not u:
            return

        sq = await s.execute(
            select(Subscription).where(Subscription.user_id == user_id, Subscription.is_active == 1)
        )
        subs = sq.scalars().all()
        print("ACTIVE_SUBS_COUNT:", len(subs))
        for sub in subs[:1]:
            print("ACTIVE_SUB_END:", sub.end_date)


if __name__ == "__main__":
    asyncio.run(main())