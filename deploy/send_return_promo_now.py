#!/usr/bin/env python3
"""
Скрипт для ручной отправки уведомлений с промокодами возврата
пользователям, у которых подписка истекла в течение последних 7 дней
"""
import asyncio
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.config import AsyncSessionLocal
from database.crud import (
    get_users_for_7day_return_promo,
    create_personal_return_promo_code,
    create_subscription_notification,
    mark_user_as_blocked
)
from utils.constants import RETURN_PROMO_CONFIG
from loyalty.levels import calc_tenure_days, level_for_days
from aiogram import Bot
from config import BOT_TOKEN
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_return_promo_to_user(user, subscription, bot):
    """Отправляет уведомление с промокодом конкретному пользователю"""
    try:
        async with AsyncSessionLocal() as session:
            # Определяем уровень лояльности
            tenure_days = await calc_tenure_days(session, user)
            loyalty_level = user.current_loyalty_level or level_for_days(tenure_days)
            
            # Получаем конфигурацию для уровня
            config = RETURN_PROMO_CONFIG.get(loyalty_level, RETURN_PROMO_CONFIG['none'])
            
            # Создаем персональный промокод
            promo_code = await create_personal_return_promo_code(
                session,
                user.id,
                loyalty_level,
                days_valid=7
            )
            
            # Формируем персонализированное сообщение
            user_name = user.first_name or "Красотка"
            expiry_date_str = promo_code.expiry_date.strftime("%d.%m.%Y") if promo_code.expiry_date else "не ограничен"
            
            message_text = (
                f"{config['message_emoji']} {user_name}, мы скучаем по тебе!\n\n"
                f"Твоя подписка в Mom's Club закончилась неделю назад, "
                f"и без тебя в чате не так тепло 😔\n\n"
                f"Как наш {config['level_name']}, мы подготовили для тебя "
                f"особый подарок для возврата:\n\n"
                f"🎁 Скидка <b>{promo_code.value}%</b> на подписку\n"
                f"⏰ Действует до <b>{expiry_date_str}</b>\n\n"
                f"{config['message_text']}\n\n"
                f"Вернись, красотка, твое место — с нами 💖\n\n"
                f"Твоя Полина и команда Mom's Club 🩷"
            )
            
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="🎁 Использовать промокод",
                        callback_data=f"use_return_promo:{promo_code.id}"
                    )],
                    [InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
                ]
            )
            
            await bot.send_message(
                user.telegram_id,
                message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
            # Отмечаем, что уведомление отправлено (проверяем, не было ли уже отправлено)
            from database.crud import get_subscription_notification
            existing_notification = await get_subscription_notification(session, subscription.id, 'expired_reminder_7days')
            if not existing_notification:
                await create_subscription_notification(session, subscription.id, 'expired_reminder_7days')
            logger.info(f"✅ Уведомление с промокодом возврата отправлено пользователю {user.telegram_id} (@{user.username or 'нет username'}) (промокод: {promo_code.code})")
            return True
            
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления с промокодом пользователю {user.telegram_id}: {e}")
        if 'bot was blocked by the user' in str(e) or 'USER_IS_BLOCKED' in str(e):
            async with AsyncSessionLocal() as session:
                await mark_user_as_blocked(session, user.id)
            logger.info(f"Пользователь {user.telegram_id} отмечен как заблокировавший бота")
        return False


async def send_to_specific_user(username_or_id: str):
    """Отправляет тестовое уведомление конкретному пользователю по username или telegram_id"""
    bot = Bot(token=BOT_TOKEN)
    
    try:
        async with AsyncSessionLocal() as session:
            from database.crud import get_user_by_username, get_user_by_telegram_id
            from database.models import Subscription
            from sqlalchemy import select, desc, text
            
            # Определяем, это username или telegram_id
            user = None
            if username_or_id.isdigit():
                # Это telegram_id
                user = await get_user_by_telegram_id(session, int(username_or_id))
            else:
                # Это username
                user = await get_user_by_username(session, username_or_id.replace('@', ''))
            
            if not user:
                identifier = f"@{username_or_id}" if not username_or_id.isdigit() else f"ID: {username_or_id}"
                print(f"❌ Пользователь {identifier} не найден в базе данных")
                return
            
            # Получаем последнюю истекшую подписку через прямой SQL
            query = text("""
                SELECT id, user_id, end_date, price, is_active 
                FROM subscriptions 
                WHERE user_id = :user_id AND is_active = 0 
                ORDER BY end_date DESC 
                LIMIT 1
            """)
            result = await session.execute(query, {"user_id": user.id})
            row = result.fetchone()
            
            if not row:
                identifier = f"@{username_or_id}" if not username_or_id.isdigit() else f"ID: {username_or_id}"
                print(f"⚠️  У пользователя {identifier} нет истекших подписок. Создаем тестовую подписку...")
                from datetime import datetime, timedelta
                # Создаем тестовую подписку через SQL (истекла сегодня)
                insert_query = text("""
                    INSERT INTO subscriptions (user_id, end_date, price, is_active, start_date, created_at, updated_at)
                    VALUES (:user_id, :end_date, :price, 0, :start_date, :created_at, :updated_at)
                """)
                test_end_date = datetime.now()  # Подписка истекла сегодня
                await session.execute(insert_query, {
                    "user_id": user.id,
                    "end_date": test_end_date,
                    "price": 990,
                    "start_date": test_end_date - timedelta(days=30),
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                })
                await session.commit()
                
                # Получаем созданную подписку
                result = await session.execute(query, {"user_id": user.id})
                row = result.fetchone()
            
            # Создаем объект подписки
            subscription = Subscription()
            subscription.id = row[0]
            subscription.user_id = row[1]
            subscription.end_date = row[2]
            subscription.price = row[3]
            subscription.is_active = row[4]
            
            if not subscription:
                print(f"⚠️  У пользователя @{username} нет истекших подписок. Создаем тестовую подписку...")
                from datetime import datetime, timedelta
                subscription = Subscription(
                    user_id=user.id,
                    end_date=datetime.now() - timedelta(days=7),
                    price=990,
                    is_active=False
                )
                session.add(subscription)
                await session.commit()
                await session.refresh(subscription)
            
            identifier = f"@{username_or_id}" if not username_or_id.isdigit() else f"ID: {username_or_id}"
            print(f"📤 Отправка уведомления пользователю {identifier} (Telegram ID: {user.telegram_id})...")
            success = await send_return_promo_to_user(user, subscription, bot)
            
            if success:
                print(f"✅ Уведомление успешно отправлено пользователю {identifier}")
            else:
                print(f"❌ Не удалось отправить уведомление пользователю {identifier}")
                
    except Exception as e:
        logger.error(f"Ошибка при отправке тестового уведомления: {e}", exc_info=True)
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()


async def send_to_all_eligible_users():
    """Отправляет уведомления всем подходящим пользователям"""
    bot = Bot(token=BOT_TOKEN)
    
    try:
        async with AsyncSessionLocal() as session:
            # Получаем пользователей с истекшими подписками за последние 7 дней
            # Модифицируем запрос, чтобы получить всех, у кого подписка истекла от 0 до 7 дней назад
            from database.models import User, Subscription
            from sqlalchemy import select, func, and_
            from datetime import datetime, timedelta
            
            now = datetime.now()
            days_ago_7 = now - timedelta(days=7)
            days_ago_0 = now - timedelta(days=0)
            
            # Получаем последние истекшие подписки для каждого пользователя
            subquery = (
                select(
                    Subscription.user_id,
                    func.max(Subscription.end_date).label('max_end_date')
                )
                .group_by(Subscription.user_id)
                .having(
                    and_(
                        func.max(Subscription.end_date) <= datetime(2099, 1, 1),
                        func.max(Subscription.end_date) >= days_ago_7,
                        func.max(Subscription.end_date) <= days_ago_0
                    )
                )
            ).subquery()
            
            # Получаем полные данные подписок
            query = (
                select(User, Subscription)
                .join(Subscription, User.id == Subscription.user_id)
                .join(
                    subquery,
                    and_(
                        Subscription.user_id == subquery.c.user_id,
                        Subscription.end_date == subquery.c.max_end_date
                    )
                )
                .where(
                    and_(
                        Subscription.is_active == False,
                        User.is_blocked == False,
                        User.is_recurring_active == False
                    )
                )
            )
            
            result = await session.execute(query)
            users_with_subs = result.all()
            
            # Фильтруем тех, кому еще не отправлялось уведомление
            eligible_users = []
            for user, subscription in users_with_subs:
                notification = await create_subscription_notification(session, subscription.id, 'expired_reminder_7days')
                if not notification:
                    eligible_users.append((user, subscription))
            
            print(f"📊 Найдено {len(eligible_users)} пользователей для отправки уведомлений")
            
            success_count = 0
            fail_count = 0
            
            for user, subscription in eligible_users:
                print(f"📤 Отправка пользователю @{user.username or 'нет username'} (ID: {user.telegram_id})...")
                success = await send_return_promo_to_user(user, subscription, bot)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                await asyncio.sleep(1)  # Небольшая задержка между отправками
            
            print(f"\n✅ Успешно отправлено: {success_count}")
            print(f"❌ Ошибок: {fail_count}")
            
    except Exception as e:
        logger.error(f"Ошибка при массовой отправке: {e}", exc_info=True)
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()


async def main():
    if len(sys.argv) > 1:
        username = sys.argv[1].replace('@', '')
        print(f"🎯 Отправка тестового уведомления пользователю @{username}")
        await send_to_specific_user(username)
    else:
        print("📤 Отправка уведомлений всем подходящим пользователям...")
        await send_to_all_eligible_users()


if __name__ == "__main__":
    asyncio.run(main())

