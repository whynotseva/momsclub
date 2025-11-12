"""
Middleware для автоматической синхронизации данных пользователей
Обновляет username, first_name, last_name при каждом взаимодействии с ботом
"""
import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id, sync_user_data

logger = logging.getLogger(__name__)


class UserSyncMiddleware(BaseMiddleware):
    """
    Middleware для синхронизации данных пользователя с Telegram.
    Обновляет username, first_name, last_name при каждом взаимодействии.
    
    БЕЗОПАСНО:
    - Только обновляет имя/username, НЕ затрагивает подписки
    - НЕ создает новых пользователей (только обновляет существующих)
    - НЕ меняет флаги платежей (is_first_payment_done, first_payment_date и т.д.)
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Синхронизирует данные пользователя перед обработкой события
        
        Args:
            handler: Следующий обработчик в цепочке
            event: Событие (Message или CallbackQuery)
            data: Данные контекста
        """
        # Получаем пользователя из события
        user_tg = None
        
        if isinstance(event, Message):
            user_tg = event.from_user
        elif isinstance(event, CallbackQuery):
            user_tg = event.from_user
        
        # Если есть информация о пользователе Telegram, синхронизируем
        if user_tg and user_tg.id:
            try:
                async with AsyncSessionLocal() as session:
                    # Ищем пользователя в БД
                    user = await get_user_by_telegram_id(session, user_tg.id)
                    
                    if user:
                        # Синхронизируем только базовые данные (НЕ трогаем подписки, платежи, лояльность)
                        await sync_user_data(
                            session,
                            user,
                            username=user_tg.username,
                            first_name=user_tg.first_name,
                            last_name=user_tg.last_name
                        )
                        logger.debug(f"Синхронизированы данные пользователя {user_tg.id}")
                    else:
                        # Пользователь не найден — это нормально для /start
                        # get_or_create_user создаст его в обработчике
                        logger.debug(f"Пользователь {user_tg.id} не найден в БД (будет создан при /start)")
                        
            except Exception as e:
                # Логируем ошибку, но НЕ прерываем обработку события
                logger.error(f"Ошибка синхронизации данных пользователя {user_tg.id}: {e}")
                # Продолжаем выполнение, даже если синхронизация не удалась
        
        # Вызываем следующий обработчик в цепочке
        return await handler(event, data)

