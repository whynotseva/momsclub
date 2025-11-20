"""
Модуль для защиты от спама и DoS атак через rate limiting.
"""

import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, Awaitable, Optional, List
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)


class RateLimitConfig:
    """Конфигурация лимитов для разных типов запросов"""
    # МЯГКИЕ ЛИМИТЫ - только защита от DoS атак
    GENERAL_LIMIT = 50      # Было 10 - увеличено для комфорта
    GENERAL_WINDOW = 60
    PAYMENT_LIMIT = 10      # Было 3 - увеличено для тестирования
    PAYMENT_WINDOW = 60
    CALLBACK_LIMIT = 50     # Было 15 - увеличено
    CALLBACK_WINDOW = 60
    ADMIN_LIMIT = 100       # Было 30 - админы без ограничений
    ADMIN_WINDOW = 60
    BLOCK_DURATION = 180    # Было 300 (5 мин) - теперь 3 минуты


class UserRequestTracker:
    """Отслеживает запросы пользователей"""
    
    def __init__(self):
        self.requests: Dict[int, List[tuple]] = defaultdict(list)
        self.blocked_users: Dict[int, datetime] = {}
        self.stats = {
            'total_requests': 0,
            'blocked_requests': 0,
            'unique_users': set()
        }
    
    def cleanup_old_requests(self, user_id: int, window_seconds: int):
        """Удаляет запросы старше окна времени"""
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_seconds)
        
        if user_id in self.requests:
            self.requests[user_id] = [
                (ts, req_type) for ts, req_type in self.requests[user_id]
                if ts > cutoff
            ]
            if not self.requests[user_id]:
                del self.requests[user_id]
    
    def is_user_blocked(self, user_id: int) -> bool:
        """Проверяет, заблокирован ли пользователь"""
        if user_id in self.blocked_users:
            if datetime.now() < self.blocked_users[user_id]:
                return True
            else:
                del self.blocked_users[user_id]
                logger.info(f"Разблокирован user_id={user_id}")
        return False
    
    def block_user(self, user_id: int, duration_seconds: int):
        """Блокирует пользователя на указанное время"""
        block_until = datetime.now() + timedelta(seconds=duration_seconds)
        self.blocked_users[user_id] = block_until
        logger.warning(f"Заблокирован user_id={user_id} до {block_until.strftime('%H:%M:%S')}")
    
    def add_request(self, user_id: int, request_type: str = 'general'):
        """Добавляет запрос пользователя"""
        now = datetime.now()
        self.requests[user_id].append((now, request_type))
        self.stats['total_requests'] += 1
        self.stats['unique_users'].add(user_id)
    
    def count_requests(self, user_id: int, window_seconds: int, 
                      request_type: Optional[str] = None) -> int:
        """Подсчитывает количество запросов в окне времени"""
        self.cleanup_old_requests(user_id, window_seconds)
        
        if user_id not in self.requests:
            return 0
        
        if request_type:
            return sum(1 for _, rtype in self.requests[user_id] if rtype == request_type)
        else:
            return len(self.requests[user_id])
    
    def get_stats(self) -> dict:
        """Возвращает статистику"""
        return {
            'total_requests': self.stats['total_requests'],
            'blocked_requests': self.stats['blocked_requests'],
            'unique_users': len(self.stats['unique_users']),
            'currently_blocked': len(self.blocked_users),
            'active_users': len(self.requests)
        }


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для ограничения частоты запросов от пользователей"""
    
    def __init__(self, admin_ids: Optional[List[int]] = None):
        super().__init__()
        self.tracker = UserRequestTracker()
        self.admin_ids = admin_ids or []
        self.config = RateLimitConfig()
        logger.info("Rate Limiting Middleware инициализирован")
    
    def _get_request_type(self, event: TelegramObject) -> str:
        """Определяет тип запроса для выбора лимита"""
        if isinstance(event, Message):
            text = event.text or ""
            if any(keyword in text.lower() for keyword in ['subscribe', 'payment', 'pay']):
                return 'payment'
            if text.startswith('/admin') or text.startswith('/export'):
                return 'admin'
            return 'general'
        elif isinstance(event, CallbackQuery):
            data = event.data or ""
            if any(keyword in data for keyword in ['payment_', 'subscribe', 'pay_']):
                return 'payment'
            if data.startswith('admin_'):
                return 'admin'
            return 'callback'
        return 'general'
    
    def _get_limits(self, request_type: str, is_admin: bool) -> tuple:
        """Возвращает (лимит, окно) для типа запроса"""
        if is_admin:
            return self.config.ADMIN_LIMIT, self.config.ADMIN_WINDOW
        if request_type == 'payment':
            return self.config.PAYMENT_LIMIT, self.config.PAYMENT_WINDOW
        elif request_type == 'callback':
            return self.config.CALLBACK_LIMIT, self.config.CALLBACK_WINDOW
        else:
            return self.config.GENERAL_LIMIT, self.config.GENERAL_WINDOW
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """Обработка запроса с проверкой лимитов"""
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        
        if not user:
            return await handler(event, data)
        
        user_id = user.id
        is_admin = user_id in self.admin_ids
        
        if self.tracker.is_user_blocked(user_id):
            self.tracker.stats['blocked_requests'] += 1
            block_until = self.tracker.blocked_users[user_id]
            remaining = int((block_until - datetime.now()).total_seconds())
            
            if isinstance(event, Message):
                try:
                    await event.reply(
                        f"⏸ Подожди немного ({remaining} сек.) - бот обрабатывает запросы 🤍"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки сообщения о блокировке: {e}")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer(
                        f"⏸ Подожди {remaining} сек. 🤍",
                        show_alert=False
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки callback о блокировке: {e}")
            return
        
        request_type = self._get_request_type(event)
        limit, window = self._get_limits(request_type, is_admin)
        
        current_count = self.tracker.count_requests(user_id, window, request_type)
        
        if current_count >= limit:
            self.tracker.block_user(user_id, self.config.BLOCK_DURATION)
            self.tracker.stats['blocked_requests'] += 1
            
            if isinstance(event, Message):
                try:
                    await event.reply(
                        "⏸ Слишком быстро! Подожди 3 минуты, бот немного отдохнёт 🤍"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки сообщения о превышении лимита: {e}")
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer(
                        "⏸ Подожди 3 мин. 🤍",
                        show_alert=False
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки callback о превышении лимита: {e}")
            return
        
        self.tracker.add_request(user_id, request_type)
        return await handler(event, data)
