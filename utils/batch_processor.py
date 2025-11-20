"""
Утилита для batch-обработки с savepoints.

Обрабатывает большие объемы данных батчами с возможностью отката
только проблемного батча, а не всей операции.
"""

import logging
from typing import List, Callable, Any, Optional, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

T = TypeVar('T')


class BatchProcessor:
    """
    Процессор для batch-обработки с savepoints.
    
    Преимущества:
    - Обрабатывает данные батчами (по умолчанию 50 элементов)
    - При ошибке откатывает только текущий батч
    - Продолжает обработку следующих батчей
    - Собирает статистику по успешным/неуспешным операциям
    """
    
    def __init__(self, batch_size: int = 50):
        """
        Args:
            batch_size: Размер батча (количество элементов)
        """
        self.batch_size = batch_size
        self.stats = {
            'total': 0,
            'processed': 0,
            'failed': 0,
            'batches_total': 0,
            'batches_success': 0,
            'batches_failed': 0,
            'errors': []
        }
    
    async def process_batch(
        self,
        session: AsyncSession,
        items: List[T],
        processor_func: Callable[[AsyncSession, T], Any],
        batch_name: str = "batch"
    ) -> dict:
        """
        Обрабатывает список элементов батчами с savepoints.
        
        Args:
            session: Сессия БД
            items: Список элементов для обработки
            processor_func: Async функция обработки одного элемента
            batch_name: Имя батча для логирования
            
        Returns:
            Словарь со статистикой обработки
        """
        self.stats['total'] = len(items)
        
        # Разбиваем на батчи
        batches = [items[i:i + self.batch_size] for i in range(0, len(items), self.batch_size)]
        self.stats['batches_total'] = len(batches)
        
        logger.info(
            f"🔄 Начало batch-обработки: {len(items)} элементов, "
            f"{len(batches)} батчей по {self.batch_size}"
        )
        
        for batch_idx, batch in enumerate(batches, 1):
            batch_id = f"{batch_name}_{batch_idx}"
            
            try:
                # Создаем savepoint для батча
                async with session.begin_nested() as savepoint:
                    logger.debug(f"📦 Обработка батча {batch_idx}/{len(batches)} ({len(batch)} элементов)")
                    
                    batch_errors = 0
                    
                    for item in batch:
                        try:
                            await processor_func(session, item)
                            self.stats['processed'] += 1
                        except Exception as item_error:
                            batch_errors += 1
                            self.stats['failed'] += 1
                            self.stats['errors'].append({
                                'batch': batch_id,
                                'item': str(item),
                                'error': str(item_error)
                            })
                            logger.error(
                                f"❌ Ошибка обработки элемента в батче {batch_id}: {item_error}",
                                exc_info=True
                            )
                    
                    # Коммитим savepoint если батч обработан
                    await savepoint.commit()
                    self.stats['batches_success'] += 1
                    
                    logger.info(
                        f"✅ Батч {batch_idx}/{len(batches)} обработан: "
                        f"{len(batch) - batch_errors}/{len(batch)} успешно"
                    )
                    
            except Exception as batch_error:
                # Откатываем только текущий батч
                self.stats['batches_failed'] += 1
                self.stats['failed'] += len(batch)
                
                logger.error(
                    f"❌ Ошибка обработки батча {batch_idx}/{len(batches)}: {batch_error}",
                    exc_info=True
                )
                
                # Откат savepoint происходит автоматически
                continue
        
        # Финальный commit всех успешных батчей
        try:
            await session.commit()
            logger.info("✅ Все успешные батчи закоммичены")
        except Exception as commit_error:
            logger.error(f"❌ Ошибка финального commit: {commit_error}")
            await session.rollback()
        
        # Логируем итоговую статистику
        logger.info(
            f"📊 Итоги batch-обработки:\n"
            f"  Всего элементов: {self.stats['total']}\n"
            f"  Обработано успешно: {self.stats['processed']}\n"
            f"  Ошибок: {self.stats['failed']}\n"
            f"  Батчей успешно: {self.stats['batches_success']}/{self.stats['batches_total']}\n"
            f"  Батчей с ошибками: {self.stats['batches_failed']}/{self.stats['batches_total']}"
        )
        
        return self.stats.copy()


async def process_users_in_batches(
    session: AsyncSession,
    users: List[Any],
    processor_func: Callable[[AsyncSession, Any], Any],
    batch_size: int = 50,
    operation_name: str = "users"
) -> dict:
    """
    Удобная функция для обработки пользователей батчами.
    
    Args:
        session: Сессия БД
        users: Список пользователей
        processor_func: Функция обработки одного пользователя
        batch_size: Размер батча
        operation_name: Название операции для логов
        
    Returns:
        Статистика обработки
    """
    processor = BatchProcessor(batch_size=batch_size)
    return await processor.process_batch(
        session=session,
        items=users,
        processor_func=processor_func,
        batch_name=operation_name
    )
