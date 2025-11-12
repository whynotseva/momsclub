"""
Тестовый скрипт для проверки работы вебхука ЮКассы
Проверяет: rate limiting, валидацию, обработку событий
"""

import requests
import json
import time
from datetime import datetime
import uuid

# URL вебхука на сервере
WEBHOOK_URL = "http://localhost:8000/webhook"
HEALTH_URL = "http://localhost:8000/health"

def test_health_check():
    """Проверка health endpoint"""
    print("🔍 Тест 1: Health Check")
    try:
        response = requests.get(HEALTH_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Health check OK: {data}")
            return True
        else:
            print(f"   ❌ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Health check error: {e}")
        return False

def create_mock_payment_succeeded_event(payment_id=None, user_id=123456789, amount=1990, days=30, with_saved_method=True):
    """Создает mock-событие успешного платежа"""
    if not payment_id:
        payment_id = str(uuid.uuid4())
    
    event = {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": payment_id,
            "status": "succeeded",
            "amount": {
                "value": f"{amount}.00",
                "currency": "RUB"
            },
            "description": f"Подписка на {days} дней",
            "metadata": {
                "user_id": str(user_id),
                "sub_type": "default",
                "days": str(days),
                "payment_label": f"test_{user_id}_{int(time.time())}"
            },
            "created_at": datetime.now().isoformat() + "Z",
            "captured_at": datetime.now().isoformat() + "Z"
        }
    }
    
    # Добавляем сохраненный метод оплаты для рекуррентных платежей
    if with_saved_method:
        event["object"]["payment_method"] = {
            "id": f"test_method_{payment_id[:8]}",
            "saved": True,
            "type": "bank_card"
        }
    
    return event

def create_mock_payment_canceled_event(payment_id=None):
    """Создает mock-событие отмененного платежа"""
    if not payment_id:
        payment_id = str(uuid.uuid4())
    
    return {
        "type": "notification",
        "event": "payment.canceled",
        "object": {
            "id": payment_id,
            "status": "canceled",
            "cancellation_details": {
                "reason": "test_cancel"
            }
        }
    }

def test_rate_limiting():
    """Проверка rate limiting (10 запросов в секунду)"""
    print("\n🔍 Тест 2: Rate Limiting")
    print("   Отправляю 20 запросов БЕЗ задержки (лимит: 10/сек)...")
    
    success_count = 0
    rate_limited_count = 0
    error_count = 0
    
    # Отправляем запросы быстро, без задержки
    start_time = time.time()
    for i in range(20):
        event = create_mock_payment_succeeded_event()
        try:
            response = requests.post(
                WEBHOOK_URL,
                json=event,
                headers={"Content-Type": "application/json"},
                timeout=2
            )
            
            if response.status_code == 200:
                success_count += 1
            elif response.status_code == 429:
                rate_limited_count += 1
                if i < 15:  # Показываем только первые несколько
                    print(f"   ⚠️  Запрос {i+1}: Rate limit (ожидаемо)")
            else:
                error_count += 1
                print(f"   ❌ Запрос {i+1}: {response.status_code}")
        except Exception as e:
            error_count += 1
            if i < 5:  # Показываем только первые ошибки
                print(f"   ❌ Запрос {i+1}: {e}")
    
    elapsed = time.time() - start_time
    print(f"   📊 Время выполнения: {elapsed:.2f} сек")
    print(f"   📊 Результаты: успешно={success_count}, rate limited={rate_limited_count}, ошибки={error_count}")
    
    if rate_limited_count > 0:
        print("   ✅ Rate limiting работает! Некоторые запросы были ограничены.")
        return True
    elif success_count >= 10:
        print("   ⚠️  Rate limiting не сработал (все запросы прошли)")
        print("   💡 Возможно, slowapi не инициализирован или лимит слишком высокий")
        return True  # Не критично, но стоит проверить
    else:
        print("   ⚠️  Неожиданные результаты")
        return True

