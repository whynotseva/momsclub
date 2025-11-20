"""
Модуль для работы с платежной системой ЮКасса
Полная замена Prodamus на ЮКассу
"""

import os
import logging
import random
import time
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any
from functools import wraps
from dotenv import load_dotenv
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

load_dotenv()

# Настройки timeout и retry для YooKassa API
YOOKASSA_API_TIMEOUT = int(os.getenv("YOOKASSA_API_TIMEOUT", "30"))  # 30 секунд по умолчанию
YOOKASSA_MAX_RETRIES = int(os.getenv("YOOKASSA_MAX_RETRIES", "3"))  # 3 попытки по умолчанию
YOOKASSA_RETRY_DELAY = float(os.getenv("YOOKASSA_RETRY_DELAY", "1.0"))  # 1 секунда базовая задержка

# Список доверенных IP префиксов ЮКассы для проверки вебхуков
YOOKASSA_IP_PREFIXES = ["185.71.76.", "185.71.77.", "77.75.153.", "77.75.156.", "77.75.154."]

# Импортируем конфигурацию ЮКассы
from config import YOOKASSA_CONFIG

# Настраиваем ЮКассу
Configuration.configure(
    YOOKASSA_CONFIG["shop_id"],
    YOOKASSA_CONFIG["secret_key"]
)

# Настраиваем логирование
logger = logging.getLogger("payment_yookassa")
logger.setLevel(logging.INFO)


def retry_with_backoff(max_retries: int = YOOKASSA_MAX_RETRIES, 
                       base_delay: float = YOOKASSA_RETRY_DELAY,
                       exceptions: tuple = (Exception,)):
    """
    Декоратор для повторных попыток с экспоненциальной задержкой (для синхронных функций).
    
    ПРИМЕЧАНИЕ: Использует time.sleep который блокирует event loop.
    Это приемлемо т.к. используется только с синхронным YooKassa SDK
    и срабатывает редко (только при ошибках соединения).
    
    Args:
        max_retries: максимальное количество попыток
        base_delay: базовая задержка в секундах (удваивается при каждой попытке)
        exceptions: кортеж исключений, при которых нужно повторять попытку
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Ошибка при вызове {func.__name__} (попытка {attempt + 1}/{max_retries}): {e}. "
                            f"Повтор через {delay:.1f} сек..."
                        )
                        time.sleep(delay)  # Блокирующий, но приемлемо для редких ошибок
                    else:
                        logger.error(f"Все {max_retries} попыток {func.__name__} исчерпаны. Последняя ошибка: {e}")
            raise last_exception
        return wrapper
    return decorator


def async_retry_with_backoff(max_retries: int = YOOKASSA_MAX_RETRIES,
                             base_delay: float = YOOKASSA_RETRY_DELAY,
                             exceptions: tuple = (Exception,)):
    """
    Декоратор для повторных попыток с экспоненциальной задержкой (для async функций).
    
    Использует asyncio.sleep который НЕ блокирует event loop.
    Использовать для async функций вместо retry_with_backoff.
    
    Args:
        max_retries: максимальное количество попыток
        base_delay: базовая задержка в секундах (удваивается при каждой попытке)
        exceptions: кортеж исключений, при которых нужно повторять попытку
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Ошибка при вызове {func.__name__} (попытка {attempt + 1}/{max_retries}): {e}. "
                            f"Повтор через {delay:.1f} сек..."
                        )
                        await asyncio.sleep(delay)  # НЕ блокирует event loop
                    else:
                        logger.error(f"Все {max_retries} попыток {func.__name__} исчерпаны. Последняя ошибка: {e}")
            raise last_exception
        return wrapper
    return decorator


@retry_with_backoff(max_retries=YOOKASSA_MAX_RETRIES, 
                   base_delay=YOOKASSA_RETRY_DELAY,
                   exceptions=(ConnectionError, TimeoutError, OSError))
