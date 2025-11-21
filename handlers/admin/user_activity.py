"""
Модуль расширенной активности пользователя в группе для админки
Показывает детальную статистику активности на основе GroupActivityLog
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, and_
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id, get_group_activity
from database.models import User, GroupActivity, GroupActivityLog
from utils.admin_permissions import is_admin

logger = logging.getLogger(__name__)

# Создаём роутер для расширенной активности
activity_router = Router()


async def calculate_activity_stats(session, user: User) -> Dict:
    """
    Подсчитывает расширенную статистику активности пользователя в группе
    
    Args:
        session: Сессия БД
        user: Объект пользователя
        
    Returns:
        dict: Словарь со статистикой
    """
    # Получаем общую активность
    activity = await get_group_activity(session, user.id)
    
    if not activity or activity.message_count == 0:
        return {
            'total_messages': 0,
            'avg_per_day': 0,
            'most_active_day': None,
            'most_active_count': 0,
            'active_days_count': 0,
            'total_days': 0,
            'active_percentage': 0,
            'last_activity': None,
            'month_change': 0
        }
    
    # Получаем все записи из лога
    query = select(GroupActivityLog).where(
        GroupActivityLog.user_id == user.id
    ).order_by(GroupActivityLog.date.desc())
    
    result = await session.execute(query)
    logs = result.scalars().all()
    
    if not logs:
        # Есть общая активность, но нет детального лога (старые данные)
        return {
            'total_messages': activity.message_count,
            'avg_per_day': 0,
            'most_active_day': None,
            'most_active_count': 0,
            'active_days_count': 0,
            'total_days': 0,
            'active_percentage': 0,
            'last_activity': activity.last_activity,
            'month_change': 0
        }
    
    # Подсчёт статистики
    total_messages = activity.message_count
    active_days_count = len(logs)
    
    # Самый активный день
    most_active_log = max(logs, key=lambda x: x.message_count)
    most_active_day = most_active_log.date
    most_active_count = most_active_log.message_count
    
    # Дата первой записи в логе
    first_log_date = logs[-1].date if logs else datetime.now().date()
    total_days = (datetime.now().date() - first_log_date).days + 1
    
    # Среднее в день (по активным дням)
    avg_per_day = total_messages / active_days_count if active_days_count > 0 else 0
    
    # Процент активных дней
    active_percentage = (active_days_count / total_days * 100) if total_days > 0 else 0
    
    # Динамика за месяц
    month_ago = datetime.now().date() - timedelta(days=30)
    current_month_logs = [log for log in logs if log.date >= month_ago]
    prev_month_start = month_ago - timedelta(days=30)
    prev_month_logs = [log for log in logs if prev_month_start <= log.date < month_ago]
    
    current_month_messages = sum(log.message_count for log in current_month_logs)
    prev_month_messages = sum(log.message_count for log in prev_month_logs)
    
    if prev_month_messages > 0:
        month_change = ((current_month_messages - prev_month_messages) / prev_month_messages * 100)
    else:
        month_change = 100 if current_month_messages > 0 else 0
    
    return {
        'total_messages': total_messages,
        'avg_per_day': avg_per_day,
        'most_active_day': most_active_day,
        'most_active_count': most_active_count,
        'active_days_count': active_days_count,
        'total_days': total_days,
        'active_percentage': active_percentage,
        'last_activity': activity.last_activity,
        'month_change': month_change
    }


@activity_router.callback_query(F.data.startswith("admin_user_activity:"))
async def show_user_activity(callback: CallbackQuery):
    """Показывает расширенную статистику активности пользователя в группе"""
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
            stats = await calculate_activity_stats(session, user)
            
            # Формируем сообщение
            username = f"@{user.username}" if user.username else f"ID: {user.telegram_id}"
            name = f"{user.first_name or ''} {user.last_name or ''}".strip() or username
            
            text = f"📊 <b>Расширенная активность в группе</b>\n\n"
            text += f"👤 Пользователь: {name}\n"
            text += f"{'─' * 30}\n\n"
            
            if stats['total_messages'] == 0:
                text += "📭 <i>Активности в группе пока нет</i>\n"
            else:
                # Общая статистика
                text += f"📝 <b>Всего сообщений:</b> {stats['total_messages']}\n"
                
                if stats['active_days_count'] > 0:
                    text += f"📊 <b>Среднее в день:</b> {stats['avg_per_day']:.1f} сообщ.\n"
                
                # Самый активный день
                if stats['most_active_day']:
                    text += f"🔥 <b>Самый активный день:</b> {stats['most_active_day'].strftime('%d.%m.%Y')} "
                    text += f"({stats['most_active_count']} сообщ.)\n"
                
                # Динамика
                if stats['month_change'] != 0:
                    if stats['month_change'] > 0:
                        text += f"📈 <b>Динамика за месяц:</b> +{stats['month_change']:.0f}%\n"
                    else:
                        text += f"📉 <b>Динамика за месяц:</b> {stats['month_change']:.0f}%\n"
                
                # Активных дней
                if stats['total_days'] > 0:
                    text += f"\n📅 <b>Активных дней:</b> {stats['active_days_count']} из {stats['total_days']} "
                    text += f"({stats['active_percentage']:.0f}%)\n"
                
                # Последняя активность
                if stats['last_activity']:
                    now = datetime.now()
                    delta = now - stats['last_activity']
                    
                    if delta.total_seconds() < 60:
                        time_ago = "только что"
                    elif delta.total_seconds() < 3600:
                        minutes = int(delta.total_seconds() / 60)
                        time_ago = f"{minutes} мин. назад"
                    elif delta.total_seconds() < 86400:
                        hours = int(delta.total_seconds() / 3600)
                        time_ago = f"{hours} ч. назад"
                    else:
                        days = delta.days
                        time_ago = f"{days} дн. назад"
                    
                    text += f"🕐 <b>Последняя активность:</b> {time_ago}\n"
            
            # Кнопка назад - зависит от источника
            if source == "analytics_menu":
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
        logger.error(f"Ошибка при показе активности пользователя: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке статистики", show_alert=True)
    
    await callback.answer()


def register_activity_handlers(dp):
    """Регистрирует обработчики расширенной активности"""
    dp.include_router(activity_router)
