#!/usr/bin/env python3
import asyncio
import sys


async def main():
    if len(sys.argv) < 2:
        print("Usage: grant_referral_self_bonus.py <referee_username>")
        return

    referee_username = sys.argv[1].lstrip('@').strip()

    from sqlalchemy import select
    from sqlalchemy import func
    from database.config import AsyncSessionLocal
    from database.models import User, PaymentLog
    from database.crud import extend_subscription_days
    from utils.constants import REFERRAL_BONUS_DAYS

    async with AsyncSessionLocal() as s:
        q = await s.execute(select(User).where(func.lower(User.username) == referee_username.lower()))
        user = q.scalar_one_or_none()
        if not user:
            print("REFEREE_NOT_FOUND")
            return
        if not user.referrer_id:
            print("NO_REFERRER_ID")
            return
        # Check if already granted
        reason = f"referral_bonus_self_from_{user.referrer_id}"
        exists_q = await s.execute(
            select(PaymentLog).where(
                PaymentLog.user_id == user.id,
                PaymentLog.payment_method == "bonus",
                PaymentLog.details.like(f"%{reason}%")
            )
        )
        if exists_q.scalars().first():
            print("ALREADY_GRANTED")
            return
        ok = await extend_subscription_days(s, user.id, REFERRAL_BONUS_DAYS, reason=reason)
        print("GRANTED", ok)


if __name__ == "__main__":
    asyncio.run(main())