"""
Модуль прогнозирования поведения пользователя для админки
Анализирует данные и предсказывает вероятность продления, риск оттока
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id, get_group_activity
from database.models import User, PaymentLog, Subscription, GroupActivity, GroupActivityLog
from utils.admin_permissions import is_admin
from loyalty.levels import calc_tenure_days

logger = logging.getLogger(__name__)

# Создаём роутер для прогнозирования
prediction_router = Router()


async def analyze_user_behavior(session, user: User) -> Dict:
    """
    Анализирует поведение пользователя и делает прогноз
    
    Returns:
        dict: Словарь с прогнозом и рекомендациями
    """
    
    # === 1. АНАЛИЗ ПОДПИСКИ ===
    
    # Получаем текущую подписку
    subscription_query = select(Subscription).where(
        Subscription.user_id == user.id
    ).order_by(Subscription.end_date.desc())
    
    subscription_result = await session.execute(subscription_query)
    subscription = subscription_result.scalars().first()
    
    has_active_subscription = False
    days_until_expiry = 0
    
    if subscription:
        has_active_subscription = subscription.is_active
        if subscription.end_date:
            days_until_expiry = (subscription.end_date.date() - datetime.now().date()).days
    
    # === 2. АНАЛИЗ ПЛАТЕЖЕЙ ===
    
    # Получаем историю платежей
    payments_query = select(PaymentLog).where(
        PaymentLog.user_id == user.id,
        PaymentLog.status.in_(['success', 'succeeded'])
    ).order_by(PaymentLog.created_at.desc())
    
    payments_result = await session.execute(payments_query)
    payments = payments_result.scalars().all()
    
    payment_count = len(payments)
    has_payments = payment_count > 0
    
    # Регулярность платежей (если больше 2 платежей)
    payment_regularity = 0
    if payment_count >= 2:
        # Средний интервал между платежами
        intervals = []
        for i in range(len(payments) - 1):
            delta = (payments[i].created_at - payments[i + 1].created_at).days
            intervals.append(delta)
        
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            # Если средний интервал близок к 30 дням - регулярно
            if 25 <= avg_interval <= 35:
                payment_regularity = 100
            elif 20 <= avg_interval <= 40:
                payment_regularity = 70
            else:
                payment_regularity = 40
    
    # === 3. АНАЛИЗ АКТИВНОСТИ ===
    
    activity = await get_group_activity(session, user.id)
    
    has_activity = activity and activity.message_count > 0
    activity_score = 0
    
    if has_activity:
        # Получаем активность за последние 30 дней
        month_ago = datetime.now().date() - timedelta(days=30)
        recent_logs_query = select(GroupActivityLog).where(
            GroupActivityLog.user_id == user.id,
            GroupActivityLog.date >= month_ago
        )
        recent_logs_result = await session.execute(recent_logs_query)
        recent_logs = recent_logs_result.scalars().all()
        
        recent_messages = sum(log.message_count for log in recent_logs)
        
        # Последняя активность
        if activity.last_activity:
            days_since_activity = (datetime.now() - activity.last_activity).days
            
            if days_since_activity <= 7:
                activity_recency = 100
            elif days_since_activity <= 14:
                activity_recency = 80
            elif days_since_activity <= 30:
                activity_recency = 50
            else:
                activity_recency = 20
        else:
            activity_recency = 0
        
        # Количество сообщений за месяц
        if recent_messages >= 50:
            activity_volume = 100
        elif recent_messages >= 20:
            activity_volume = 80
        elif recent_messages >= 10:
            activity_volume = 60
        elif recent_messages >= 5:
            activity_volume = 40
        else:
            activity_volume = 20
        
        activity_score = (activity_recency * 0.6 + activity_volume * 0.4)
    
    # === 4. АНАЛИЗ СТАЖА ===
    
    tenure_days = await calc_tenure_days(session, user)
    
    if tenure_days >= 180:  # 6+ месяцев
        tenure_score = 100
    elif tenure_days >= 90:  # 3+ месяца
        tenure_score = 80
    elif tenure_days >= 30:  # 1+ месяц
        tenure_score = 60
    else:
        tenure_score = 40
    
    # === 5. АНАЛИЗ ЛОЯЛЬНОСТИ ===
    
    loyalty_level = user.current_loyalty_level or 'none'
    
    loyalty_scores = {
        'platinum': 100,
        'gold': 80,
        'silver': 60,
        'none': 30
    }
    
    loyalty_score = loyalty_scores.get(loyalty_level, 30)
    
    # === 6. АНАЛИЗ АВТОПРОДЛЕНИЯ ===
    
    has_recurring = user.is_recurring_active
    recurring_score = 100 if has_recurring else 30
    
    # === 7. РАСЧЁТ ИТОГОВОГО ПРОГНОЗА ===
    
    # Веса для разных факторов
    weights = {
        'subscription': 0.25,  # Есть ли активная подписка
        'payments': 0.20,      # Регулярность платежей
        'activity': 0.20,      # Активность в группе
        'tenure': 0.15,        # Стаж
        'loyalty': 0.10,       # Уровень лояльности
        'recurring': 0.10      # Автопродление
    }
    
    # Оценки по факторам (0-100)
    subscription_score = 100 if has_active_subscription else 20
    
    # Итоговая вероятность продления
    renewal_probability = (
        subscription_score * weights['subscription'] +
        payment_regularity * weights['payments'] +
        activity_score * weights['activity'] +
        tenure_score * weights['tenure'] +
        loyalty_score * weights['loyalty'] +
        recurring_score * weights['recurring']
    )
    
    # Риск оттока (обратная вероятность)
    churn_risk = 100 - renewal_probability
    
    # === 8. ФОРМИРОВАНИЕ РЕКОМЕНДАЦИЙ ===
    
    recommendations = []
    
    # Рекомендации по подписке
    if not has_active_subscription:
        recommendations.append(("⚠️", "Нет активной подписки", "Предложить возобновить подписку"))
    elif days_until_expiry <= 7 and not has_recurring:
        recommendations.append(("⏰", "Подписка истекает через {} дн.".format(days_until_expiry), "Напомнить о продлении"))
    
    # Рекомендации по автопродлению
    if not has_recurring and renewal_probability >= 60:
        recommendations.append(("🔄", "Автопродление выключено", "Предложить включить автоплатёж"))
    
    # Рекомендации по активности
    if activity_score < 40:
        recommendations.append(("💬", "Низкая активность в группе", "Вовлечь в обсуждения"))
    
    # Рекомендации по лояльности
    if loyalty_level == 'none' and tenure_days >= 30:
        recommendations.append(("⭐", "Нет уровня лояльности", "Проверить начисление стажа"))
    
    # Рекомендации по стажу
    if tenure_days >= 180 and not has_recurring:
        recommendations.append(("🎁", "Долгий стаж ({}+ дн.)".format(tenure_days), "Предложить годовую подписку"))
    
    # Если всё отлично
    if renewal_probability >= 80 and not recommendations:
        recommendations.append(("✅", "Лояльный клиент", "Всё в порядке, продолжайте"))
    
    return {
        'renewal_probability': renewal_probability,
        'churn_risk': churn_risk,
        'has_active_subscription': has_active_subscription,
        'days_until_expiry': days_until_expiry,
        'payment_count': payment_count,
        'payment_regularity': payment_regularity,
        'activity_score': activity_score,
        'tenure_days': tenure_days,
        'loyalty_level': loyalty_level,
        'has_recurring': has_recurring,
        'recommendations': recommendations
    }


@prediction_router.callback_query(F.data.startswith("admin_user_prediction:"))
async def show_user_prediction(callback: CallbackQuery):
    """Показывает прогноз поведения пользователя"""
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
            
            # Получаем прогноз
            prediction = await analyze_user_behavior(session, user)
            
            # Формируем сообщение
            username = f"@{user.username}" if user.username else f"ID: {user.telegram_id}"
            name = f"{user.first_name or ''} {user.last_name or ''}".strip() or username
            
            text = f"🔮 <b>Прогноз поведения</b>\n\n"
            text += f"👤 Пользователь: {name}\n"
            text += f"{'─' * 30}\n\n"
            
            # Вероятность продления
            renewal = prediction['renewal_probability']
            if renewal >= 75:
                renewal_emoji = "🟢"
                renewal_text = "Высокая"
            elif renewal >= 50:
                renewal_emoji = "🟡"
                renewal_text = "Средняя"
            else:
                renewal_emoji = "🔴"
                renewal_text = "Низкая"
            
            text += f"📊 <b>Вероятность продления:</b> {renewal_emoji} {renewal_text} ({renewal:.0f}%)\n"
            
            # Риск оттока
            churn = prediction['churn_risk']
            if churn <= 25:
                churn_emoji = "🟢"
                churn_text = "Низкий"
            elif churn <= 50:
                churn_emoji = "🟡"
                churn_text = "Средний"
            else:
                churn_emoji = "🔴"
                churn_text = "Высокий"
            
            text += f"⚠️ <b>Риск оттока:</b> {churn_emoji} {churn_text} ({churn:.0f}%)\n\n"
            
            # Ключевые факторы
            text += f"<b>📈 Ключевые факторы:</b>\n\n"
            
            if prediction['has_active_subscription']:
                text += f"✅ Активная подписка"
                if prediction['days_until_expiry'] > 0:
                    text += f" (осталось {prediction['days_until_expiry']} дн.)"
                text += "\n"
            else:
                text += f"❌ Нет активной подписки\n"
            
            text += f"💳 Платежей: {prediction['payment_count']}"
            if prediction['payment_regularity'] > 0:
                text += f" (регулярность: {prediction['payment_regularity']:.0f}%)"
            text += "\n"
            
            if prediction['activity_score'] > 0:
                text += f"💬 Активность в группе: {prediction['activity_score']:.0f}%\n"
            else:
                text += f"💬 Активность в группе: нет данных\n"
            
            text += f"📅 Стаж: {prediction['tenure_days']} дн.\n"
            
            loyalty_names = {
                'platinum': '💎 Platinum',
                'gold': '🥇 Gold',
                'silver': '🥈 Silver',
                'none': 'Нет'
            }
            text += f"⭐ Лояльность: {loyalty_names.get(prediction['loyalty_level'], 'Нет')}\n"
            
            text += f"🔄 Автопродление: {'Включено ✅' if prediction['has_recurring'] else 'Выключено ❌'}\n"
            
            # Рекомендации
            if prediction['recommendations']:
                text += f"\n<b>💡 Рекомендации:</b>\n\n"
                for emoji, reason, action in prediction['recommendations'][:5]:  # Показываем первые 5
                    text += f"{emoji} <b>{reason}</b>\n"
                    text += f"   → {action}\n\n"
            
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
        logger.error(f"Ошибка при показе прогноза пользователя: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке прогноза", show_alert=True)
    
    await callback.answer()


def register_prediction_handlers(dp):
    """Регистрирует обработчики прогнозирования"""
    dp.include_router(prediction_router)
