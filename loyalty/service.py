"""
Публичные фасады для системы лояльности
"""
import logging
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from database.models import User, LoyaltyEvent
from .levels import upgrade_level_if_needed, calc_tenure_days
from .benefits import apply_benefit, apply_benefit_for_inactive_user
from database.crud import get_active_subscription

logger = logging.getLogger(__name__)


def effective_discount(user: User) -> int:
    """
    Вычисляет эффективную скидку для пользователя с учётом приоритета.
    Приоритет: lifetime 15% > one-time 10% > one-time 5%
    Суммирование запрещено.
    
    Args:
        user: Объект пользователя
        
    Returns:
        Процент скидки (0, 5, 10 или 15)
    """
    if user.lifetime_discount_percent and user.lifetime_discount_percent > 0:
        return user.lifetime_discount_percent
    
    if user.one_time_discount_percent and user.one_time_discount_percent > 0:
        return user.one_time_discount_percent
    
    return 0


def price_with_discount(base_price: int, discount_percent: int) -> int:
    """
    Вычисляет цену со скидкой.
    
    Args:
        base_price: Базовая цена в копейках
        discount_percent: Процент скидки (0-100)
        
    Returns:
        Цена со скидкой в копейках
    """
    if discount_percent <= 0:
        return base_price
    
    discount_amount = (base_price * discount_percent) // 100
    return base_price - discount_amount


