#!/usr/bin/env python3
import asyncio
import os
import sys


async def main():
    if len(sys.argv) < 3:
        print("Usage: send_referral_push_pair.py <referrer_username> <referee_username> [bonus_days]")
        return

    referrer_username = sys.argv[1].lstrip('@').strip()
    referee_username = sys.argv[2].lstrip('@').strip()
    bonus_days = int(sys.argv[3]) if len(sys.argv) > 3 else 7

    from sqlalchemy import select, func
    from database.config import AsyncSessionLocal
    from database.models import User, Subscription
    from aiogram import Bot
    from handlers.admin_handlers import ADMIN_IDS

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        print("BOT_TOKEN not set")
        return
    bot = Bot(token=bot_token)

    async with AsyncSessionLocal() as s:
        # Fetch users
        ref_q = await s.execute(select(User).where(func.lower(User.username) == referrer_username.lower()))
        referrer = ref_q.scalar_one_or_none()
        refd_q = await s.execute(select(User).where(func.lower(User.username) == referee_username.lower()))
        referee = refd_q.scalar_one_or_none()

        if not referrer or not referee:
            print("USERS_NOT_FOUND", bool(referrer), bool(referee))
            return

        # Active subs end dates
        ref_sub_q = await s.execute(
            select(Subscription).where(Subscription.user_id == referrer.id, Subscription.is_active == 1).order_by(Subscription.end_date.desc())
        )
        ref_sub = ref_sub_q.scalars().first()
        ref_end_str = ref_sub.end_date.strftime('%d.%m.%Y') if ref_sub else 'N/A'

        refd_sub_q = await s.execute(
            select(Subscription).where(Subscription.user_id == referee.id, Subscription.is_active == 1).order_by(Subscription.end_date.desc())
        )
        refd_sub = refd_sub_q.scalars().first()
        refd_end_str = refd_sub.end_date.strftime('%d.%m.%Y') if refd_sub else 'N/A'

        # Compose admin message
        user_info = f"{referee.first_name} {referee.last_name or ''} (@{referee.username})" if referee.username else f"{referee.first_name} {referee.last_name or ''} (ID: {referee.telegram_id})"
        ref_display = f"@{referrer.username}" if referrer.username else f"ID: {referrer.telegram_id}"
        admin_text = (
            "💰 <b>Новый платеж!</b>\n\n"
            "✨ <b>Новый пользователь оформил подписку</b>\n"
            "🤝 Оплата по реферальной программе\n"
            f"👤 Пользователь: {user_info}\n"
            f"🤝 Реферал: пригласил {ref_display}\n"
            f"🎁 Бонусы начислены: рефереру +{bonus_days} дней, рефералу +{bonus_days} дней\n"
            f"📆 Сроки: реферер до {ref_end_str}, реферал до {refd_end_str}"
        )

        # Send to admins
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, admin_text, parse_mode="HTML")
            except Exception as e:
                print("ADMIN_SEND_ERR", admin_id, e)

        # Send to referrer (informational)
        try:
            await bot.send_message(
                referrer.telegram_id,
                (
                    f"🎁 <b>Бонус за приглашение подтверждён</b>\n\n"
                    f"Пользователь {referee.first_name or ''} (@{referee.username or 'без никнейма'}) оплатил подписку.\n"
                    f"Ваша подписка продлена на {bonus_days} дней. Текущий срок: до {ref_end_str}"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print("REFERRER_SEND_ERR", e)

        # Send to referee (informational)
        try:
            await bot.send_message(
                referee.telegram_id,
                (
                    f"🎁 <b>Реферальный бонус начислен</b>\n\n"
                    f"Вы приглашены {ref_display}. Ваша подписка продлена на {bonus_days} дней. Текущий срок: до {refd_end_str}"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print("REFEREE_SEND_ERR", e)

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())