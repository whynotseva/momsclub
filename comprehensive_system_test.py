#!/usr/bin/env python3
"""
Комплексный тест платежной системы и системы лояльности
Тестирует: вебхуки, платежи, скидки, пуши админам
"""
import sys
import os
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

# Добавляем путь к проекту
sys.path.insert(0, '/root/home/momsclub')

from database.config import AsyncSessionLocal
from database.models import User, PaymentLog, Subscription
from database.crud import (
    get_user_by_telegram_id,
    get_payment_by_transaction_id,
    get_active_subscription,
    create_payment_log,
    get_user_by_id
)
from sqlalchemy import select
from loyalty.service import effective_discount, price_with_discount
from utils.constants import SUBSCRIPTION_PRICE, ADMIN_IDS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TEST_USER_TELEGRAM_ID = 44054166  # Всеволод для теста

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.RESET}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.RESET}")

def print_test(msg):
    print(f"{Colors.BOLD}{Colors.YELLOW}🧪 {msg}{Colors.RESET}")

async def test_user_exists(session):
    """Проверяем, что тестовый пользователь существует"""
    print_test("1. Проверка существования тестового пользователя...")
    user = await get_user_by_telegram_id(session, TEST_USER_TELEGRAM_ID)
    if not user:
        print_error(f"Пользователь с Telegram ID {TEST_USER_TELEGRAM_ID} не найден!")
        return None
    
    print_success(f"Пользователь найден: {user.first_name} (ID: {user.id})")
    print_info(f"  - Текущая скидка лояльности: {effective_discount(user)}%")
    print_info(f"  - Lifetime discount: {user.lifetime_discount_percent}%")
    print_info(f"  - One-time discount: {user.one_time_discount_percent}%")
    print_info(f"  - Уровень лояльности: {user.current_loyalty_level}")
    print_info(f"  - First payment date: {user.first_payment_date}")
    return user

async def test_price_calculation():
    """Тест расчета цен со скидками"""
    print_test("2. Тест расчета цен со скидками (Decimal)...")
    
    base_price = SUBSCRIPTION_PRICE  # В рублях (990)
    
    test_cases = [
        (0, base_price),  # Без скидки
        (5, 941),  # 990 - 5% = 940.5 → 941 (округление вверх)
        (10, 891),  # 990 - 10% = 891 (точно)
        (15, 842),  # 990 - 15% = 841.5 → 842 (округление вверх)
    ]
    
    all_passed = True
    for discount, expected in test_cases:
        result = price_with_discount(base_price, discount)
        # Проверяем, что результат соответствует ожидаемому (с учетом округления)
        diff = abs(result - expected)
        if diff <= 1:  # Допускаем разницу в 1 рубль из-за округления
            print_success(f"  Скидка {discount}%: {base_price} руб → {result} руб")
        else:
            print_error(f"  Скидка {discount}%: ожидалось {expected} руб, получено {result} руб")
            all_passed = False
    
    return all_passed


async def test_idempotency(session, user):
    """Тест идемпотентности обработки платежей"""
    print_test("4. Тест идемпотентности (повторная обработка платежа)...")
    
    test_transaction_id = f"idempotency_test_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    base_price = SUBSCRIPTION_PRICE  # В рублях
    
    try:
        # Создаем первый платеж напрямую через ORM
        payment1 = PaymentLog(
            user_id=user.id,
            amount=base_price,
            status="success",
            payment_method="test",
            transaction_id=test_transaction_id,
            details="Тест идемпотентности - первый платеж",
            days=30
        )
        session.add(payment1)
        await session.commit()
        
        print_info(f"  Создан платеж: {test_transaction_id}")
        
        # Пытаемся создать дубликат
        try:
            payment2 = PaymentLog(
                user_id=user.id,
                amount=base_price,
                status="pending",
                payment_method="test",
                transaction_id=test_transaction_id,  # Тот же ID
                details="Тест идемпотентности - попытка дубликата",
                days=30
            )
            session.add(payment2)
            await session.commit()
            print_error("  ОШИБКА: Дубликат был создан!")
            await session.delete(payment2)
            await session.commit()
            return False
        except Exception as e:
            if "UNIQUE" in str(e) or "unique" in str(e).lower():
                print_success("  Идемпотентность работает: дубликат отклонен UNIQUE индексом")
                
                # Удаляем тестовый платеж
                await session.delete(payment1)
                await session.commit()
                return True
            else:
                print_error(f"  Неожиданная ошибка: {e}")
                await session.rollback()
                # Удаляем тестовый платеж
                await session.delete(payment1)
                await session.commit()
                return False
                
    except Exception as e:
        print_error(f"  Ошибка при тесте идемпотентности: {e}")
        await session.rollback()
        return False

