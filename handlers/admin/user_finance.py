"""
Модуль финансовой статистики пользователя для админки
Показывает подробную информацию о платежах пользователя
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id
from database.models import User, PaymentLog
from utils.admin_permissions import is_admin
from loyalty.levels import calc_tenure_days

logger = logging.getLogger(__name__)

# Создаём роутер для финансовой статистики
finance_router = Router()


async def calculate_user_finance_stats(session, user: User) -> dict:
    """
    Подсчитывает финансовую статистику пользователя
    
    Args:
        session: Сессия БД
        user: Объект пользователя
        
    Returns:
        dict: Словарь со статистикой
    """
    # Получаем все успешные платежи
    query = select(PaymentLog).where(
        PaymentLog.user_id == user.id,
        PaymentLog.status.in_(['success', 'succeeded'])
    ).order_by(PaymentLog.created_at.desc())
    
    result = await session.execute(query)
    payments = result.scalars().all()
    
    if not payments:
        return {
            'total_amount': 0,
            'payment_count': 0,
            'average_check': 0,
            'last_payment_amount': 0,
            'last_payment_date': None,
            'is_recurring_active': getattr(user, 'is_recurring_active', False),
            'first_payment_date': None,
            'tenure_days': 0
        }
    
    # Подсчёт статистики
    total_amount = sum(p.amount for p in payments)
    payment_count = len(payments)
    average_check = total_amount / payment_count if payment_count > 0 else 0
    
    # Последний платёж
    last_payment = payments[0]
    last_payment_amount = last_payment.amount
    last_payment_date = last_payment.created_at
    
    # Реальный стаж - используем calc_tenure_days (как в системе лояльности)
    # Это считает только дни АКТИВНЫХ подписок, без перерывов
    tenure_days = await calc_tenure_days(session, user)
    
    # Дата первой оплаты для отображения
    first_payment_date = user.first_payment_date
    
    # Статус автопродления (текущий статус, а не история)
    is_recurring_active = getattr(user, 'is_recurring_active', False)
    
    return {
        'total_amount': total_amount,
        'payment_count': payment_count,
        'average_check': average_check,
        'last_payment_amount': last_payment_amount,
        'last_payment_date': last_payment_date,
        'is_recurring_active': is_recurring_active,
        'first_payment_date': first_payment_date,
        'tenure_days': tenure_days
    }


@finance_router.callback_query(F.data.startswith("admin_user_finance:"))
async def show_user_finance(callback: CallbackQuery):
    """Показывает финансовую статистику пользователя"""
    try:
        async with AsyncSessionLocal() as session:
            # Проверка прав админа
            admin_user = await get_user_by_telegram_id(session, callback.from_user.id)
            if not admin_user or not is_admin(admin_user):
                await callback.answer("❌ Доступ запрещён", show_alert=True)
                return
            
            # Получаем ID пользователя и источник
            parts = callback.data.split(":")
            telegram_id = int(parts[1])
            source = parts[2] if len(parts) > 2 else None
            
            # Получаем пользователя
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            # Получаем статистику
            stats = await calculate_user_finance_stats(session, user)
            
            # Формируем сообщение
            username = f"@{user.username}" if user.username else f"ID: {user.telegram_id}"
            name = f"{user.first_name or ''} {user.last_name or ''}".strip() or username
            
            text = f"💰 <b>Финансовая статистика</b>\n\n"
            text += f"👤 Пользователь: {name}\n"
            text += f"{'─' * 30}\n\n"
            
            if stats['payment_count'] == 0:
                text += "📭 <i>Платежей пока нет</i>\n\n"
                # Статус автопродления даже если нет платежей
                if stats['is_recurring_active']:
                    text += f"🔄 <b>Автопродление:</b> Включено ✅\n"
                else:
                    text += f"🔄 <b>Автопродление:</b> Выключено ❌\n"
            else:
                # Стаж и дата регистрации
                if stats['first_payment_date']:
                    text += f"📅 <b>Клиент с:</b> {stats['first_payment_date'].strftime('%d.%m.%Y')}\n"
                    text += f"📊 <b>Стаж:</b> {stats['tenure_days']} дн. "
                    text += "<i>(только активные дни)</i>\n\n"
                
                # Общая статистика
                text += f"💵 <b>Всего оплачено:</b> {stats['total_amount']:,.0f}₽\n"
                text += f"📊 <b>Количество платежей:</b> {stats['payment_count']}\n"
                text += f"📈 <b>Средний чек:</b> {stats['average_check']:.0f}₽\n\n"
                
                # Последний платёж
                if stats['last_payment_date']:
                    days_ago = (datetime.now() - stats['last_payment_date']).days
                    
                    if days_ago == 0:
                        time_ago = "сегодня"
                    elif days_ago == 1:
                        time_ago = "вчера"
                    else:
                        time_ago = f"{days_ago} дн. назад"
                    
                    text += f"💳 <b>Последний платёж:</b> {stats['last_payment_amount']:.0f}₽ ({time_ago})\n\n"
                
                # Статус автопродления
                if stats['is_recurring_active']:
                    text += f"🔄 <b>Автопродление:</b> Включено ✅\n"
                else:
                    text += f"🔄 <b>Автопродление:</b> Выключено ❌\n"
            
            # Кнопка назад - зависит от источника
            if source == "sub_menu":
                back_text = "« Назад к управлению подпиской"
                back_callback = f"admin_subscription_menu:{telegram_id}"
            elif source == "analytics_menu":
                back_text = "« Назад к аналитике"
                back_callback = f"admin_analytics_menu:{telegram_id}"
            else:
                back_text = "« Назад к пользователю"
                back_callback = f"admin_user_info:{telegram_id}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=back_text,
                    callback_data=back_callback
                )]
            ])
            
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка при показе финансовой статистики: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке статистики", show_alert=True)
    
    await callback.answer()


def register_finance_handlers(dp):
    """Регистрирует обработчики финансовой статистики"""
    dp.include_router(finance_router)
