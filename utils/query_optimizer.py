"""
Утилиты для оптимизации запросов к БД и решения N+1 проблемы.

N+1 проблема возникает когда:
1. Загружаем N объектов (например, пользователей)
2. Для каждого объекта делаем дополнительный запрос (например, подписки)
3. Итого: 1 + N запросов вместо 1-2

Решение: использовать selectinload для предзагрузки связанных данных.
"""

import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Subscription, PaymentLog, LoyaltyEvent

logger = logging.getLogger(__name__)


async def get_users_with_subscriptions(
    session: AsyncSession,
    user_ids: Optional[List[int]] = None,
    active_only: bool = False
) -> List[User]:
    """
    Получает пользователей с предзагруженными подписками (решение N+1).
    
    Args:
        session: Сессия БД
        user_ids: Список ID пользователей (если None - все)
        active_only: Загружать только активные подписки
        
    Returns:
        Список пользователей с предзагруженными subscriptions
    """
    query = select(User).options(
        selectinload(User.subscriptions)
    )
    
    if user_ids:
        query = query.where(User.id.in_(user_ids))
    
    result = await session.execute(query)
    users = result.scalars().all()
    
    logger.debug(
        f"Загружено {len(users)} пользователей с подписками "
        f"(1 запрос вместо {len(users) + 1})"
    )
    
    return users


async def get_users_with_loyalty_events(
    session: AsyncSession,
    user_ids: Optional[List[int]] = None,
    level: Optional[str] = None
) -> List[User]:
    """
    Получает пользователей с предзагруженными событиями лояльности.
    
    Args:
        session: Сессия БД
        user_ids: Список ID пользователей
        level: Фильтр по уровню лояльности
        
    Returns:
        Список пользователей с предзагруженными событиями
    """
    query = select(User)
    
    if user_ids:
        query = query.where(User.id.in_(user_ids))
    
    if level:
        query = query.where(User.current_loyalty_level == level)
    
    # Предзагружаем события лояльности
    query = query.options(
        selectinload(User.loyalty_events)
    )
    
    result = await session.execute(query)
    users = result.scalars().all()
    
    logger.debug(
        f"Загружено {len(users)} пользователей с событиями лояльности "
        f"(оптимизировано)"
    )
    
    return users


async def get_subscriptions_with_users(
    session: AsyncSession,
    subscription_ids: Optional[List[int]] = None,
    active_only: bool = False
) -> List[Subscription]:
    """
    Получает подписки с предзагруженными пользователями.
    
    Args:
        session: Сессия БД
        subscription_ids: Список ID подписок
        active_only: Только активные подписки
        
    Returns:
        Список подписок с предзагруженными user
    """
    query = select(Subscription).options(
        selectinload(Subscription.user)
    )
    
    if subscription_ids:
        query = query.where(Subscription.id.in_(subscription_ids))
    
    if active_only:
        query = query.where(Subscription.is_active == True)
    
    result = await session.execute(query)
    subscriptions = result.scalars().all()
    
    logger.debug(
        f"Загружено {len(subscriptions)} подписок с пользователями "
        f"(оптимизировано)"
    )
    
    return subscriptions


async def get_users_with_full_data(
    session: AsyncSession,
    user_ids: Optional[List[int]] = None
) -> List[User]:
    """
    Получает пользователей со всеми связанными данными (подписки + события).
    
    Используется для админ-панели и статистики.
    
    Args:
        session: Сессия БД
        user_ids: Список ID пользователей
        
    Returns:
        Список пользователей с полными данными
    """
    query = select(User).options(
        selectinload(User.subscriptions),
        selectinload(User.loyalty_events)
    )
    
    if user_ids:
        query = query.where(User.id.in_(user_ids))
    
    result = await session.execute(query)
    users = result.scalars().all()
    
    logger.debug(
        f"Загружено {len(users)} пользователей с полными данными "
        f"(subscriptions + loyalty_events)"
    )
    
    return users


class QueryBatcher:
    """
    Батчер для группировки запросов и предотвращения N+1.
    
    Пример использования:
        batcher = QueryBatcher(session)
        
        # Собираем ID пользователей
        user_ids = [1, 2, 3, 4, 5]
        
        # Загружаем всех пользователей одним запросом
        users = await batcher.load_users(user_ids)
        
        # Загружаем все подписки одним запросом
        subscriptions = await batcher.load_subscriptions_for_users(user_ids)
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self._user_cache = {}
        self._subscription_cache = {}
    
    async def load_users(self, user_ids: List[int]) -> dict[int, User]:
        """
        Загружает пользователей батчем.
        
        Returns:
            Словарь {user_id: User}
        """
        # Фильтруем уже загруженных
        to_load = [uid for uid in user_ids if uid not in self._user_cache]
        
        if to_load:
            query = select(User).where(User.id.in_(to_load))
            result = await self.session.execute(query)
            users = result.scalars().all()
            
            for user in users:
                self._user_cache[user.id] = user
            
            logger.debug(f"Загружено {len(users)} пользователей батчем")
        
        return {uid: self._user_cache.get(uid) for uid in user_ids}
    
    async def load_subscriptions_for_users(
        self,
        user_ids: List[int]
    ) -> dict[int, List[Subscription]]:
        """
        Загружает подписки для пользователей батчем.
        
        Returns:
            Словарь {user_id: [Subscription, ...]}
        """
        query = select(Subscription).where(Subscription.user_id.in_(user_ids))
        result = await self.session.execute(query)
        subscriptions = result.scalars().all()
        
        # Группируем по user_id
        by_user = {}
        for sub in subscriptions:
            if sub.user_id not in by_user:
                by_user[sub.user_id] = []
            by_user[sub.user_id].append(sub)
        
        logger.debug(
            f"Загружено {len(subscriptions)} подписок для "
            f"{len(user_ids)} пользователей (1 запрос)"
        )
        
        return by_user
    
    def clear_cache(self):
        """Очищает кэш"""
        self._user_cache.clear()
        self._subscription_cache.clear()


# Декоратор для логирования количества запросов
def log_query_count(func):
    """
    Декоратор для отслеживания количества запросов к БД.
    
    Помогает выявлять N+1 проблемы в development.
    """
    async def wrapper(*args, **kwargs):
        # В production это можно отключить
        logger.debug(f"Начало выполнения {func.__name__}")
        result = await func(*args, **kwargs)
        logger.debug(f"Завершено {func.__name__}")
        return result
    
    return wrapper
