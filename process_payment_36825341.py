"""
Обработка пропущенного платежа #36825341
Дата: 13.10.2025 11:30:47
Телефон: +79213553958
Email: Qdiagord@gmail.com
Сумма: 990 руб (30 дней)
"""
import asyncio
import logging
from datetime import timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_subscription_by_subscription_id,
    create_payment_log,
    send_payment_notification_to_admins
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

# Данные из скриншота
PAYMENT_DATA = {
    'order_id': '36825341',
    'phone': '+79213553958',
    'email': 'Qdiagord@gmail.com',
    'amount': 990,
    'days': 30,
    'payment_date': '13.10.2025 11:30:47'
}

CLUB_CHANNEL_URL = "https://t.me/+Z77jamwsi1hiNTZi"

async def find_user_by_phone(session):
    """Ищет пользователя по телефону (с разными форматами)"""
    # Пробуем разные форматы телефона
    phone_variants = [
        '+79213553958',
        '79213553958',
        '89213553958',
        '9213553958'
    ]
    
    for phone in phone_variants:
        query = select(User).where(User.phone == phone)
        result = await session.execute(query)
        user = result.scalar_one_or_none()
        if user:
            logger.info(f'✅ Найден по телефону {phone}')
            return user
    
    # Пробуем по email
    query = select(User).where(User.email == PAYMENT_DATA['email'])
    result = await session.execute(query)
    user = result.scalar_one_or_none()
    if user:
        logger.info(f'✅ Найден по email')
        return user
    
    return None

async def process_payment():
    """Обработка платежа"""
    logger.info('='*60)
    logger.info(f'ОБРАБОТКА ПЛАТЕЖА #{PAYMENT_DATA["order_id"]}')
    logger.info('='*60)
    
    async with AsyncSessionLocal() as session:
        # Ищем пользователя
        logger.info(f'Поиск пользователя...')
        user = await find_user_by_phone(session)
        
        if not user:
            logger.error('❌ ПОЛЬЗОВАТЕЛЬ НЕ НАЙДЕН!')
            logger.info('\nПоследние 10 пользователей:')
            query = select(User).order_by(User.created_at.desc()).limit(10)
            result = await session.execute(query)
            users = result.scalars().all()
            for u in users:
                logger.info(f'  TG: {u.telegram_id} | Tel: {u.phone} | Email: {u.email} | {u.first_name}')
            return
        
        logger.info(f'✅ Найден пользователь:')
        logger.info(f'   ID: {user.id}')
        logger.info(f'   Telegram: {user.telegram_id}')
        logger.info(f'   Имя: {user.first_name} (@{user.username})')
        logger.info(f'   Телефон: {user.phone}')
        
        # Ищем активную подписку
        query = select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.is_active == True
        ).order_by(Subscription.end_date.desc())
        result = await session.execute(query)
        subscription = result.scalar_one_or_none()
        
        if not subscription:
            logger.error('❌ Активная подписка не найдена!')
            # Создаем новую
            from datetime import datetime
            from database.crud import create_subscription
            
            end_date = datetime.now() + timedelta(days=PAYMENT_DATA['days'])
            subscription = await create_subscription(
                session,
                user_id=user.id,
                end_date=end_date,
                price=PAYMENT_DATA['amount'],
                payment_id=f"manual_{PAYMENT_DATA['order_id']}",
                renewal_price=PAYMENT_DATA['amount'],
                renewal_duration_days=PAYMENT_DATA['days']
            )
            logger.info(f'✅ Создана новая подписка до {end_date.strftime("%d.%m.%Y")}')
        else:
            logger.info(f'✅ Найдена подписка ID={subscription.id}')
            logger.info(f'   Окончание ДО: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
            
            # Продлеваем на 30 дней
            new_end_date = subscription.end_date + timedelta(days=PAYMENT_DATA['days'])
            
            query = update(Subscription).where(
                Subscription.id == subscription.id
            ).values(
                end_date=new_end_date,
                is_active=True
            )
            await session.execute(query)
            await session.commit()
            
            logger.info(f'✅ Подписка продлена!')
            logger.info(f'   Окончание ПОСЛЕ: {new_end_date.strftime("%d.%m.%Y %H:%M")}')
            
            # Обновляем объект
            await session.refresh(subscription)
        
        # Записываем платеж
        logger.info('\n📝 Записываем платеж...')
        
        payment_log = await create_payment_log(
            session,
            user_id=user.id,
            amount=PAYMENT_DATA['amount'],
            status='success',
            subscription_id=subscription.id,
            payment_method='prodamus',
            transaction_id=f"manual_{PAYMENT_DATA['order_id']}",
            details=f"Ручная обработка платежа #{PAYMENT_DATA['order_id']} от {PAYMENT_DATA['payment_date']}",
            payment_label=f"manual_{PAYMENT_DATA['order_id']}",
            days=PAYMENT_DATA['days']
        )
        
        payment_log.is_confirmed = True
        payment_log.prodamus_order_id = PAYMENT_DATA['order_id']
        await session.commit()
        
        logger.info(f'✅ Платеж записан: ID={payment_log.id}')
        
        # Отправляем уведомление пользователю
        logger.info('\n📱 Отправляем уведомление пользователю...')
        
        try:
            message_text = (
                f"✨ <b>Подписка успешно активирована!</b> ✨\n\n"
                f"Спасибо за оплату! Ваша подписка на Mom's Club продлена.\n\n"
                f"📅 <b>Активна до:</b> {subscription.end_date.strftime('%d.%m.%Y')}\n"
                f"💰 <b>Сумма:</b> {PAYMENT_DATA['amount']} ₽\n\n"
                f"Добро пожаловать! 💖"
            )
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🩷 Перейти в Mom's Club", url=CLUB_CHANNEL_URL)
                ]]
            )
            
            await bot.send_message(
                user.telegram_id,
                message_text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            logger.info(f'✅ Пользователь {user.telegram_id} уведомлен')
        except Exception as e:
            logger.error(f'❌ Ошибка отправки пользователю: {e}')
        
        # Отправляем админам
        logger.info('\n👨‍💼 Отправляем уведомление админам...')
        
        try:
            await send_payment_notification_to_admins(
                bot, user, payment_log, subscription,
                f"manual_{PAYMENT_DATA['order_id']}"
            )
            logger.info('✅ Админы уведомлены')
        except Exception as e:
            logger.error(f'❌ Ошибка уведомления админов: {e}')
        
        logger.info('\n' + '='*60)
        logger.info('✅ ПЛАТЕЖ ОБРАБОТАН!')
        logger.info('='*60)
        logger.info(f'👤 Пользователь: {user.first_name} (@{user.username})')
        logger.info(f'📅 Подписка до: {subscription.end_date.strftime("%d.%m.%Y")}')
        logger.info(f'💰 Платеж: {PAYMENT_DATA["amount"]} ₽')
        logger.info('='*60)

async def main():
    try:
        await process_payment()
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())

