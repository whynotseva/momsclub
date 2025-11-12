"""
Модуль для работы с платежной системой ЮКасса
Полная замена Prodamus на ЮКассу
"""

import os
import logging
import random
import time
import uuid
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any
from dotenv import load_dotenv
from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

load_dotenv()

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
            "user_id": str(user_id),
            "sub_type": sub_type,
            "payment_label": payment_label,
            "days": str(days or 30),
            "expected_amount": str(amount)  # P1.1: Сохраняем ожидаемую сумму для сверки в вебхуке
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
            "user_id": str(user_id),
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


def verify_yookassa_signature(notification_body: str, client_ip: str = None) -> bool:
    """
    Проверяет подпись вебхука от ЮКассы.
    ЮКасса использует IP-based проверку. Дополнительно валидируется структура JSON.

    Args:
        notification_body: тело уведомления
        client_ip: IP адрес клиента (обязательно для проверки)

    Returns:
        bool: True если подпись корректна
    """
    import json
    import ipaddress
    
    try:
        # Проверка IP-адреса (белый список YooKassa)
        # Официальные IP-адреса YooKassa для продакшена:
        # 185.71.76.0/27, 185.71.77.0/27, 77.75.153.0/25, 77.75.154.128/25
        # Для тестового окружения IP могут отличаться
        yookassa_networks = [
            ipaddress.ip_network('185.71.76.0/27'),
            ipaddress.ip_network('185.71.77.0/27'),
            ipaddress.ip_network('77.75.153.0/25'),
            ipaddress.ip_network('77.75.154.128/25'),
        ]
        
        # Если IP указан, проверяем его
        if client_ip:
            try:
                client_ip_obj = ipaddress.ip_address(client_ip)
                # Проверяем, входит ли IP в разрешенные сети
                is_valid_ip = any(client_ip_obj in net for net in yookassa_networks)
                
                if not is_valid_ip:
                    # В тестовом окружении можно разрешить любые IP (для разработки)
                    # В продакшене эта проверка обязательна
                    import os
                    allow_test_ips = os.getenv("YOOKASSA_ALLOW_TEST_IPS", "false").lower() == "true"
                    
                    if not allow_test_ips:
                        logger.warning(f"Вебхук от неразрешенного IP: {client_ip}")
                        return False
                    else:
                        logger.debug(f"Вебхук от IP {client_ip} (разрешено для тестов)")
                else:
                    logger.debug(f"Вебхук от разрешенного IP YooKassa: {client_ip}")
            except ValueError:
                logger.warning(f"Некорректный формат IP адреса: {client_ip}")
                return False
        else:
            logger.warning("IP адрес клиента не указан, пропускаем IP-проверку")
            # В продакшене лучше отклонять, но для совместимости оставим warning
        
        # Валидация структуры JSON
        try:
            data = json.loads(notification_body)
        except json.JSONDecodeError as e:
            logger.error(f"Некорректный JSON в вебхуке: {e}")
            return False
        
        # Проверяем обязательные поля
        required_fields = ['type', 'event', 'object']
        for field in required_fields:
            if field not in data:
                logger.warning(f"Отсутствует обязательное поле в вебхуке: {field}")
                return False
        
        # Маскируем чувствительные данные в логах (не логируем полное тело)
        masked_data = {
            'type': data.get('type'),
            'event': data.get('event'),
            'object_id': data.get('object', {}).get('id', 'N/A')[:20] + '...' if isinstance(data.get('object'), dict) else 'N/A'
        }
        logger.debug(f"Валидный вебхук от YooKassa: {masked_data}")
        
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
