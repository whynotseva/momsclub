"""
Менеджер для graceful shutdown бота.

Обеспечивает корректное завершение всех задач при остановке бота.
"""

import asyncio
import signal
import logging
from typing import Set, Callable, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ShutdownManager:
    """
    Менеджер graceful shutdown.
    
    Функции:
    - Отслеживает все активные задачи
    - При получении SIGTERM/SIGINT останавливает прием новых запросов
    - Дает время на завершение текущих задач (по умолчанию 30 сек)
    - Сохраняет состояние незавершенных операций
    - Корректно закрывает соединения
    """
    
    def __init__(self, grace_period: int = 30):
        """
        Args:
            grace_period: Время в секундах для завершения задач
        """
        self.grace_period = grace_period
        self.is_shutting_down = False
        self.shutdown_initiated_at: Optional[datetime] = None
        
        # Отслеживаемые задачи
        self.active_tasks: Set[asyncio.Task] = set()
        self.background_tasks: Set[asyncio.Task] = set()
        
        # Callback функции для cleanup
        self.cleanup_callbacks: list[Callable] = []
        
        # Статистика
        self.stats = {
            'tasks_completed': 0,
            'tasks_cancelled': 0,
            'tasks_timeout': 0
        }
        
        logger.info("✅ ShutdownManager инициализирован")
    
    def register_task(self, task: asyncio.Task, is_background: bool = False):
        """
        Регистрирует задачу для отслеживания.
        
        Args:
            task: Asyncio задача
            is_background: True для фоновых задач (крон-джобы)
        """
        if is_background:
            self.background_tasks.add(task)
            logger.debug(f"Зарегистрирована фоновая задача: {task.get_name()}")
        else:
            self.active_tasks.add(task)
            logger.debug(f"Зарегистрирована активная задача: {task.get_name()}")
        
        # Автоматически удаляем задачу после завершения
        task.add_done_callback(lambda t: self._task_done(t, is_background))
    
    def _task_done(self, task: asyncio.Task, is_background: bool):
        """Callback при завершении задачи"""
        task_set = self.background_tasks if is_background else self.active_tasks
        task_set.discard(task)
        
        if not task.cancelled():
            self.stats['tasks_completed'] += 1
            logger.debug(f"Задача завершена: {task.get_name()}")
    
    def register_cleanup_callback(self, callback: Callable):
        """
        Регистрирует callback для cleanup при shutdown.
        
        Args:
            callback: Async функция для вызова при shutdown
        """
        self.cleanup_callbacks.append(callback)
        logger.debug(f"Зарегистрирован cleanup callback: {callback.__name__}")
    
    def should_accept_requests(self) -> bool:
        """
        Проверяет, можно ли принимать новые запросы.
        
        Returns:
            False если идет shutdown
        """
        return not self.is_shutting_down
    
    async def initiate_shutdown(self, signal_name: str = "UNKNOWN"):
        """
        Инициирует graceful shutdown.
        
        Args:
            signal_name: Имя сигнала (SIGTERM, SIGINT, etc.)
        """
        if self.is_shutting_down:
            logger.warning("⚠️  Shutdown уже в процессе")
            return
        
        self.is_shutting_down = True
        self.shutdown_initiated_at = datetime.now()
        
        logger.info("=" * 80)
        logger.info(f"🛑 ПОЛУЧЕН СИГНАЛ {signal_name} - НАЧАЛО GRACEFUL SHUTDOWN")
        logger.info(f"⏱️  Grace period: {self.grace_period} секунд")
        logger.info(f"📊 Активных задач: {len(self.active_tasks)}")
        logger.info(f"📊 Фоновых задач: {len(self.background_tasks)}")
        logger.info("=" * 80)
        
        # Шаг 1: Останавливаем фоновые задачи (крон-джобы)
        logger.info("🔴 Шаг 1: Остановка фоновых задач...")
        await self._cancel_background_tasks()
        
        # Шаг 2: Ждем завершения активных задач
        logger.info(f"⏳ Шаг 2: Ожидание завершения активных задач ({self.grace_period}с)...")
        await self._wait_for_active_tasks()
        
        # Шаг 3: Выполняем cleanup callbacks
        logger.info("🧹 Шаг 3: Выполнение cleanup callbacks...")
        await self._run_cleanup_callbacks()
        
        # Шаг 4: Финальная статистика
        logger.info("=" * 80)
        logger.info("📊 СТАТИСТИКА SHUTDOWN")
        logger.info(f"✅ Завершено задач: {self.stats['tasks_completed']}")
        logger.info(f"❌ Отменено задач: {self.stats['tasks_cancelled']}")
        logger.info(f"⏱️  Timeout задач: {self.stats['tasks_timeout']}")
        logger.info("=" * 80)
        logger.info("✅ GRACEFUL SHUTDOWN ЗАВЕРШЕН")
        logger.info("=" * 80)
    
    async def _cancel_background_tasks(self):
        """Отменяет все фоновые задачи"""
        if not self.background_tasks:
            logger.info("   ℹ️  Нет фоновых задач для остановки")
            return
        
        logger.info(f"   🔴 Отмена {len(self.background_tasks)} фоновых задач...")
        
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
                logger.debug(f"   Отменена фоновая задача: {task.get_name()}")
        
        # Ждем отмены всех фоновых задач (максимум 5 секунд)
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.background_tasks, return_exceptions=True),
                timeout=5.0
            )
            logger.info("   ✅ Все фоновые задачи остановлены")
        except asyncio.TimeoutError:
            logger.warning("   ⚠️  Timeout при остановке фоновых задач")
        
        self.stats['tasks_cancelled'] += len(self.background_tasks)
        self.background_tasks.clear()
    
    async def _wait_for_active_tasks(self):
        """Ждет завершения активных задач"""
        if not self.active_tasks:
            logger.info("   ℹ️  Нет активных задач")
            return
        
        logger.info(f"   ⏳ Ожидание {len(self.active_tasks)} активных задач...")
        
        try:
            # Ждем завершения всех активных задач
            await asyncio.wait_for(
                asyncio.gather(*self.active_tasks, return_exceptions=True),
                timeout=self.grace_period
            )
            logger.info("   ✅ Все активные задачи завершены")
            
        except asyncio.TimeoutError:
            # Timeout - отменяем оставшиеся задачи
            remaining = len([t for t in self.active_tasks if not t.done()])
            logger.warning(f"   ⏱️  Timeout! Осталось {remaining} незавершенных задач")
            
            timeout_count = 0
            for task in self.active_tasks:
                if not task.done():
                    task.cancel()
                    timeout_count += 1
                    logger.warning(f"   ❌ Принудительно отменена: {task.get_name()}")
            
            self.stats['tasks_timeout'] = timeout_count
            
            # Даем еще 2 секунды на отмену
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.active_tasks, return_exceptions=True),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.error("   ❌ Не удалось отменить все задачи")
        
        self.active_tasks.clear()
    
    async def _run_cleanup_callbacks(self):
        """Выполняет все cleanup callbacks"""
        if not self.cleanup_callbacks:
            logger.info("   ℹ️  Нет cleanup callbacks")
            return
        
        logger.info(f"   🧹 Выполнение {len(self.cleanup_callbacks)} cleanup callbacks...")
        
        for callback in self.cleanup_callbacks:
            try:
                logger.debug(f"   Выполнение: {callback.__name__}")
                await callback()
                logger.debug(f"   ✅ Завершен: {callback.__name__}")
            except Exception as e:
                logger.error(f"   ❌ Ошибка в {callback.__name__}: {e}", exc_info=True)
        
        logger.info("   ✅ Все cleanup callbacks выполнены")


