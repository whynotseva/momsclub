#!/usr/bin/env python3
"""
Тестирование исправлений из аудита кода
Дата: 20.11.2025

ТЕСТЫ:
1. CRIT-002: loyalty/service.py без with_for_update()
2. HIGH-001: HMAC валидация webhook
3. CRIT-001: Модель transaction_id с unique constraint
"""

import asyncio
import sys
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('audit_tests')

# Цвета для вывода
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

test_results = {
    'passed': 0,
    'failed': 0,
    'warnings': 0
}

def print_header(text):
    print(f"\n{BLUE}{'=' * 80}")
    print(f"{text}")
    print(f"{'=' * 80}{RESET}\n")

def print_test(name, status, details=""):
    global test_results
    if status == "PASS":
        print(f"{GREEN}✅ {name}: PASSED{RESET}")
        if details:
            print(f"   {details}")
        test_results['passed'] += 1
    elif status == "FAIL":
        print(f"{RED}❌ {name}: FAILED{RESET}")
        if details:
            print(f"   {details}")
        test_results['failed'] += 1
    elif status == "WARN":
        print(f"{YELLOW}⚠️  {name}: WARNING{RESET}")
        if details:
            print(f"   {details}")
        test_results['warnings'] += 1


async def test_1_loyalty_service_no_for_update():
    """ТЕСТ 1: Проверка loyalty/service.py без with_for_update()"""
    print_header("ТЕСТ 1: loyalty/service.py - Убран with_for_update()")
    
    try:
        # Проверяем что файл содержит правильные изменения
        with open('loyalty/service.py', 'r') as f:
            content = f.read()
        
        # Проверка 1: with_for_update() НЕ должно быть в коде (игнорируем комментарии)
        with_for_update_lines = [
            line for line in content.split('\n')
            if 'with_for_update()' in line and not line.strip().startswith('#')
        ]
        if with_for_update_lines:
            print_test(
                "Проверка отсутствия with_for_update()",
                "FAIL",
                "Найден with_for_update() в коде! Исправление не применено."
            )
            return False
        else:
            print_test(
                "Проверка отсутствия with_for_update()",
                "PASS",
                "with_for_update() успешно удалён из кода"
            )
        
        # Проверка 2: Проверка идемпотентности присутствует
        if 'benefit_check_query' in content and 'LoyaltyEvent' in content:
            print_test(
                "Проверка идемпотентности через LoyaltyEvent",
                "PASS",
                "Логика проверки идемпотентности на месте"
            )
        else:
            print_test(
                "Проверка идемпотентности через LoyaltyEvent",
                "WARN",
                "Не найдена проверка идемпотентности"
            )
        
        # Проверка 3: Комментарий об исправлении присутствует
        if 'CRIT-002' in content or 'SQLite не поддерживает' in content:
            print_test(
                "Документирование исправления",
                "PASS",
                "Комментарий об исправлении добавлен"
            )
        else:
            print_test(
                "Документирование исправления",
                "WARN",
                "Комментарий об исправлении не найден"
            )
        
        # Проверка 4: Пробуем импортировать модуль
        try:
            from loyalty import service
            print_test(
                "Импорт модуля loyalty.service",
                "PASS",
                "Модуль успешно импортирован без ошибок"
            )
        except Exception as e:
            print_test(
                "Импорт модуля loyalty.service",
                "FAIL",
                f"Ошибка импорта: {e}"
            )
            return False
        
        return True
        
    except Exception as e:
        print_test("ТЕСТ 1", "FAIL", f"Критическая ошибка: {e}")
        return False


