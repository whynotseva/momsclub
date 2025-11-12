"""
Обработка платежа #36825341 по username
Username: @BrankaKatic
Дата: 13.10.2025 11:30:47
Сумма: 990 руб (30 дней)
"""
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_username,
    create_payment_log,
    send_payment_notification_to_admins,
    extend_subscription_days,
    get_referrer_info,
    is_first_payment_by_user,
    extend_subscription
)
from database.models import User, Subscription
from sqlalchemy import update, select
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)

# Данные платежа
PAYMENT_DATA = {
    'username': 'BrankaKatic',  # Без @
    'order_id': '36825341',
    'amount': 990,
    'days': 30,
    'payment_date': '13.10.2025 11:30:47',
    'subscription_profile_id': '45026544'  # ID подписки из Prodamus
}

CLUB_CHANNEL_URL = "https://t.me/+Z77jamwsi1hiNTZi"
REFERRAL_BONUS_DAYS = 7

async def process_payment():
    """Обработка платежа по username"""
    logger.info('='*60)
    logger.info(f'ОБРАБОТКА ПЛАТЕЖА #{PAYMENT_DATA["order_id"]}')
    logger.info(f'Username: @{PAYMENT_DATA["username"]}')
    logger.info('='*60)
    
    async with AsyncSessionLocal() as session:
        # Ищем пользователя по username
        logger.info(f'Поиск пользователя @{PAYMENT_DATA["username"]}...')
        
        user = await get_user_by_username(session, PAYMENT_DATA['username'])
        
        if not user:
            logger.error(f'❌ Пользователь @{PAYMENT_DATA["username"]} НЕ НАЙДЕН!')
            logger.info('\nПопробуем поискать похожих...')
            query = select(User).where(User.username.ilike(f'%{PAYMENT_DATA["username"]}%'))
            result = await session.execute(query)
            similar = result.scalars().all()
            if similar:
                logger.info('Похожие username:')
                for u in similar:
                    logger.info(f'  @{u.username} - {u.first_name} (TG: {u.telegram_id})')
            return
        
        logger.info(f'✅ Найден пользователь:')
        logger.info(f'   ID: {user.id}')
        logger.info(f'   Telegram ID: {user.telegram_id}')
        logger.info(f'   Имя: {user.first_name} {user.last_name or ""}')
        logger.info(f'   Username: @{user.username}')
        logger.info(f'   Телефон: {user.phone or "не указан"}')
        logger.info(f'   Email: {user.email or "не указан"}')
        
        # Создаем/продлеваем подписку
        logger.info(f'\n📝 Создаем подписку на {PAYMENT_DATA["days"]} дней...')
        
        subscription = await extend_subscription(
            session,
            user_id=user.id,
            days=PAYMENT_DATA['days'],
            price=PAYMENT_DATA['amount'],
            payment_id=f"manual_{PAYMENT_DATA['order_id']}",
            renewal_price=PAYMENT_DATA['amount'],
            renewal_duration_days=PAYMENT_DATA['days'],
            subscription_id=PAYMENT_DATA['subscription_profile_id']
        )
        
        logger.info(f'✅ Подписка создана/продлена:')
        logger.info(f'   Subscription ID: {subscription.id}')
        logger.info(f'   Prodamus profile_id: {subscription.subscription_id}')
        logger.info(f'   Активна до: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
        
        # Записываем платеж
        logger.info('\n💰 Записываем платеж в БД...')
        
        payment_log = await create_payment_log(
            session,
            user_id=user.id,
            amount=PAYMENT_DATA['amount'],
            status='success',
            subscription_id=subscription.id,
            payment_method='prodamus',
            transaction_id=f"manual_{PAYMENT_DATA['order_id']}",
            details=f"Ручная обработка платежа #{PAYMENT_DATA['order_id']} от {PAYMENT_DATA['payment_date']}. Пропущенный webhook.",
            payment_label=f"manual_{PAYMENT_DATA['order_id']}",
            days=PAYMENT_DATA['days']
        )
        
        # Обновляем флаги
        payment_log.is_confirmed = True
        payment_log.prodamus_order_id = PAYMENT_DATA['order_id']
        await session.commit()
        
        logger.info(f'✅ Платеж записан: PaymentLog ID={payment_log.id}')
        
        # Проверяем, первый ли это платеж
        is_first = await is_first_payment_by_user(session, user.id, payment_log.id)
        logger.info(f'   Первый платеж: {"Да ✨" if is_first else "Нет (продление)"}')
        
        # Если первый платеж - проверяем реферера
        if is_first:
            referrer = await get_referrer_info(session, user.id, bot)
            if referrer:
                logger.info(f'\n🎁 Найден реферер: @{referrer.username} (TG: {referrer.telegram_id})')
                logger.info(f'   Начисляем +{REFERRAL_BONUS_DAYS} дней...')
                
                success = await extend_subscription_days(session, referrer.id, REFERRAL_BONUS_DAYS, "referral_bonus")
                
                if success:
                    logger.info(f'✅ Реферу начислено +{REFERRAL_BONUS_DAYS} дней')
                    try:
                        await bot.send_message(
                            referrer.telegram_id,
                            f"🎁 <b>Вам начислен бонус за приглашение!</b>\n\n"
                            f"Пользователь {user.first_name} оплатил подписку, и ваша подписка автоматически продлена на {REFERRAL_BONUS_DAYS} дней.\n\n"
                            f"Спасибо за участие в программе приглашений Mom's Club! 💖",
                            parse_mode='HTML'
                        )
                        logger.info(f'✅ Уведомление отправлено реферу')
                    except Exception as e:
                        logger.error(f'Ошибка отправки реферу: {e}')
                else:
                    logger.warning('⚠️  Не удалось начислить бонус (нет активной подписки у реферера)')
            else:
                logger.info('ℹ️  Реферер не найден')
        
        # Отправляем уведомление пользователю
        logger.info(f'\n📱 Отправляем уведомление пользователю @{user.username}...')
        
        try:
            success_message = (
                f"✨ <b>Подписка успешно оформлена!</b> ✨\n\n"
                f"Спасибо за оплату! Ваша подписка на Mom's Club активирована.\n\n"
                f"📅 <b>Активна до:</b> {subscription.end_date.strftime('%d.%m.%Y')}\n"
                f"💰 <b>Сумма:</b> {PAYMENT_DATA['amount']} ₽\n\n"
                f"Добро пожаловать в наш уютный клуб! 💖"
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
            logger.info(f'✅ Уведомление отправлено пользователю (TG: {user.telegram_id})')
        except Exception as e:
            logger.error(f'❌ Ошибка отправки пользователю: {e}')
        
        # Отправляем уведомление админам
        logger.info('\n👨‍💼 Отправляем уведомление админам...')
        
        try:
            await send_payment_notification_to_admins(
                bot, user, payment_log, subscription,
                f"manual_{PAYMENT_DATA['order_id']}"
            )
            logger.info('✅ Админы уведомлены')
        except Exception as e:
            logger.error(f'❌ Ошибка уведомления админов: {e}')
        
        # Финальный отчет
        logger.info('\n' + '='*60)
        logger.info('✅ ✅ ✅ ПЛАТЕЖ УСПЕШНО ОБРАБОТАН! ✅ ✅ ✅')
        logger.info('='*60)
        logger.info(f'👤 Пользователь: {user.first_name} (@{user.username})')
        logger.info(f'📱 Telegram ID: {user.telegram_id}')
        logger.info(f'📅 Подписка до: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
        logger.info(f'💰 Платеж: {PAYMENT_DATA["amount"]} ₽')
        logger.info(f'📋 PaymentLog ID: {payment_log.id}')
        logger.info(f'🔄 Subscription ID: {subscription.id}')
        logger.info('='*60)

async def main():
    try:
        await process_payment()
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())