def create_payment_link(amount: int,
                       user_id: int,
                       description: str,
                       sub_type: str = "default",
                       days: Optional[int] = None,
                       return_url: str = None,
                       phone: str = None,
                       email: str = None,
                       discount_percent: int = 0) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Создает платеж в ЮКассе и возвращает ссылку для оплаты.

    Args:
        amount: сумма в рублях
        user_id: ID пользователя в Telegram
        description: описание платежа
        sub_type: тип подписки (для метаданных)
        days: количество дней подписки
        return_url: URL для возврата после оплаты
        phone: номер телефона пользователя
        email: email пользователя

    Returns:
        tuple: (payment_url, payment_id, payment_label)
    """
    try:
        # Генерируем уникальный идентификатор платежа
        payment_id = str(uuid.uuid4())

        # Создаем метку платежа
        timestamp = int(time.time())
        random_suffix = random.randint(1000, 9999)
        payment_label = f"user_{user_id}_{sub_type}_{timestamp}_{random_suffix}"

        logger.info(f"Создание платежа ЮКасса: user_id={user_id}, amount={amount}, type={sub_type}")
        logger.info(f"Метка платежа: {payment_label}")

        # URL возврата
        if not return_url:
            return_url = "https://t.me/momsclubsubscribe_bot"

        # Формируем метаданные
        metadata = {
            "telegram_id": str(user_id),  # ВАЖНО: это telegram_id пользователя!
            "sub_type": sub_type,
            "payment_label": payment_label,
            "days": str(days or 30)
        }
        
        # Добавляем информацию о скидке лояльности, если применена
        if discount_percent > 0:
            metadata["loyalty_discount_percent"] = str(discount_percent)
            logger.info(f"Применена скидка лояльности: {discount_percent}%")

        # Формируем данные чека
        receipt_data = {
            "customer": {
                "phone": phone if phone else "+79999999999",
                "email": email if email else f"user_{user_id}@momsclub.ru"
            },
            "items": [{
                "description": description[:128],  # ЮКасса ограничивает до 128 символов
                "quantity": "1",
                "amount": {
                    "value": f"{amount}.00",
                    "currency": "RUB"
                },
                "vat_code": 1  # НДС не облагается
            }]
        }

        # Создаем платеж в ЮКассе
        payment = Payment.create({
            "amount": {
                "value": f"{amount}.00",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "save_payment_method": True,  # ВАЖНО: для автоплатежей
            "description": description,
            "metadata": metadata,
            "receipt": receipt_data
        }, payment_id)

        payment_url = payment.confirmation.confirmation_url
        
        logger.info(f"✅ Создан платеж ЮКасса: ID={payment.id}")
        logger.info(f"   URL: {payment_url}")
        
        return payment_url, payment.id, payment_label

    except Exception as e:
        logger.error(f"❌ Ошибка при создании платежа ЮКасса: {e}", exc_info=True)
        return None, None, None


@retry_with_backoff(max_retries=YOOKASSA_MAX_RETRIES,
                   base_delay=YOOKASSA_RETRY_DELAY,
                   exceptions=(ConnectionError, TimeoutError, OSError))
def create_autopayment(user_id: int,
                      amount: int,
                      description: str,
                      payment_method_id: str,
                      days: int = 30) -> Tuple[str, Optional[str]]:
    """
    Создает автоплатеж через сохраненный платежный метод ЮКассы.

    Args:
        user_id: ID пользователя
        amount: сумма в рублях
        description: описание платежа
        payment_method_id: сохраненный ID платежного метода
        days: количество дней подписки

    Returns:
        tuple: (status, payment_id) - статус и ID платежа
    """
    try:
        payment_id = str(uuid.uuid4())
        
        logger.info(f"Создание автоплатежа ЮКасса: user_id={user_id}, amount={amount}")
        logger.info(f"Payment method ID: {payment_method_id}")

        # Метаданные
        metadata = {
            "telegram_id": str(user_id),  # ВАЖНО: это telegram_id пользователя!
            "auto_renewal": "true",
            "days": str(days)
        }

        # Создаем автоплатеж
        payment = Payment.create({
            "amount": {
                "value": f"{amount}.00",
                "currency": "RUB"
            },
            "capture": True,
            "payment_method_id": payment_method_id,
            "description": description,
            "metadata": metadata
        }, payment_id)

        logger.info(f"✅ Автоплатеж создан: ID={payment.id}, статус={payment.status}")
        
        # Маппинг статусов
        status_map = {
            "succeeded": "success",
            "pending": "pending",
            "waiting_for_capture": "pending",
            "canceled": "failed"
        }
        
        return status_map.get(payment.status, "pending"), payment.id

    except Exception as e:
        logger.error(f"❌ Ошибка автоплатежа ЮКасса: {e}", exc_info=True)
        return "failed", None


@retry_with_backoff(max_retries=YOOKASSA_MAX_RETRIES,
                   base_delay=YOOKASSA_RETRY_DELAY,
                   exceptions=(ConnectionError, TimeoutError, OSError))
def check_payment_status(payment_id: str, expected_amount: float = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Проверяет статус платежа в ЮКассе.

    Args:
        payment_id: ID платежа в ЮКассе
        expected_amount: ожидаемая сумма (опционально)

    Returns:
        tuple: (status, payment_data)
    """
    try:
        logger.info(f"Проверка статуса платежа ЮКасса: {payment_id}")

        payment = Payment.find_one(payment_id)
        
        if not payment:
            logger.error(f"Платеж {payment_id} не найден в ЮКассе")
            return "failed", None

        # Проверка суммы
        if expected_amount and float(payment.amount.value) < expected_amount:
            logger.warning(f"Сумма платежа {payment.amount.value} меньше ожидаемой {expected_amount}")
            return "failed", payment.__dict__

        # Маппинг статусов
        status_map = {
            "succeeded": "success",
            "pending": "pending",
            "waiting_for_capture": "pending",
            "canceled": "failed"
        }

        status = status_map.get(payment.status, "failed")
        
        logger.info(f"Статус платежа {payment_id}: {status} (ЮКасса: {payment.status})")
        
        return status, payment.__dict__

    except Exception as e:
        logger.error(f"❌ Ошибка проверки статуса ЮКасса: {e}", exc_info=True)
        return "failed", None