async def test_2_webhook_hmac_validation():
    """ТЕСТ 2: Проверка HMAC валидации webhook"""
    print_header("ТЕСТ 2: Webhook HMAC валидация")
    
    try:
        # Проверяем webhook_handlers.py
        with open('handlers/webhook_handlers.py', 'r') as f:
            webhook_content = f.read()
        
        # Проверка 1: X-Idempotence-Key НЕ должен использоваться
        if 'X-Idempotence-Key' in webhook_content:
            # Проверяем что он упомянут только в комментариях
            lines_with_idempotence = [line for line in webhook_content.split('\n') 
                                     if 'X-Idempotence-Key' in line and not line.strip().startswith('#')]
            if lines_with_idempotence:
                print_test(
                    "Удаление X-Idempotence-Key",
                    "FAIL",
                    f"X-Idempotence-Key всё ещё используется: {len(lines_with_idempotence)} строк"
                )
            else:
                print_test(
                    "Удаление X-Idempotence-Key",
                    "PASS",
                    "X-Idempotence-Key больше не используется"
                )
        else:
            print_test(
                "Удаление X-Idempotence-Key",
                "PASS",
                "X-Idempotence-Key полностью удалён"
            )
        
        # Проверка 2: Только X-Content-HMAC-SHA256
        if 'X-Content-HMAC-SHA256' in webhook_content:
            print_test(
                "Использование X-Content-HMAC-SHA256",
                "PASS",
                "Правильный заголовок HMAC используется"
            )
        else:
            print_test(
                "Использование X-Content-HMAC-SHA256",
                "FAIL",
                "X-Content-HMAC-SHA256 не найден!"
            )
        
        # Проверяем payment.py
        with open('utils/payment.py', 'r') as f:
            payment_content = f.read()
        
        # Проверка 3: IP fallback удалён
        if 'YOOKASSA_IPS' in payment_content and 'is_yookassa' in payment_content:
            print_test(
                "Удаление IP fallback",
                "FAIL",
                "IP fallback всё ещё присутствует в коде"
            )
        else:
            print_test(
                "Удаление IP fallback",
                "PASS",
                "IP fallback успешно удалён"
            )
        
        # Проверка 4: Обязательная проверка подписи
        if 'if not signature_header:' in payment_content and 'return False' in payment_content:
            print_test(
                "Обязательная проверка HMAC",
                "PASS",
                "HMAC подпись обязательна"
            )
        else:
            print_test(
                "Обязательная проверка HMAC",
                "WARN",
                "Проверка обязательности HMAC не найдена"
            )
        
        # Проверка 5: Комментарий об исправлении
        if 'HIGH-001' in webhook_content or 'HIGH-001' in payment_content:
            print_test(
                "Документирование исправления HIGH-001",
                "PASS",
                "Исправление задокументировано"
            )
        else:
            print_test(
                "Документирование исправления HIGH-001",
                "WARN",
                "Комментарий об исправлении не найден"
            )
        
        return True
        
    except Exception as e:
        print_test("ТЕСТ 2", "FAIL", f"Критическая ошибка: {e}")
        return False


async def test_3_transaction_id_model():
    """ТЕСТ 3: Проверка модели transaction_id"""
    print_header("ТЕСТ 3: Модель transaction_id с unique constraint")
    
    try:
        # Проверяем models.py
        with open('database/models.py', 'r') as f:
            models_content = f.read()
        
        # Проверка 1: transaction_id с unique=True
        if 'transaction_id' in models_content and 'unique=True' in models_content:
            print_test(
                "Уникальный constraint на transaction_id",
                "PASS",
                "unique=True добавлен"
            )
        else:
            print_test(
                "Уникальный constraint на transaction_id",
                "FAIL",
                "unique=True не найден!"
            )
            return False
        
        # Проверка 2: transaction_id с nullable=False
        transaction_id_line = [line for line in models_content.split('\n') 
                              if 'transaction_id' in line and 'Column' in line]
        if transaction_id_line and 'nullable=False' in transaction_id_line[0]:
            print_test(
                "NOT NULL constraint на transaction_id",
                "PASS",
                "nullable=False добавлен"
            )
        else:
            print_test(
                "NOT NULL constraint на transaction_id",
                "FAIL",
                "nullable=False не найден!"
            )
        
        # Проверка 3: Индекс на transaction_id
        if 'index=True' in models_content:
            print_test(
                "Индекс на transaction_id",
                "PASS",
                "index=True добавлен"
            )
        else:
            print_test(
                "Индекс на transaction_id",
                "WARN",
                "index=True не найден (будет создан при миграции)"
            )
        
        # Проверка 4: Скрипт миграции существует
        import os
        if os.path.exists('database/migrations/migrate_transaction_id_20251120.py'):
            print_test(
                "Скрипт миграции БД",
                "PASS",
                "Скрипт миграции создан"
            )
        else:
            print_test(
                "Скрипт миграции БД",
                "FAIL",
                "Скрипт миграции не найден!"
            )
        
        # Проверка 5: Импорт модели работает
        try:
            from database.models import PaymentLog
            print_test(
                "Импорт модели PaymentLog",
                "PASS",
                "Модель успешно импортирована"
            )
        except Exception as e:
            print_test(
                "Импорт модели PaymentLog",
                "FAIL",
                f"Ошибка импорта: {e}"
            )
            return False
        
        return True
        
    except Exception as e:
        print_test("ТЕСТ 3", "FAIL", f"Критическая ошибка: {e}")
        return False


