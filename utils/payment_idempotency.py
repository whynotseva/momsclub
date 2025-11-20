"""
Утилиты для обеспечения идемпотентности платежей.

Гарантирует, что дублирующие webhook от YooKassa не создают дубликаты подписок.
"""

import logging
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import PaymentLog, Subscription

logger = logging.getLogger(__name__)


async def check_payment_idempotency(
    session: AsyncSession,
    transaction_id: str
) -> Tuple[bool, Optional[PaymentLog], Optional[str]]:
    """
    Проверяет идемпотентность платежа с блокировкой строки.
    
    Использует SELECT FOR UPDATE для предотвращения race condition
    при параллельной обработке дублирующих webhook.
    
    Args:
        session: Сессия БД
        transaction_id: ID транзакции от YooKassa
        
    Returns:
        Tuple[should_process, payment_log, skip_reason]:
        - should_process: True если нужно обрабатывать платеж
        - payment_log: Объект PaymentLog (может быть None)
        - skip_reason: Причина пропуска (если should_process=False)
    """
    try:
        # КРИТИЧНО: Блокируем строку платежа для предотвращения race condition
        # Это гарантирует, что только один webhook обработает платеж
        query = select(PaymentLog).where(
            PaymentLog.transaction_id == transaction_id
        ).with_for_update()
        
        result = await session.execute(query)
        payment_log = result.scalar_one_or_none()
        
        if not payment_log:
            # Платеж не найден - нужно создать
            logger.info(f"💳 Платеж {transaction_id} не найден в БД - будет создан")
            return True, None, None
        
        # Платеж найден и заблокирован - проверяем его статус
        
        # Проверка 1: Платеж уже успешно обработан
        if payment_log.status == "success" and payment_log.is_confirmed:
            # Дополнительная проверка: есть ли подписка
            if payment_log.subscription_id:
                logger.info(
                    f"✅ Платеж {transaction_id} уже обработан "
                    f"(subscription_id={payment_log.subscription_id}) - пропускаем"
                )
                return False, payment_log, "already_processed_with_subscription"
            else:
                # Платеж success, но подписки нет - возможно ошибка при обработке
                logger.warning(
                    f"⚠️  Платеж {transaction_id} помечен success, "
                    f"но subscription_id отсутствует - повторная обработка"
                )
                return True, payment_log, None
        
        # Проверка 2: Платеж в процессе обработки (pending)
        if payment_log.status == "pending":
            logger.info(
                f"🔄 Платеж {transaction_id} в статусе pending - "
                f"продолжаем обработку"
            )
            return True, payment_log, None
        
        # Проверка 3: Платеж отменен или failed
        if payment_log.status in ["failed", "canceled"]:
            logger.warning(
                f"❌ Платеж {transaction_id} в статусе {payment_log.status} - "
                f"пропускаем"
            )
            return False, payment_log, f"payment_status_{payment_log.status}"
        
        # Неизвестный статус - обрабатываем на всякий случай
        logger.warning(
            f"⚠️  Платеж {transaction_id} в неизвестном статусе "
            f"{payment_log.status} - обрабатываем"
        )
        return True, payment_log, None
        
    except Exception as e:
        logger.error(
            f"❌ Ошибка проверки идемпотентности для {transaction_id}: {e}",
            exc_info=True
        )
        # При ошибке не обрабатываем - безопаснее
        return False, None, "error_during_check"


async def verify_subscription_created(
    session: AsyncSession,
    payment_log: PaymentLog
) -> bool:
    """
    Проверяет, что подписка действительно создана для платежа.
    
    Args:
        session: Сессия БД
        payment_log: Объект PaymentLog
        
    Returns:
        True если подписка существует
    """
    if not payment_log.subscription_id:
        return False
    
    try:
        query = select(Subscription).where(
            Subscription.id == payment_log.subscription_id
        )
        result = await session.execute(query)
        subscription = result.scalar_one_or_none()
        
        if subscription:
            logger.debug(
                f"✅ Подписка {subscription.id} найдена для платежа "
                f"{payment_log.transaction_id}"
            )
            return True
        else:
            logger.warning(
                f"⚠️  Подписка {payment_log.subscription_id} не найдена "
                f"для платежа {payment_log.transaction_id}"
            )
            return False
            
    except Exception as e:
        logger.error(
            f"❌ Ошибка проверки подписки для платежа "
            f"{payment_log.transaction_id}: {e}"
        )
        return False


async def mark_payment_processed(
    session: AsyncSession,
    payment_log: PaymentLog,
    subscription_id: int
):
    """
    Помечает платеж как обработанный.
    
    Args:
        session: Сессия БД
        payment_log: Объект PaymentLog
        subscription_id: ID созданной подписки
    """
    payment_log.status = "success"
    payment_log.is_confirmed = True
    payment_log.subscription_id = subscription_id
    
    session.add(payment_log)
    
    logger.info(
        f"✅ Платеж {payment_log.transaction_id} помечен как обработанный "
        f"(subscription_id={subscription_id})"
    )


class PaymentIdempotencyError(Exception):
    """Исключение при нарушении идемпотентности платежа"""
    pass
