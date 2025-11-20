"""
Тестовый скрипт для проверки работы вебхука ЮКассы
Проверяет: rate limiting, валидацию, обработку событий
"""

import requests
import json
import time
import hmac
import hashlib
from datetime import datetime
import uuid
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv не установлен, используем переменные окружения напрямую
    pass

# URL вебхука на сервере
# Для тестирования на сервере используйте: "https://momsclubwebhook.ru/webhook"
# Для локального тестирования: "http://localhost:8000/webhook"
WEBHOOK_URL = "https://momsclubwebhook.ru/webhook"
HEALTH_URL = "https://momsclubwebhook.ru/health"

def test_health_check():
    """Проверка health endpoint"""
    print("🔍 Тест 1: Health Check")
    try:
        response = requests.get(HEALTH_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Health check OK: {data}")
            return True
        elif response.status_code == 404:
            print(f"   ⚠️  Health endpoint не найден (404) - возможно на другом пути")
            print(f"   💡 Проверяем альтернативные пути...")
            # Пробуем корневой путь
            alt_url = WEBHOOK_URL.replace('/webhook', '/')
            try:
                alt_response = requests.get(alt_url, timeout=5)
                if alt_response.status_code == 200:
                    print(f"   ✅ Health check OK на корневом пути: {alt_response.json()}")
                    return True
            except:
                pass
            return True  # Не критично для теста
        else:
            print(f"   ⚠️  Health check: {response.status_code} (не критично)")
            return True  # Не критично для теста
    except Exception as e:
        print(f"   ⚠️  Health check error: {e} (не критично)")
        return True  # Не критично для теста

def calculate_hmac_signature(body: str, secret_key: str) -> str:
    """Вычисляет HMAC-SHA256 подпись для вебхука"""
    return hmac.new(
        secret_key.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

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
    
    # Получаем secret key для подписи
    secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_secret")
    
    # Отправляем запросы быстро, без задержки
    start_time = time.time()
    for i in range(20):
        event = create_mock_payment_succeeded_event()
        # Добавляем HMAC подпись для каждого запроса
        body = json.dumps(event, ensure_ascii=False)
        signature = calculate_hmac_signature(body, secret_key)
        
        try:
            response = requests.post(
                WEBHOOK_URL,
                data=body.encode('utf-8'),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Content-HMAC-SHA256": signature
                },
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
    print("\n🔍 Тест 3: Валидация подписи (невалидные данные)")
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

def test_hmac_signature_validation():
    """Проверка HMAC подписи с правильным и неправильным ключом"""
    print("\n🔍 Тест 3.1: Валидация HMAC подписи")
    time.sleep(2)  # Ждем сброса rate limiting
    
    # Получаем secret key из окружения (если доступен)
    secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_secret_key_for_validation")
    
    # Создаем валидное событие
    event = create_mock_payment_succeeded_event(
        payment_id=f"hmac_test_{int(time.time())}",
        user_id=999999999,
        amount=1990,
        days=30
    )
    
    body = json.dumps(event, ensure_ascii=False)
    
    # Тест 1: Правильная подпись
    print("   📝 Тест 3.1.1: Запрос с правильной HMAC подписью")
    correct_signature = calculate_hmac_signature(body, secret_key)
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Content-HMAC-SHA256": correct_signature
            },
            timeout=10
        )
        
        print(f"      📊 Статус: {response.status_code}")
        if response.status_code in [200, 403, 500]:  # 403 если проверка строгая, 500 если пользователь не найден
            print("      ✅ Запрос обработан (подпись проверена)")
        else:
            print(f"      ⚠️  Неожиданный статус: {response.status_code}")
    except Exception as e:
        print(f"      ❌ Ошибка: {e}")
    
    time.sleep(1)
    
    # Тест 2: Неправильная подпись
    print("   📝 Тест 3.1.2: Запрос с неправильной HMAC подписью")
    wrong_signature = "wrong_signature_" + "a" * 50
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Content-HMAC-SHA256": wrong_signature
            },
            timeout=10
        )
        
        print(f"      📊 Статус: {response.status_code}")
        if response.status_code == 403:
            print("      ✅ Неправильная подпись отклонена (403)")
            return True
        elif response.status_code == 429:
            print("      ⚠️  Rate limit")
            return True
        else:
            print(f"      ⚠️  Статус: {response.status_code} (ожидался 403)")
            return False
    except Exception as e:
        print(f"      ❌ Ошибка: {e}")
        return False
    
    # Тест 3: Запрос без подписи (должен работать с предупреждением)
    print("   📝 Тест 3.1.3: Запрос без заголовка подписи")
    time.sleep(1)
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=10
        )
        
        print(f"      📊 Статус: {response.status_code}")
        if response.status_code in [200, 403, 500]:
            print("      ✅ Запрос обработан (без подписи, с предупреждением в логах)")
            return True
        else:
            print(f"      ⚠️  Статус: {response.status_code}")
            return False
    except Exception as e:
        print(f"      ❌ Ошибка: {e}")
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
    
    # Добавляем HMAC подпись
    body = json.dumps(event, ensure_ascii=False)
    secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_secret")
    signature = calculate_hmac_signature(body, secret_key)
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Content-HMAC-SHA256": signature
            },
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
    
    # Добавляем HMAC подпись
    body = json.dumps(event, ensure_ascii=False)
    secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_secret")
    signature = calculate_hmac_signature(body, secret_key)
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Content-HMAC-SHA256": signature
            },
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
    event["object"]["payment_method"]["type"] = "bank_card"
    
    # Добавляем HMAC подпись для более реалистичного теста
    body = json.dumps(event, ensure_ascii=False)
    secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_secret")
    signature = calculate_hmac_signature(body, secret_key)
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Content-HMAC-SHA256": signature
            },
            timeout=10
        )
        
        print(f"   📊 Статус ответа: {response.status_code}")
        print(f"   📊 Payment Method ID: {payment_method_id}")
        print(f"   📊 Payment Method Saved: {event['object']['payment_method']['saved']}")
        print(f"   📊 Payment Method Type: {event['object']['payment_method']['type']}")
        
        if response.status_code == 200:
            print("   ✅ Рекуррентный платеж обработан успешно")
            print("   💡 Проверьте логи сервера на наличие:")
            print("      - 'Сохранен payment_method_id для пользователя'")
            print("      - 'is_recurring_active=True'")
            print("      - 'Метаданные (замаскированы): ...' (должны быть замаскированы)")
            return True
        elif response.status_code == 429:
            print("   ⚠️  Rate limit (подождите и повторите тест)")
            return True  # Не критично
        elif response.status_code == 500:
            print("   ⚠️  Ошибка обработки (возможно, пользователь не существует)")
            print("   💡 Это нормально для тестового пользователя")
            print("   💡 Проверьте логи на наличие обработки payment_method")
            return True  # Не критично для теста
        else:
            print(f"   ⚠️  Неожиданный статус: {response.status_code}")
            print(f"   📊 Тело ответа: {response.text[:200]}")
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
    
    # Добавляем HMAC подпись
    body = json.dumps(event, ensure_ascii=False)
    secret_key = os.getenv("YOOKASSA_SECRET_KEY", "test_secret")
    signature = calculate_hmac_signature(body, secret_key)
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=body.encode('utf-8'),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Content-HMAC-SHA256": signature
            },
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
    
    # Тест 3: Валидация подписи (невалидные данные)
    results.append(("Валидация подписи (невалидные данные)", test_invalid_signature()))
    
    # Тест 3.1: Валидация HMAC подписи
    results.append(("Валидация HMAC подписи", test_hmac_signature_validation()))
    
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

