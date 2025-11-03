"""
Модуль для работы с уровнями лояльности и подсчёта стажа
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from database.models import User, LoyaltyEvent

logger = logging.getLogger(__name__)

# Пороги стажа в днях
SILVER_THRESHOLD = 90
GOLD_THRESHOLD = 180
PLATINUM_THRESHOLD = 365

# Уровни лояльности
LOYALTY_LEVELS = ['none', 'silver', 'gold', 'platinum']
LoyaltyLevel = Literal['none', 'silver', 'gold', 'platinum']


def calc_tenure_days(user: User) -> int:
    """
    Вычисляет стаж пользователя в днях (continuous режим).
    
    Args:
        user: Объект пользователя
        
    Returns:
        Количество дней стажа
    """
    if not user.first_payment_date:
        # Если нет даты первой оплаты, стаж = 0
        return 0
    
    now = datetime.now()
    first_date = user.first_payment_date
    
    # Если дата с timezone, приводим к naive datetime для корректного сравнения
    if first_date.tzinfo is not None:
        first_date = first_date.replace(tzinfo=None)
    
    tenure = (now - first_date).days
    
    return max(0, tenure)  # Не может быть отрицательным


def level_for_days(days: int) -> LoyaltyLevel:
    """
    Определяет уровень лояльности по количеству дней стажа.
    
    Args:
        days: Количество дней стажа
        
    Returns:
        Уровень лояльности: 'none', 'silver', 'gold', 'platinum'
    """
    if days >= PLATINUM_THRESHOLD:
        return 'platinum'
    elif days >= GOLD_THRESHOLD:
        return 'gold'
    elif days >= SILVER_THRESHOLD:
        return 'silver'
    else:
        return 'none'


async def upgrade_level_if_needed(db: AsyncSession, user: User) -> Optional[LoyaltyLevel]:
    """
    Проверяет, нужно ли повысить уровень лояльности пользователя.
    Если новый уровень достигнут и он выше текущего, обновляет уровень,
    устанавливает флаг pending_loyalty_reward и записывает событие.
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        
    Returns:
        Новый уровень, если произошло повышение, иначе None
    """
    try:
        # Вычисляем текущий стаж
        tenure_days = calc_tenure_days(user)
        
        # Определяем уровень на основе стажа
        new_level = level_for_days(tenure_days)
        
        # Получаем текущий уровень пользователя
        current_level = user.current_loyalty_level or 'none'
        
        # Определяем порядок уровней для сравнения
        level_order = {'none': 0, 'silver': 1, 'gold': 2, 'platinum': 3}
        current_order = level_order.get(current_level, 0)
        new_order = level_order.get(new_level, 0)
        
        # Если новый уровень выше текущего, повышаем
        if new_order > current_order:
            logger.info(
                f"Повышение уровня лояльности для user_id={user.id}: "
                f"{current_level} -> {new_level} (стаж: {tenure_days} дней)"
            )
            
            # Обновляем уровень и устанавливаем флаг ожидания награды
            update_query = (
                update(User)
                .where(User.id == user.id)
                .values(
                    current_loyalty_level=new_level,
                    pending_loyalty_reward=True
                )
            )
            await db.execute(update_query)
            await db.commit()
            
            # Обновляем объект пользователя
            await db.refresh(user)
            
            # Записываем событие повышения уровня
            event = LoyaltyEvent(
                user_id=user.id,
                kind='level_up',
                level=new_level,
                payload=f'{{"tenure_days": {tenure_days}, "old_level": "{current_level}"}}'
            )
            db.add(event)
            await db.commit()
            
            logger.info(f"✅ Уровень лояльности обновлён для user_id={user.id}: {new_level}")
            
            return new_level
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке повышения уровня для user_id={user.id}: {e}", exc_info=True)
        await db.rollback()
        return None