async def send_choose_benefit_push(
    bot,
    db: AsyncSession,
    user: User,
    level: str,
    is_reminder: bool = False
) -> bool:
    """
    Отправляет пользователю сообщение с выбором бонуса для достигнутого уровня.
    Отправляет только пользователям с активной подпиской.
    
    Args:
        bot: Объект Telegram бота
        db: Сессия БД
        user: Объект пользователя
        level: Уровень лояльности ('silver', 'gold', 'platinum')
        is_reminder: Флаг напоминания (если True, используется другой заголовок)
        
    Returns:
        True если успешно отправлено, False в противном случае
    """
    user_id = user.id  # Сохраняем ID заранее для логирования
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from aiogram import Bot
        
        if not isinstance(bot, Bot):
            logger.error(f"Некорректный тип бота: {type(bot)}")
            return False
        
        # Проверяем наличие активной подписки
        active_sub = await get_active_subscription(db, user.id)
        if not active_sub:
            logger.info(f"Пропуск отправки push для user_id={user.id}: нет активной подписки (уровень {level})")
            return False
        
        # Тексты и кнопки для каждого уровня
        level_configs = {
            'silver': {
                'text': (
                    ("🔔 <b>Напоминаем, красотка!</b> ✨\n\n" if is_reminder else "🎉 <b>Красотка, ты с нами уже 3 месяца!</b> ✨\n\n") +
                    "Спасибо за твоё доверие и за то, что ты часть нашего клуба 🩷\n\n"
                    "Твой статус: <b>Silver Mom</b> ⭐\n\n"
                    "Выбери свой подарочек:"
                ),
                'buttons': [
                    ("💰 −5% навсегда", "benefit:silver:discount_5"),
                    ("🎁 +7 дней доступа", "benefit:silver:days_7"),
                ]
            },
            'gold': {
                'text': (
                    ("🔔 <b>Напоминаем, красотка!</b> ✨\n\n" if is_reminder else "🌟 <b>Красотка, целых 6 месяцев вместе!</b> 💖\n\n") +
                    "Ты — настоящая часть семьи Mom's Club, и мы это ценим 🫂\n\n"
                    "Твой статус: <b>Gold Mom</b> 🌟\n\n"
                    "Выбери свой подарок:"
                ),
                'buttons': [
                    ("💰 −10% навсегда", "benefit:gold:discount_10"),
                    ("🎁 +14 дней доступа", "benefit:gold:days_14"),
                ]
            },
            'platinum': {
                'text': (
                    ("🔔 <b>Напоминаем, красотка!</b> ✨\n\n" if is_reminder else "💎 <b>Красотка, ты с нами целый год!</b> 😍✨\n\n") +
                    "Это особенный момент — целый год мы вместе! Спасибо за твою верность и тепло, которое ты привносишь в наш клуб 🩷\n\n"
                    "Твой статус: <b>Platinum Mom</b> 💍\n\n"
                    "Выбери свой особенный подарок:"
                ),
                'buttons': [
                    ("💎 −15% навсегда", "benefit:platinum:discount_15_forever"),
                    ("🎁 +1 месяц + подарок", "benefit:platinum:days_30_gift"),
                ]
            }
        }
        
        config = level_configs.get(level)
        if not config:
            logger.error(f"Неизвестный уровень лояльности: {level}")
            return False
        
        # Создаём inline-клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=callback_data)]
            for text, callback_data in config['buttons']
        ])
        
        # Отправляем сообщение
        await bot.send_message(
            chat_id=user.telegram_id,
            text=config['text'],
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        logger.info(f"✅ Отправлено сообщение выбора бонуса для user_id={user.id}, level={level}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке сообщения выбора бонуса для user_id={user_id}: {e}", exc_info=True)
        return False


async def apply_benefit_from_callback(
    db: AsyncSession,
    user: User,
    level: str,
    code: str
) -> bool:
    """
    Применяет бонус из callback-кнопки.
    Проверяет идемпотентность, применяет бонус, обновляет флаг pending_loyalty_reward.
    
    ИСПРАВЛЕНО: Добавлена защита от race condition и проверка идемпотентности.
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        level: Уровень лояльности
        code: Код бонуса
        
    Returns:
        True если успешно применено, False в противном случае
    """
    user_id = user.id  # Сохраняем ID заранее для логирования
    try:
        # ИСПРАВЛЕНО CRIT-002: Убрали with_for_update() для совместимости с SQLite
        # SQLite не поддерживает SELECT FOR UPDATE
        # Вместо блокировок используем проверку идемпотентности через LoyaltyEvent
        user_query = select(User).where(User.id == user_id)
        result = await db.execute(user_query)
        locked_user = result.scalar_one()
        # Сохраняем locked_user_id для защиты от greenlet
        locked_user_id = locked_user.id
        
        # Проверяем идемпотентность: не применялся ли уже бонус для этого уровня
        benefit_check_query = select(LoyaltyEvent.id).where(
            LoyaltyEvent.user_id == locked_user_id,
            LoyaltyEvent.kind == 'benefit_chosen',
            LoyaltyEvent.level == level
        )
        benefit_check_result = await db.execute(benefit_check_query)
        
        if benefit_check_result.scalar_one_or_none():
            logger.warning(f"⚠️ Бонус для уровня {level} уже применён для user_id={locked_user_id}")
            return False
        
        # Применяем бонус (внутри apply_benefit уже есть проверка на активную подписку)
        success = await apply_benefit(db, locked_user, level, code)
        
        if success:
            # Сбрасываем флаг ожидания награды
            locked_user.pending_loyalty_reward = False
            
            # Коммитим все изменения атомарно
            await db.commit()
            
            logger.info(f"✅ Бонус {code} успешно применён для user_id={locked_user_id}")
            return True
        else:
            logger.error(f"❌ Не удалось применить бонус {code} для user_id={locked_user_id}")
            await db.rollback()
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при применении бонуса из callback для user_id={user_id}: {e}", exc_info=True)
        await db.rollback()
        return False


async def send_loyalty_reminders(bot, db: AsyncSession) -> dict:
    """
    Отправляет напоминания пользователям, которые не выбрали бонус лояльности.
    Вызывается раз в неделю (каждый понедельник).
    
    Args:
        bot: Объект бота
        db: Сессия БД
        
    Returns:
        Словарь со статистикой отправки
    """
    from sqlalchemy import select
    from database.models import User, LoyaltyEvent
    from database.crud import get_active_subscription
    
    stats = {
        'total_checked': 0,
        'with_pending': 0,
        'with_active_sub': 0,
        'reminders_sent': 0,
        'skipped_no_sub': 0,
        'already_chosen': 0,
        'errors': 0
    }
    
    try:
        # Получаем всех пользователей с pending_loyalty_reward = True
        # и current_loyalty_level != 'none'
        query = select(User).where(
            User.pending_loyalty_reward == True,
            User.current_loyalty_level.isnot(None),
            User.current_loyalty_level != 'none'
        )
        
        result = await db.execute(query)
        users = result.scalars().all()
        
        stats['total_checked'] = len(users)
        logger.info(f"🔔 Проверка напоминаний: найдено {len(users)} пользователей с pending_loyalty_reward")
        
        for user in users:
            try:
                stats['with_pending'] += 1
                
                # ИСПРАВЛЕНИЕ БАГА: Проверяем АКТУАЛЬНЫЙ рассчитанный уровень
                # Если уровень в базе не соответствует рассчитанному - пропускаем
                from loyalty.levels import calc_tenure_days, level_for_days
                tenure_days = await calc_tenure_days(db, user)
                actual_level = level_for_days(tenure_days)
                
                if user.current_loyalty_level != actual_level:
                    logger.warning(
                        f"⚠️ Несоответствие уровней user_id={user.id}: "
                        f"db={user.current_loyalty_level}, actual={actual_level}, tenure={tenure_days}"
                    )
                    # Обновляем уровень в базе и сбрасываем pending если уровень стал none
                    if actual_level == 'none':
                        from sqlalchemy import update as sql_update
                        await db.execute(
                            sql_update(User)
                            .where(User.id == user.id)
                            .values(current_loyalty_level=actual_level, pending_loyalty_reward=False)
                        )
                        await db.commit()
                        logger.info(f"📉 Сброшен уровень и pending для user_id={user.id}")
                    continue
                
                # Проверяем, не выбирал ли уже пользователь бонус для ТЕКУЩЕГО уровня
                benefit_check_query = select(LoyaltyEvent.id).where(
                    LoyaltyEvent.user_id == user.id,
                    LoyaltyEvent.kind == 'benefit_chosen',
                    LoyaltyEvent.level == user.current_loyalty_level
                )
                benefit_check_result = await db.execute(benefit_check_query)
                
                if benefit_check_result.scalar_one_or_none():
                    # Пользователь уже выбирал бонус для этого уровня
                    stats['already_chosen'] += 1
                    logger.debug(f"ℹ️  Пропуск (бонус уже выбран): user_id={user.id}, level={user.current_loyalty_level}")
                    continue
                
                # Проверяем активную подписку
                active_sub = await get_active_subscription(db, user.id)
                
                if not active_sub:
                    stats['skipped_no_sub'] += 1
                    logger.debug(f"⏭️  Пропуск (нет активной подписки): user_id={user.id}")
                    continue
                
                stats['with_active_sub'] += 1
                
                # Отправляем напоминание с выбором бонуса
                logger.info(f"📤 Отправка напоминания: user_id={user.id}, level={user.current_loyalty_level}")
                
                success = await send_choose_benefit_push(
                    bot,
                    db,
                    user,
                    user.current_loyalty_level,
                    is_reminder=True  # Помечаем как напоминание
                )
                
                if success:
                    stats['reminders_sent'] += 1
                    logger.info(f"✅ Напоминание отправлено: user_id={user.id}, level={user.current_loyalty_level}")
                else:
                    stats['errors'] += 1
                    logger.error(f"❌ Ошибка отправки напоминания: user_id={user.id}")
                    
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"❌ Ошибка при обработке user_id={user.id}: {e}", exc_info=True)
        
        logger.info(f"📊 Статистика напоминаний: отправлено {stats['reminders_sent']}, ошибок {stats['errors']}")
        return stats
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в send_loyalty_reminders: {e}", exc_info=True)
        stats['errors'] += 1
        return stats