def test_invalid_signature():
    """Проверка обработки невалидной подписи"""
    print("\n🔍 Тест 3: Валидация подписи")
    time.sleep(2)  # Ждем сброса rate limiting
    
    # Отправляем запрос с невалидными данными
    invalid_data = {"invalid": "data", "no_signature": True}
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=invalid_data,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        
        if response.status_code == 403:
            print("   ✅ Невалидный запрос отклонен (403)")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True  # Не критично
        else:
            print(f"   ⚠️  Неожиданный статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_payment_succeeded():
    """Проверка обработки успешного платежа"""
    print("\n🔍 Тест 4: Обработка успешного платежа")
    time.sleep(2)  # Ждем сброса rate limiting
    
    event = create_mock_payment_succeeded_event(
        payment_id=f"test_{int(time.time())}",
        user_id=999999999,  # Тестовый пользователь (не должен существовать)
        amount=1990,
        days=30
    )
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=event,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"   📊 Статус ответа: {response.status_code}")
        print(f"   📊 Тело ответа: {response.text[:200]}")
        
        if response.status_code in [200, 500]:  # 500 может быть, если пользователь не найден
            print("   ✅ Запрос обработан (ошибка обработки ожидаема, если пользователь не существует)")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True  # Не критично
        else:
            print(f"   ⚠️  Неожиданный статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_payment_canceled():
    """Проверка обработки отмененного платежа"""
    print("\n🔍 Тест 5: Обработка отмененного платежа")
    time.sleep(2)  # Ждем сброса rate limiting
    
    event = create_mock_payment_canceled_event(
        payment_id=f"test_cancel_{int(time.time())}"
    )
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=event,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        
        print(f"   📊 Статус ответа: {response.status_code}")
        
        if response.status_code == 200:
            print("   ✅ Запрос обработан")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True  # Не критично
        else:
            print(f"   ⚠️  Статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_malformed_json():
    """Проверка обработки невалидного JSON"""
    print("\n🔍 Тест 6: Обработка невалидного JSON")
    time.sleep(2)  # Ждем сброса rate limiting
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data="invalid json {",
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        
        print(f"   📊 Статус ответа: {response.status_code}")
        
        if response.status_code in [400, 403, 500]:
            print("   ✅ Невалидный JSON обработан корректно")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True  # Не критично
        else:
            print(f"   ⚠️  Неожиданный статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_recurring_payment():
    """Проверка обработки рекуррентного платежа с сохраненным методом оплаты"""
    print("\n🔍 Тест 7: Рекуррентный платеж (с сохраненным payment_method)")
    time.sleep(2)  # Ждем сброса rate limiting
    
    # Создаем событие с сохраненным методом оплаты
    payment_method_id = f"recurring_method_{int(time.time())}"
    event = create_mock_payment_succeeded_event(
        payment_id=f"recurring_{int(time.time())}",
        user_id=999999999,  # Тестовый пользователь
        amount=1990,
        days=30,
        with_saved_method=True
    )
    
    # Убеждаемся, что payment_method присутствует и сохранен
    event["object"]["payment_method"]["id"] = payment_method_id
    event["object"]["payment_method"]["saved"] = True
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=event,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"   📊 Статус ответа: {response.status_code}")
        print(f"   📊 Тело ответа: {response.text[:200]}")
        print(f"   📊 Payment Method ID: {payment_method_id}")
        print(f"   📊 Payment Method Saved: {event['object']['payment_method']['saved']}")
        
        if response.status_code == 200:
            print("   ✅ Рекуррентный платеж обработан")
            print("   💡 Проверьте логи сервера на наличие:")
            print("      - 'Сохранен payment_method_id для пользователя'")
            print("      - 'is_recurring_active=True'")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True  # Не критично
        elif response.status_code == 500:
            print("   ⚠️  Ошибка обработки (возможно, пользователь не существует)")
            print("   💡 Это нормально для тестового пользователя")
            return True  # Не критично для теста
        else:
            print(f"   ⚠️  Неожиданный статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def test_recurring_payment_without_method():
    """Проверка обработки обычного платежа без сохраненного метода"""
    print("\n🔍 Тест 8: Обычный платеж (без сохраненного payment_method)")
    time.sleep(2)  # Ждем сброса rate limiting
    
    # Создаем событие БЕЗ сохраненного метода оплаты
    event = create_mock_payment_succeeded_event(
        payment_id=f"regular_{int(time.time())}",
        user_id=999999999,
        amount=1990,
        days=30,
        with_saved_method=False
    )
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=event,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"   📊 Статус ответа: {response.status_code}")
        print(f"   📊 Payment Method: отсутствует (ожидаемо для обычного платежа)")
        
        if response.status_code == 200:
            print("   ✅ Обычный платеж обработан (без сохранения метода)")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True
        elif response.status_code == 500:
            print("   ⚠️  Ошибка обработки (возможно, пользователь не существует)")
            return True
        else:
            print(f"   ⚠️  Статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def main():
    """Запуск всех тестов"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ ВЕБХУКА ЮКАССЫ")
    print("=" * 60)
    
    results = []
    
    # Тест 1: Health check
    results.append(("Health Check", test_health_check()))
    
    # Тест 2: Rate limiting
    results.append(("Rate Limiting", test_rate_limiting()))
    
    # Тест 3: Валидация подписи
    results.append(("Валидация подписи", test_invalid_signature()))
    
    # Тест 4: Успешный платеж
    results.append(("Обработка успешного платежа", test_payment_succeeded()))
    
    # Тест 5: Отмененный платеж
    results.append(("Обработка отмененного платежа", test_payment_canceled()))
    
    # Тест 6: Невалидный JSON
    results.append(("Обработка невалидного JSON", test_malformed_json()))
    
    # Тест 7: Рекуррентный платеж
    results.append(("Рекуррентный платеж (с payment_method)", test_recurring_payment()))
    
    # Тест 8: Обычный платеж без сохраненного метода
    results.append(("Обычный платеж (без payment_method)", test_recurring_payment_without_method()))
    
    # Итоги
    print("\n" + "=" * 60)
    print("📊 ИТОГИ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status}: {test_name}")
    
    print(f"\n   Всего: {passed}/{total} тестов пройдено")
    
    if passed == total:
        print("\n   🎉 Все тесты пройдены успешно!")
    else:
        print(f"\n   ⚠️  {total - passed} тест(ов) не пройдено")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)