async def test_4_integration():
    """ТЕСТ 4: Интеграционный тест всех модулей"""
    print_header("ТЕСТ 4: Интеграционный тест")
    
    try:
        # Проверка 1: Все модули импортируются
        try:
            from database.models import PaymentLog, User, LoyaltyEvent
            from loyalty import service, levels, benefits
            from handlers import webhook_handlers
            from utils import payment
            
            print_test(
                "Импорт всех модулей",
                "PASS",
                "Все исправленные модули импортируются без ошибок"
            )
        except Exception as e:
            print_test(
                "Импорт всех модулей",
                "FAIL",
                f"Ошибка импорта: {e}"
            )
            return False
        
        # Проверка 2: Функция apply_benefit_from_callback доступна
        if hasattr(service, 'apply_benefit_from_callback'):
            print_test(
                "Функция apply_benefit_from_callback",
                "PASS",
                "Функция доступна и не использует with_for_update()"
            )
        else:
            print_test(
                "Функция apply_benefit_from_callback",
                "FAIL",
                "Функция не найдена!"
            )
        
        # Проверка 3: Функция verify_yookassa_signature доступна
        if hasattr(payment, 'verify_yookassa_signature'):
            print_test(
                "Функция verify_yookassa_signature",
                "PASS",
                "Функция доступна с усиленной проверкой HMAC"
            )
        else:
            print_test(
                "Функция verify_yookassa_signature",
                "FAIL",
                "Функция не найдена!"
            )
        
        # Проверка 4: Проверка совместимости с текущей БД
        print_test(
            "Совместимость с БД",
            "WARN",
            "Для проверки нужно запустить миграцию на копии БД"
        )
        
        return True
        
    except Exception as e:
        print_test("ТЕСТ 4", "FAIL", f"Критическая ошибка: {e}")
        return False


async def run_all_tests():
    """Запуск всех тестов"""
    print_header(f"🧪 ТЕСТИРОВАНИЕ ИСПРАВЛЕНИЙ ИЗ АУДИТА КОДА")
    print(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Запускаем тесты последовательно
    test1_result = await test_1_loyalty_service_no_for_update()
    test2_result = await test_2_webhook_hmac_validation()
    test3_result = await test_3_transaction_id_model()
    test4_result = await test_4_integration()
    
    # Итоги
    print_header("📊 ИТОГИ ТЕСТИРОВАНИЯ")
    
    print(f"{GREEN}✅ Тестов пройдено: {test_results['passed']}{RESET}")
    print(f"{RED}❌ Тестов провалено: {test_results['failed']}{RESET}")
    print(f"{YELLOW}⚠️  Предупреждений: {test_results['warnings']}{RESET}")
    
    print(f"\n{'=' * 80}\n")
    
    if test_results['failed'] > 0:
        print(f"{RED}❌ ТЕСТИРОВАНИЕ НЕ ПРОЙДЕНО!{RESET}")
        print(f"{RED}Исправьте ошибки перед деплоем.{RESET}\n")
        return False
    elif test_results['warnings'] > 0:
        print(f"{YELLOW}⚠️  ТЕСТИРОВАНИЕ ПРОЙДЕНО С ПРЕДУПРЕЖДЕНИЯМИ{RESET}")
        print(f"{YELLOW}Рекомендуется проверить предупреждения перед деплоем.{RESET}\n")
        return True
    else:
        print(f"{GREEN}✅ ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ!{RESET}")
        print(f"{GREEN}Исправления готовы к деплою.{RESET}\n")
        return True


if __name__ == "__main__":
    result = asyncio.run(run_all_tests())
    sys.exit(0 if result else 1)