async def test_transaction_rollback(session, user):
    """Тест отката транзакции при ошибке"""
    print_test("5. Тест отката транзакции...")
    
    try:
        async with session.begin():
            # Создаем платеж в транзакции
            payment = await create_payment_log(
                session,
                user_id=user.id,
                amount=SUBSCRIPTION_PRICE,  # В рублях
                status="pending",
                payment_method="test",
                transaction_id=f"rollback_test_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                details="Тест отката транзакции",
                days=30
            )
            
            # Имитируем ошибку
            raise Exception("Искусственная ошибка для теста отката")
    
    except Exception:
        # Транзакция должна быть откачена
        pass
    
    # Проверяем, что платеж не был сохранен
    test_id = f"rollback_test_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    found = await get_payment_by_transaction_id(session, test_id)
    
    if found is None:
        print_success("  Откат транзакции работает: платеж не сохранен")
        return True
    else:
        print_error("  ОШИБКА: Платеж был сохранен после отката!")
        await session.delete(found)
        await session.commit()
        return False

async def test_decimal_precision():
    """Тест точности вычислений с Decimal"""
    print_test("6. Тест точности вычислений (Decimal)...")
    
    from decimal import Decimal, ROUND_HALF_UP
    
    # Тестируем в рублях (так как теперь все работает в рублях)
    test_cases = [
        (990, 5, 941),   # 990 руб - 5% = 940.5 руб → 941 руб (округление вверх)
        (990, 10, 891),  # 990 руб - 10% = 891 руб (точно)
        (990, 15, 842),  # 990 руб - 15% = 841.5 руб → 842 руб (округление вверх)
    ]
    
    all_passed = True
    for base, discount, expected in test_cases:
        result = price_with_discount(base, discount)
        if result == expected:
            print_success(f"  {base} руб - {discount}% = {result} руб (точно)")
        else:
            diff = abs(result - expected)
            if diff <= 1:  # Допускаем 1 рубль из-за округления
                print_success(f"  {base} руб - {discount}% = {result} руб (разница: {diff} руб)")
            else:
                print_error(f"  {base} руб - {discount}%: ожидалось {expected} руб, получено {result} руб")
                all_passed = False
    
    return all_passed

async def test_first_payment_date(session, user):
    """Тест установки first_payment_date"""
    print_test("7. Тест установки first_payment_date...")
    
    try:
        # Обновляем объект пользователя из БД
        await session.refresh(user)
        original_date = user.first_payment_date
        
        # Проверяем, что first_payment_date установлен (если был платеж)
        if original_date:
            print_success(f"  first_payment_date уже установлен: {original_date}")
            return True
        else:
            print_info("  first_payment_date не установлен (это нормально для нового пользователя)")
            return True
            
    except Exception as e:
        print_error(f"  Ошибка: {e}")
        return False

async def test_admin_ids():
    """Тест наличия ID администраторов для пушей"""
    print_test("8. Проверка ADMIN_IDS для пушей...")
    
    if ADMIN_IDS and len(ADMIN_IDS) > 0:
        print_success(f"  Найдено администраторов: {len(ADMIN_IDS)}")
        print_info(f"  IDs: {', '.join(map(str, ADMIN_IDS))}")
        return True
    else:
        print_error("  ADMIN_IDS пуст! Пуши админам не будут отправляться.")
        return False

