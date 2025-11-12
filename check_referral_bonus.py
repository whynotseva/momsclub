#!/usr/bin/env python3
import asyncio
import sys


async def main():
    if len(sys.argv) < 3:
        print("Usage: check_referral_bonus.py <referrer_username> <referee_username>")
        return

    referrer_username = sys.argv[1].lstrip('@').strip()
    referee_username = sys.argv[2].lstrip('@').strip()

    from sqlalchemy import select
    from sqlalchemy import func
    from database.config import AsyncSessionLocal
    from database.models import User, PaymentLog, Subscription

    async with AsyncSessionLocal() as s:
        # Find users by username (case-insensitive just in case)
        ref_q = await s.execute(select(User).where(func.lower(User.username) == referrer_username.lower()))
        referrer = ref_q.scalar_one_or_none()
        refd_q = await s.execute(select(User).where(func.lower(User.username) == referee_username.lower()))
        referee = refd_q.scalar_one_or_none()

        print("REFERRER:", {
            'found': bool(referrer),
            'id': getattr(referrer, 'id', None),
            'telegram_id': getattr(referrer, 'telegram_id', None),
            'username': getattr(referrer, 'username', None),
        })
        print("REFEREE:", {
            'found': bool(referee),
            'id': getattr(referee, 'id', None),
            'telegram_id': getattr(referee, 'telegram_id', None),
            'username': getattr(referee, 'username', None),
            'referrer_id': getattr(referee, 'referrer_id', None),
        })

        # Fallback: if referrer not found but referee has referrer_id, fetch by ID
        if referee and not referrer and referee.referrer_id:
            byid_q = await s.execute(select(User).where(User.id == referee.referrer_id))
            referrer = byid_q.scalar_one_or_none()
            print("REFERRER_FALLBACK_BY_ID:", {
                'found': bool(referrer),
                'id': getattr(referrer, 'id', None),
                'username': getattr(referrer, 'username', None),
            })

        if not referrer or not referee:
            return

        # Check relationship
        print("RELATIONSHIP:", {
            'referee.referrer_id == referrer.id': referee.referrer_id == referrer.id
        })

        # Check PaymentLog for referral bonus paid to referrer
        reason_marker = f"referral_bonus_for_{referee.id}"
        plogs_q = await s.execute(
            select(PaymentLog).where(
                PaymentLog.user_id == referrer.id,
                PaymentLog.details.like(f"%{reason_marker}%")
            ).order_by(PaymentLog.id.desc())
        )
        plogs = plogs_q.scalars().all()
        print("REFERRER_PAYMENT_LOGS_COUNT:", len(plogs))
        for log in plogs[:3]:
            print("REFERRER_PAYMENT_LOG:", {
                'id': log.id,
                'details': log.details,
                'status': log.status,
            })

        # Show active subscription end_date for referrer
        subs_q = await s.execute(
            select(Subscription).where(
                Subscription.user_id == referrer.id,
                Subscription.is_active == 1
            ).order_by(Subscription.end_date.desc())
        )
        subs = subs_q.scalars().all()
        print("REFERRER_ACTIVE_SUBS_COUNT:", len(subs))
        if subs:
            print("REFERRER_ACTIVE_SUB_END:", subs[0].end_date)

        # Check if any bonus was given to referee automatically (expected NONE in current logic)
        refd_bonus_q = await s.execute(
            select(PaymentLog).where(
                PaymentLog.user_id == referee.id,
                PaymentLog.details.like("%referral_bonus%")
            ).order_by(PaymentLog.id.desc())
        )
        refd_bonuses = refd_bonus_q.scalars().all()
        print("REFEREE_PAYMENT_LOGS_REFERRAL_COUNT:", len(refd_bonuses))
        if refd_bonuses:
            print("REFEREE_REFERRAL_LOG_SAMPLE:", {
                'id': refd_bonuses[0].id,
                'details': refd_bonuses[0].details,
            })


if __name__ == "__main__":
    asyncio.run(main())