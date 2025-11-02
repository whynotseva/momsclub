"""
Скрипт ручной обработки платежа #36714276
Telegram ID: 884740782
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

# Данные платежа из Prodamus
PAYMENT_DATA = {
    'telegram_id': 884740782,  # VK ID из Prodamus
    'order_id': '36714276',
    'transaction_id': 'g4287b14-dff6-4acb-ae25-8f4ce81dc368',
    'phone': '+79102991103',
    'email': 'alyayv@yandex.ru',
    'amount': 990,
    'days': 30,
    'payment_date': '2025-10-10 00:20:15',
    'subscription_profile_id': '1014211'  # profile_id из Prodamus
}

CLUB_CHANNEL_URL = "https://t.me/+Z77jamwsi1hiNTZi"

async def process_manual_payment():
    """Обрабатывает платеж вручную"""
    logger.info('='*60)
    logger.info(f'РУЧНАЯ ОБРАБОТКА ПЛАТЕЖА #{PAYMENT_DATA["order_id"]}')
    logger.info('='*60)
    
    async with AsyncSessionLocal() as session:
        # Ищем пользователя по Telegram ID
        logger.info(f'Ищем пользователя по Telegram ID: {PAYMENT_DATA["telegram_id"]}')
        
        user = await get_user_by_telegram_id(session, PAYMENT_DATA['telegram_id'])
        
        if not user:
            logger.error(f'❌ Пользователь с Telegram ID {PAYMENT_DATA["telegram_id"]} НЕ НАЙДЕН!')
            logger.error('Пользователь должен сначала запустить бота через /start')
            return
        
        logger.info(f'✅ Найден пользователь: ID={user.id}, TG_ID={user.telegram_id}')
        logger.info(f'   Имя: {user.first_name} {user.last_name or ""}')
        logger.info(f'   Username: @{user.username if user.username else "нет"}')
        logger.info(f'   Телефон: {user.phone}')
        logger.info(f'   Email: {user.email}')
        
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
            subscription_id=PAYMENT_DATA['subscription_profile_id']  # profile_id от Prodamus
        )
        
        logger.info(f'✅ Подписка создана/продлена: ID={subscription.id}')
        logger.info(f'   Начало: {subscription.start_date.strftime("%d.%m.%Y %H:%M")}')
        logger.info(f'   Окончание: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
        logger.info(f'   Prodamus subscription_id: {subscription.subscription_id}')
        
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
            details=f"Ручная обработка платежа #{PAYMENT_DATA['order_id']} от {PAYMENT_DATA['payment_date']}. Пропущенный webhook от Prodamus.",
            payment_label=f"manual_{PAYMENT_DATA['order_id']}",
            days=PAYMENT_DATA['days']
        )
        
        # Обновляем is_confirmed и prodamus_order_id
        payment_log.is_confirmed = True
        payment_log.prodamus_order_id = PAYMENT_DATA['order_id']
        await session.commit()
        
        logger.info(f'✅ Платеж записан: PaymentLog ID={payment_log.id}')
        logger.info(f'   Prodamus order_id: {payment_log.prodamus_order_id}')
        
        # Проверяем, первый ли это платеж
        is_first = await is_first_payment_by_user(session, user.id, payment_log.id)
        logger.info(f'   Первый платеж пользователя: {"Да" if is_first else "Нет"}')
        
        # Если первый платеж - проверяем реферера
        if is_first:
            referrer = await get_referrer_info(session, user.id, bot)
            if referrer:
                logger.info(f'\n🎁 Найден реферер: {referrer.telegram_id} (@{referrer.username})')
                logger.info(f'   Начисляем +7 дней рефереру...')
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
                else:
                    logger.warning(f'⚠️  Не удалось начислить бонус реферу (возможно, нет активной подписки)')
            else:
                logger.info('ℹ️  Реферер не найден')
        
        # Отправляем уведомление пользователю
        logger.info(f'\nОтправляем уведомление пользователю {user.telegram_id}...')
        
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
        
        logger.info('\n' + '='*60)
        logger.info('✅ ПЛАТЕЖ УСПЕШНО ОБРАБОТАН ВРУЧНУЮ!')
        logger.info('='*60)
        logger.info(f'Пользователь: {user.first_name} (TG: {user.telegram_id})')
        logger.info(f'Подписка до: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
        logger.info(f'PaymentLog ID: {payment_log.id}')
        logger.info('='*60)

async def main():
    try:
        await process_manual_payment()
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())