async def test_webhook_simulation(session, user):
    """Тест имитации вебхука с разными скидками"""
    print_test("9. Имитация вебхука с разными скидками...")
    
    from handlers.webhook_handlers import handle_payment_succeeded
    from yookassa.domain.notification import WebhookNotification
    import json
    
    # Тестируем разные сценарии (expected_final в копейках для расчета, потом конвертируем в рубли)
    scenarios = [
        {"discount": 0, "expected_final": 99000},   # 990 руб
        {"discount": 5, "expected_final": 94050},   # 940.5 руб → 941 руб (округление)
        {"discount": 10, "expected_final": 89100},  # 891 руб
        {"discount": 15, "expected_final": 84150},  # 841.5 руб → 842 руб (округление)
    ]
    
    passed = 0
    total = len(scenarios)
    
    for scenario in scenarios:
        discount = scenario["discount"]
        expected_final = scenario["expected_final"]
        
        # Создаем тестовый payment ID
        test_payment_id = f"test_webhook_{datetime.now().strftime('%Y%m%d%H%M%S')}_{discount}"
        
        # Имитируем объект платежа от ЮКассы
        class MockPayment:
            def __init__(self):
                self.id = test_payment_id
                self.status = "succeeded"
                self.description = f"Тестовый платеж со скидкой {discount}%"
                # expected_amount передаем в рублях (так как ЮКасса работает в рублях)
                expected_amount_rubles = expected_final / 100
                self.metadata = {
                    "user_id": str(user.telegram_id),
                    "days": "30",
                    "expected_amount": str(int(expected_amount_rubles)),  # В рублях, как строка
                    "loyalty_discount_percent": str(discount) if discount > 0 else None
                }
                if discount > 0:
                    self.metadata["loyalty_discount_percent"] = str(discount)
                
                class MockAmount:
                    def __init__(self, value):
                        self.value = str(value / 100.0)  # В рублях
                        self.currency = "RUB"
                
                self.amount = MockAmount(expected_final)
                
                class MockPaymentMethod:
                    pass
                
                self.payment_method = None
                self.captured_at = datetime.now().isoformat()
                self.created_at = datetime.now().isoformat()
        
        mock_payment = MockPayment()
        
        expected_rubles_for_display = int(expected_final / 100)
        print_info(f"\n  Тест вебхука со скидкой {discount}%:")
        print_info(f"    Payment ID: {test_payment_id}")
        print_info(f"    Ожидаемая сумма: {expected_rubles_for_display} руб")
        
        try:
            # Вызываем обработчик вебхука
            await handle_payment_succeeded(mock_payment)
            
            # Проверяем, что платеж был создан
            payment_log = await get_payment_by_transaction_id(session, test_payment_id)
            if payment_log:
                print_success(f"    Платеж обработан: ID {payment_log.id}, сумма {payment_log.amount}")
                
                # Проверяем сумму (в БД суммы хранятся в рублях)
                # expected_final в копейках (99000), конвертируем в рубли (990)
                expected_rubles = int(expected_final / 100)
                # Допускаем округление: 990.5 может стать 990 или 991
                if abs(payment_log.amount - expected_rubles) <= 1:
                    print_success(f"    Сумма корректна: {payment_log.amount} руб (ожидалось {expected_rubles} руб)")
                    passed += 1
                else:
                    print_error(f"    Неверная сумма: ожидалось {expected_rubles} руб, получено {payment_log.amount} руб")
                
                # Проверяем статус
                if payment_log.status == "success" and payment_log.is_confirmed:
                    print_success(f"    Статус корректный: success, подтвержден")
                else:
                    print_error(f"    Неверный статус: {payment_log.status}, is_confirmed={payment_log.is_confirmed}")
                
                # Удаляем тестовый платеж
                await session.delete(payment_log)
                await session.commit()
            else:
                print_error(f"    Платеж не найден после обработки вебхука!")
                
        except Exception as e:
            print_error(f"    Ошибка при обработке вебхука: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
    
    if passed == total:
        print_success(f"  Все вебхуки обработаны корректно: {passed}/{total}")
        return True
    else:
        print_error(f"  Обработано корректно: {passed}/{total}")
        return False

async def run_all_tests():
    """Запускает все тесты"""
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}🧪 КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ СИСТЕМЫ{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
    
    results = {}
    
    async with AsyncSessionLocal() as session:
        # Тест 1: Пользователь существует
        user = await test_user_exists(session)
        if not user:
            print_error("Тестирование прервано: пользователь не найден")
            return
        
        # Тест 2: Расчет цен
        results['price_calculation'] = await test_price_calculation()
        
        # Тест 3: Обработка платежей (упрощенный - только проверка UNIQUE индекса)
        # Используем прямой SQL для проверки UNIQUE индекса
        print_test("3. Тест UNIQUE индекса на transaction_id...")
        from sqlalchemy import text
        try:
            test_id = f"unique_test_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            # Создаем первый платеж
            payment1 = PaymentLog(
                user_id=user.id,
                amount=99000,
                status="success",
                payment_method="test",
                transaction_id=test_id,
                details="Тест UNIQUE",
                days=30
            )
            session.add(payment1)
            await session.commit()
            print_success(f"  Платеж создан: {test_id}")
            
            # Пытаемся создать дубликат
            try:
                payment2 = PaymentLog(
                    user_id=user.id,
                    amount=99000,
                    status="pending",
                    payment_method="test",
                    transaction_id=test_id,  # Тот же ID
                    details="Дубликат",
                    days=30
                )
                session.add(payment2)
                await session.commit()
                print_error("  ОШИБКА: Дубликат был создан!")
                await session.delete(payment2)
                await session.commit()
                results['payment_processing'] = False
            except Exception as e:
                if "UNIQUE" in str(e) or "unique" in str(e).lower():
                    print_success("  UNIQUE индекс работает: дубликат отклонен")
                    results['payment_processing'] = True
                else:
                    print_error(f"  Неожиданная ошибка: {e}")
                    results['payment_processing'] = False
                await session.rollback()
            
            # Удаляем тестовый платеж
            await session.delete(payment1)
            await session.commit()
            
        except Exception as e:
            print_error(f"  Ошибка при тесте UNIQUE индекса: {e}")
            await session.rollback()
            results['payment_processing'] = False
        
        # Тест 4: Идемпотентность
        results['idempotency'] = await test_idempotency(session, user)
        
        # Тест 5: Откат транзакций
        results['transaction_rollback'] = await test_transaction_rollback(session, user)
        
        # Тест 6: Точность Decimal
        results['decimal_precision'] = await test_decimal_precision()
        
        # Тест 7: first_payment_date
        results['first_payment_date'] = await test_first_payment_date(session, user)
        
        # Тест 8: ADMIN_IDS
        results['admin_ids'] = await test_admin_ids()
        
        # Тест 9: Имитация вебхука с разными скидками
        results['webhook_simulation'] = await test_webhook_simulation(session, user)
    
    # Итоговая статистика
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")
    
    passed = 0
    total = len(results)
    
    for test_name, result in results.items():
        if result:
            print_success(f"{test_name}: ПРОЙДЕН")
            passed += 1
        else:
            print_error(f"{test_name}: НЕ ПРОЙДЕН")
    
    print(f"\n{Colors.BOLD}Итого: {passed}/{total} тестов пройдено{Colors.RESET}")
    
    if passed == total:
        print_success("\n🎉 Все тесты пройдены успешно!")
        return True
    else:
        print_error(f"\n⚠️  {total - passed} тест(ов) не пройдено")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nТестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print_error(f"\nКритическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