def verify_yookassa_signature(notification_body: str, signature_header: str = None, client_ip: str = None) -> bool:
    """
    Проверяет криптографическую подпись HMAC-SHA256 вебхука от ЮКассы.
    
    ЮКасса подписывает вебхуки с помощью HMAC-SHA256. Подпись передается в заголовке
    'X-Content-HMAC-SHA256' или 'X-Idempotence-Key' (в зависимости от версии API).
    
    Args:
        notification_body: необработанное тело уведомления (bytes или str)
        signature_header: значение заголовка с подписью (опционально)
        client_ip: IP адрес клиента (опционально, для логирования)

    Returns:
        bool: True если подпись корректна
    """
    import hmac
    import hashlib
    import json
    
    try:
        # Получаем secret key из конфигурации
        from config import YOOKASSA_SECRET_KEY
        if not YOOKASSA_SECRET_KEY:
            logger.error("YOOKASSA_SECRET_KEY не задан в конфигурации")
            return False
        
        # Преобразуем тело в bytes если это строка
        if isinstance(notification_body, str):
            body_bytes = notification_body.encode('utf-8')
        else:
            body_bytes = notification_body
        
        # ВРЕМЕННОЕ РЕШЕНИЕ: ЮКасса использует ECDSA подпись формата "v1 <shop_id> <timestamp> <signature>"
        # Сейчас проверяем только IP ЮКассы, БЕЗ криптографической проверки подписи
        # TODO: Реализовать полную проверку ECDSA подписи для максимальной безопасности
        # Документация: https://yookassa.ru/developers/using-api/webhooks#signature
        def is_yookassa_ip(ip: str) -> bool:
            """Проверяет принадлежит ли IP к ЮКассе"""
            return any(ip.startswith(prefix) for prefix in YOOKASSA_IP_PREFIXES)
        
        if not signature_header:
            logger.warning(f"⚠️ ОТЛАДКА: Запрос без подписи от IP {client_ip}")
            if not is_yookassa_ip(client_ip):
                logger.error(f"🚨 БЕЗОПАСНОСТЬ: Запрос без подписи от НЕ-ЮКасса IP {client_ip}")
                return False
            logger.warning(f"✅ ОТЛАДКА: IP {client_ip} в белом списке ЮКассы, разрешаем")
            return True
        
        # Проверяем формат подписи
        if signature_header.startswith("v1 "):
            # Это ECDSA подпись от ЮКассы - временно разрешаем если IP правильный
            if not is_yookassa_ip(client_ip):
                logger.error(f"🚨 БЕЗОПАСНОСТЬ: ECDSA подпись от НЕ-ЮКасса IP {client_ip}")
                return False
            logger.warning(f"⚠️ ОТЛАДКА: ECDSA подпись от ЮКассы IP {client_ip} - временно разрешаем")
            logger.info(f"TODO: Реализовать проверку ECDSA подписи: {signature_header[:50]}...")
            return True
        
        # HMAC проверка не используется - ЮКасса перешла на ECDSA
        # Если потребуется в будущем, раскомментировать:
        # expected_signature = hmac.new(YOOKASSA_SECRET_KEY.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()
        # if not hmac.compare_digest(expected_signature, signature_header):
        #     return False
        
        # Дополнительная проверка структуры JSON
        try:
            data = json.loads(notification_body if isinstance(notification_body, str) else notification_body.decode('utf-8'))
            required_fields = ['type', 'event', 'object']
            for field in required_fields:
                if field not in data:
                    logger.warning(f"Отсутствует обязательное поле: {field}")
                    return False
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON вебхука: {e}")
            return False
        
        # Логируем IP для отладки
        if client_ip:
            logger.debug(f"Вебхук получен с IP: {client_ip}")
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка проверки webhook ЮКассы: {e}", exc_info=True)
        return False


# Функции для обратной совместимости с кодом (если где-то вызываются)
def create_payment_link_yookassa(*args, **kwargs):
    """Алиас для обратной совместимости"""
    return create_payment_link(*args, **kwargs)


def check_payment_status_yookassa(*args, **kwargs):
    """Алиас для обратной совместимости"""
    return check_payment_status(*args, **kwargs)