# Глобальный экземпляр менеджера
_shutdown_manager: Optional[ShutdownManager] = None


def get_shutdown_manager(grace_period: int = 30) -> ShutdownManager:
    """
    Получает глобальный экземпляр ShutdownManager.
    
    Args:
        grace_period: Время для завершения задач (только при первом вызове)
        
    Returns:
        ShutdownManager
    """
    global _shutdown_manager
    
    if _shutdown_manager is None:
        _shutdown_manager = ShutdownManager(grace_period=grace_period)
    
    return _shutdown_manager


def setup_signal_handlers(shutdown_manager: ShutdownManager):
    """
    Настраивает обработчики сигналов для graceful shutdown.
    
    Args:
        shutdown_manager: Экземпляр ShutdownManager
    """
    loop = asyncio.get_event_loop()
    
    def signal_handler(sig):
        """Обработчик сигнала"""
        signal_name = signal.Signals(sig).name
        logger.info(f"🛑 Получен сигнал {signal_name}")
        
        # Запускаем shutdown в event loop
        asyncio.create_task(shutdown_manager.initiate_shutdown(signal_name))
    
    # Регистрируем обработчики для SIGTERM и SIGINT
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
    
    logger.info("✅ Обработчики сигналов настроены (SIGTERM, SIGINT)")


# Декоратор для автоматической регистрации задач
def tracked_task(is_background: bool = False):
    """
    Декоратор для автоматической регистрации задач в ShutdownManager.
    
    Args:
        is_background: True для фоновых задач
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            manager = get_shutdown_manager()
            
            # Проверяем, можно ли принимать новые запросы
            if not manager.should_accept_requests() and not is_background:
                logger.warning(f"⚠️  Отклонен запрос (shutdown): {func.__name__}")
                return None
            
            # Создаем и регистрируем задачу
            task = asyncio.create_task(func(*args, **kwargs))
            task.set_name(func.__name__)
            manager.register_task(task, is_background=is_background)
            
            return await task
        
        return wrapper
    return decorator
