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


def get_loyalty_progress(tenure_days: int, current_level: Optional[str]) -> dict:
    """
    Вычисляет прогресс до следующего уровня лояльности.
    
    Args:
        tenure_days: Текущий стаж пользователя в днях
        current_level: Текущий уровень лояльности ('none', 'silver', 'gold', 'platinum')
        
    Returns:
        dict с ключами:
            - current_level: текущий уровень
            - next_level: следующий уровень (или None если максимальный)
            - progress_percent: процент прогресса (0-100)
            - days_current: дни на текущем уровне
            - days_needed: дней до следующего уровня (или 0 если максимальный)
            - progress_bar: визуальный прогресс-бар (строка)
    """
    if current_level is None:
        current_level = level_for_days(tenure_days)
    
    # Определяем пороги
    if current_level == 'none':
        current_threshold = 0
        next_threshold = SILVER_THRESHOLD
        next_level = 'silver'
    elif current_level == 'silver':
        current_threshold = SILVER_THRESHOLD
        next_threshold = GOLD_THRESHOLD
        next_level = 'gold'
    elif current_level == 'gold':
        current_threshold = GOLD_THRESHOLD
        next_threshold = PLATINUM_THRESHOLD
        next_level = 'platinum'
    else:  # platinum - максимальный уровень
        current_threshold = PLATINUM_THRESHOLD
        next_threshold = None
        next_level = None
    
    # Если достигнут максимальный уровень
    if next_level is None:
        return {
            'current_level': current_level,
            'next_level': None,
            'progress_percent': 100,
            'days_current': max(0, tenure_days - current_threshold),
            'days_needed': 0,
            'progress_bar': '████████████████████ 100%'
        }
    
    # Вычисляем прогресс
    days_in_current_level = tenure_days - current_threshold
    days_needed_for_next = next_threshold - tenure_days
    total_days_for_level = next_threshold - current_threshold
    
    if total_days_for_level == 0:
        progress_percent = 100
    else:
        progress_percent = min(100, max(0, int((days_in_current_level / total_days_for_level) * 100)))
    
    # Создаем визуальный прогресс-бар (20 символов)
    filled = int(progress_percent / 5)  # 0-20
    empty = 20 - filled
    progress_bar = '█' * filled + '░' * empty + f' {progress_percent}%'
    
    return {
        'current_level': current_level,
        'next_level': next_level,
        'progress_percent': progress_percent,
        'days_current': days_in_current_level,
        'days_needed': max(0, days_needed_for_next),
        'progress_bar': progress_bar
    }


async def calc_tenure_days(db: AsyncSession, user: User) -> int:
    """
    Вычисляет стаж пользователя в днях на основе периодов активных подписок.
    Стаж считается только за периоды, когда подписка была активна (от start_date до end_date).
    Перерывы в подписке не учитываются в стаже.
    
    Args:
        db: Сессия БД для получения подписок
        user: Объект пользователя
        
    Returns:
        Количество дней стажа (сумма дней всех активных периодов подписок)
    """
    if not user.first_payment_date:
        # Если нет даты первой оплаты, стаж = 0
        return 0
    
    from database.models import Subscription
    
    # Получаем все подписки пользователя с успешными платежами
    # Подписки создаются только при успешных платежах, поэтому получаем все
    query = select(Subscription).where(
        Subscription.user_id == user.id
    ).order_by(Subscription.start_date)
    
    result = await db.execute(query)
    subscriptions = result.scalars().all()
    
    if not subscriptions:
        return 0
    
    now = datetime.now()
    
    # Собираем все периоды подписок
    periods = []
    for sub in subscriptions:
        start = sub.start_date
        end = sub.end_date
        
        # Если даты с timezone, приводим к naive datetime
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if end.tzinfo is not None:
            end = end.replace(tzinfo=None)
        
        # Стаж считается только за реально оплаченные периоды
        # Если end_date в будущем, считаем только до текущего момента (стаж не растёт без активной подписки)
        # Если end_date в прошлом, считаем весь период до end_date
        # Это гарантирует, что стаж останавливается при истечении подписки
        end_date_for_calc = min(end, now)
        
        # Добавляем период только если он имеет смысл (start <= end)
        # И только если период начался (start <= now)
        if start <= end_date_for_calc and start <= now:
            periods.append((start, end_date_for_calc))
    
    if not periods:
        return 0
    
    # Сортируем периоды по началу
    periods.sort(key=lambda x: x[0])
    
    # Объединяем перекрывающиеся периоды
    merged_periods = []
    current_start, current_end = periods[0]
    
    for start, end in periods[1:]:
        # Если текущий период перекрывается или граничит со следующим, объединяем
        if start <= current_end:
            # Объединяем: расширяем текущий период до максимального end
            current_end = max(current_end, end)
        else:
            # Периоды не перекрываются, сохраняем текущий и начинаем новый
            merged_periods.append((current_start, current_end))
            current_start, current_end = start, end
    
    # Добавляем последний период
    merged_periods.append((current_start, current_end))
    
    # Суммируем дни всех периодов
    total_days = 0
    for start, end in merged_periods:
        days = (end - start).days
        total_days += max(0, days)  # Защита от отрицательных значений
    
    return total_days


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
        # Вычисляем текущий стаж (только по периодам активных подписок)
        tenure_days = await calc_tenure_days(db, user)
        
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

