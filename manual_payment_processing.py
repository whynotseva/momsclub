"""
Скрипт ручной обработки платежа #36714276
Дата: 10.10.2025 00:20:15
Телефон: +79102991103
Email: alyayv@yandex.ru
Сумма: 990 руб (30 дней)
"""
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    extend_subscription,
    create_payment_log,
    get_user_by_id,
    send_payment_notification_to_admins,
    extend_subscription_days,
    get_referrer_info,
    is_first_payment_by_user
)
from database.models import User
from sqlalchemy import select
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)

# Данные платежа
PAYMENT_DATA = {
    'order_id': '36714276',
    'transaction_id': 'g4287b14-dff6-4acb-ae25-8f4ce81dc368',
    'phone': '+79102991103',
    'email': 'alyayv@yandex.ru',
    'amount': 990,
    'days': 30,
    'payment_date': '2025-10-10 00:20:15'
}

CLUB_CHANNEL_URL = "https://t.me/+Z77jamwsi1hiNTZi"

async def process_manual_payment():
    """Обрабатывает платеж вручную"""
    logger.info('='*60)
    logger.info(f'РУЧНАЯ ОБРАБОТКА ПЛАТЕЖА #{PAYMENT_DATA["order_id"]}')
    logger.info('='*60)
    
    async with AsyncSessionLocal() as session:
        # Ищем пользователя по телефону
        logger.info(f'Ищем пользователя по телефону: {PAYMENT_DATA["phone"]}')
        
        query = select(User).where(User.phone == PAYMENT_DATA['phone'])
        result = await session.execute(query)
        user = result.scalar_one_or_none()
        
        if not user:
            logger.error(f'❌ Пользователь с телефоном {PAYMENT_DATA["phone"]} НЕ НАЙДЕН!')
            logger.info('Попробуем найти по email...')
            query = select(User).where(User.email == PAYMENT_DATA['email'])
            result = await session.execute(query)
            user = result.scalar_one_or_none()
        
        if not user:
            logger.error(f'❌ Пользователь НЕ НАЙДЕН ни по телефону, ни по email!')
            logger.info('\nСписок последних пользователей:')
            query = select(User).order_by(User.created_at.desc()).limit(10)
            result = await session.execute(query)
            users = result.scalars().all()
            for u in users:
                logger.info(f'  - {u.telegram_id} | {u.phone} | {u.email} | {u.first_name}')
            return
        
        logger.info(f'✅ Найден пользователь: ID={user.id}, TG_ID={user.telegram_id}, Имя={user.first_name}')
        logger.info(f'   Username: @{user.username if user.username else "нет"}')
        
        # Создаем подписку
        logger.info(f'\nСоздаем подписку на {PAYMENT_DATA["days"]} дней...')
        
        subscription = await extend_subscription(
            session,
            user_id=user.id,
            days=PAYMENT_DATA['days'],
            price=PAYMENT_DATA['amount'],
            payment_id=PAYMENT_DATA['transaction_id'],
            renewal_price=PAYMENT_DATA['amount'],
            renewal_duration_days=PAYMENT_DATA['days'],
            subscription_id=f"manual_{PAYMENT_DATA['order_id']}"
        )
        
        logger.info(f'✅ Подписка создана/продлена: ID={subscription.id}')
        logger.info(f'   Окончание: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
        
        # Записываем платеж в БД
        logger.info('\nЗаписываем платеж в БД...')
        
        payment_log = await create_payment_log(
            session,
            user_id=user.id,
            amount=PAYMENT_DATA['amount'],
            status='success',
            subscription_id=subscription.id,
            payment_method='prodamus',
            transaction_id=PAYMENT_DATA['transaction_id'],
            details=f"Ручная обработка платежа #{PAYMENT_DATA['order_id']} от {PAYMENT_DATA['payment_date']}",
            payment_label=f"manual_{PAYMENT_DATA['order_id']}",
            days=PAYMENT_DATA['days']
        )
        
        # Обновляем is_confirmed
        payment_log.is_confirmed = True
        payment_log.prodamus_order_id = PAYMENT_DATA['order_id']
        await session.commit()
        
        logger.info(f'✅ Платеж записан: PaymentLog ID={payment_log.id}')
        
        # Проверяем, первый ли это платеж
        is_first = await is_first_payment_by_user(session, user.id, payment_log.id)
        logger.info(f'   Первый платеж: {"Да" if is_first else "Нет"}')
        
        # Если первый платеж - проверяем реферера
        if is_first:
            referrer = await get_referrer_info(session, user.id, bot)
            if referrer:
                logger.info(f'\n🎁 Найден реферер: {referrer.telegram_id} (@{referrer.username})')
                success = await extend_subscription_days(session, referrer.id, 7, "referral_bonus")
                if success:
                    logger.info(f'✅ Реферу начислено +7 дней')
                    try:
                        await bot.send_message(
                            referrer.telegram_id,
                            f"🎁 Вам начислен бонус за приглашение!\n\n"
                            f"Пользователь {user.first_name} оплатил подписку, и ваша подписка автоматически продлена на 7 дней.\n\n"
                            f"Спасибо за участие в программе приглашений Mom's Club! 💖"
                        )
                        logger.info(f'✅ Уведомление отправлено реферу')
                    except Exception as e:
                        logger.error(f'Ошибка отправки уведомления реферу: {e}')
        
        # Отправляем уведомление пользователю
        logger.info(f'\nОтправляем уведомление пользователю...')
        
        try:
            success_message = (
                f"✨ <b>Подписка успешно оформлена!</b> ✨\n\n"
                f"Спасибо за оплату! Ваша подписка на Mom's Club активирована.\n\n"
                f"📅 <b>Срок действия:</b> до {subscription.end_date.strftime('%d.%m.%Y')}\n"
                f"💰 <b>Сумма:</b> {PAYMENT_DATA['amount']} ₽\n\n"
                f"Добро пожаловать в наш клуб! 💖"
            )
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🩷 Перейти в Mom's Club", url=CLUB_CHANNEL_URL)
                ]]
            )
            
            await bot.send_message(
                user.telegram_id,
                success_message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            logger.info(f'✅ Уведомление отправлено пользователю {user.telegram_id}')
        except Exception as e:
            logger.error(f'❌ Ошибка при отправке уведомления пользователю: {e}')
        
        # Отправляем уведомление админам
        logger.info('\nОтправляем уведомление админам...')
        try:
            await send_payment_notification_to_admins(bot, user, payment_log, subscription, PAYMENT_DATA['transaction_id'])
            logger.info('✅ Уведомление отправлено админам')
        except Exception as e:
            logger.error(f'Ошибка при отправке уведомления админам: {e}')
        
        logger.info('='*60)
        logger.info('✅ ПЛАТЕЖ УСПЕШНО ОБРАБОТАН ВРУЧНУЮ!')
        logger.info('='*60)

async def main():
    try:
        await process_manual_payment()
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())

