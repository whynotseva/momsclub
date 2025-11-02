"""
Скрипт ручной обработки АВТОПРОДЛЕНИЯ #36714276
Это второй платеж по подписке profile_id: 1014211
Telegram ID: 884740782
"""
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_subscription_by_subscription_id,
    create_payment_log,
    send_payment_notification_to_admins
)
from sqlalchemy import update
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)

# Данные платежа
PAYMENT_DATA = {
    'telegram_id': 884740782,
    'order_id': '36714276',
    'subscription_profile_id': '1014211',
    'amount': 990,
    'days': 30
}

async def process_renewal():
    """Обрабатывает автопродление вручную"""
    logger.info('='*60)
    logger.info(f'ОБРАБОТКА АВТОПРОДЛЕНИЯ #{PAYMENT_DATA["order_id"]}')
    logger.info('='*60)
    
    async with AsyncSessionLocal() as session:
        # Находим пользователя
        user = await get_user_by_telegram_id(session, PAYMENT_DATA['telegram_id'])
        if not user:
            logger.error('❌ Пользователь не найден!')
            return
        
        logger.info(f'✅ Пользователь: {user.first_name} (@{user.username})')
        
        # Находим подписку по subscription_id
        subscription = await get_subscription_by_subscription_id(session, PAYMENT_DATA['subscription_profile_id'])
        
        if not subscription:
            logger.error('❌ Подписка не найдена!')
            return
        
        logger.info(f'✅ Найдена подписка ID={subscription.id}')
        logger.info(f'   Текущее окончание: {subscription.end_date.strftime("%d.%m.%Y %H:%M")}')
        
        # Продлеваем подписку на 30 дней
        new_end_date = subscription.end_date + timedelta(days=PAYMENT_DATA['days'])
        
        from database.models import Subscription
        query = (
            update(Subscription)
            .where(Subscription.id == subscription.id)
            .values(
                end_date=new_end_date,
                is_active=True
            )
        )
        await session.execute(query)
        await session.commit()
        
        logger.info(f'✅ Подписка продлена!')
        logger.info(f'   Новое окончание: {new_end_date.strftime("%d.%m.%Y %H:%M")}')
        
        # Записываем платеж
        logger.info('\nЗаписываем платеж в БД...')
        
        payment_log = await create_payment_log(
            session,
            user_id=user.id,
            amount=PAYMENT_DATA['amount'],
            status='success',
            subscription_id=subscription.id,
            payment_method='prodamus_auto',
            transaction_id=f"auto_{PAYMENT_DATA['order_id']}",
            details=f"Автопродление (ручная обработка) платежа #{PAYMENT_DATA['order_id']}",
            payment_label=f"autorenewal_{PAYMENT_DATA['order_id']}",
            days=PAYMENT_DATA['days']
        )
        
        payment_log.is_confirmed = True
        payment_log.prodamus_order_id = PAYMENT_DATA['order_id']
        await session.commit()
        
        logger.info(f'✅ Платеж записан: PaymentLog ID={payment_log.id}')
        
        # Отправляем уведомление пользователю
        logger.info('\nОтправляем уведомление...')
        
        try:
            await bot.send_message(
                user.telegram_id,
                f"✅ <b>Подписка автоматически продлена!</b>\n\n"
                f"Списано: {PAYMENT_DATA['amount']} ₽\n"
                f"Подписка активна до: {new_end_date.strftime('%d.%m.%Y')}\n\n"
                f"Спасибо, что остаетесь с нами! 💖",
                parse_mode='HTML'
            )
            logger.info('✅ Уведомление отправлено пользователю')
        except Exception as e:
            logger.error(f'Ошибка отправки: {e}')
        
        # Уведомление админам
        try:
            # Обновляем объект subscription для актуальной даты
            await session.refresh(subscription)
            subscription.end_date = new_end_date
            
            await send_payment_notification_to_admins(
                bot, user, payment_log, subscription, 
                f"auto_{PAYMENT_DATA['order_id']}"
            )
            logger.info('✅ Админы уведомлены')
        except Exception as e:
            logger.error(f'Ошибка уведомления админов: {e}')
        
        logger.info('='*60)
        logger.info('✅ АВТОПРОДЛЕНИЕ ОБРАБОТАНО!')
        logger.info('='*60)

async def main():
    try:
        await process_renewal()
    finally:
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())

