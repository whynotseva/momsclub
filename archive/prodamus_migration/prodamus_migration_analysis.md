# Анализ возможности замены ЮКассы на Prodamus

## Сравнение функционала

### 1. Создание платежных ссылок

**Текущая система (ЮКасса):**
```python
# utils/payment.py
def create_payment_link(amount, user_id, description, sub_type, days, return_url, phone)
```
- Создает платеж через API ЮКассы
- Возвращает ссылку на оплату и payment_id
- Сохраняет метаданные (user_id, sub_type, days, payment_label)

**Prodamus:**
```php
// Из документации
$data = [
    'order_id' => '',
    'customer_phone' => '+79278820060',
    'customer_email' => 'site_testing@prodamus.ru',
    'subscription' => 1,
    'vk_user_id' => 12345,
    'customer_extra' => '',
    'do' => 'link',
    'subscription_limit_autopayments' => 10
];
```
- Аналогичный функционал формирования ссылок
- Поддерживает те же параметры

**✅ СОВМЕСТИМОСТЬ:** Полная - можно заменить create_payment_link()

---

### 2. Обработка вебхуков

**Текущая система:**
```python
# handlers/webhook_handlers.py
@app.post("/webhook")
async def webhook_handler(request: Request):
    # Обрабатывает payment.succeeded, payment.canceled
    # Проверяет подпись, находит платеж по transaction_id
    # Активирует подписку, отправляет уведомления
```

**Prodamus:**
- Отправляет вебхуки при автосписании
- Имеет блок subscription в уведомлениях
- Поддерживает различные типы действий (auto_payment, deactivation, reactivation, finish)

**✅ СОВМЕСТИМОСТЬ:** Полная - аналогичная структура обработки

---

### 3. Автоплатежи (рекуррентные платежи)

**Текущая система:**
```python
# Сохраняет payment_method_id после первого платежа
user.yookassa_payment_method_id = payment_data.get("payment_method", {}).get("id")

# Использует для автоплатежей
def create_autopayment(user_id, amount, description, payment_method_id)
```

**Prodamus:**
- Поддерживает автосписания по подпискам
- Сохраняет платежные методы автоматически
- Отправляет уведомления при автосписании
- Имеет лимиты автоплатежей (subscription_limit_autopayments)

**✅ СОВМЕСТИМОСТЬ:** Полная - аналогичный механизм

---

### 4. Управление подписками

**Текущая система:**
```python
# database/crud.py
async def create_subscription()
async def extend_subscription()
async def deactivate_subscription()
```

**Prodamus REST API:**
```php
// setActivity - управление статусами
$data = [
  'subscription' => 1,
  'vk_user_id' => 123,
  'active_manager' => 0
];

// setSubscriptionPaymentDate - установка даты платежа
$data = [
  'subscription' => 1,
  'date' => '2021-12-31 23:59'
];
```

**✅ СОВМЕСТИМОСТЬ:** Полная - можно интегрировать API Prodamus

---

### 5. Структура данных платежей

**Текущая система:**
```sql
payment_logs:
- transaction_id (ID платежа ЮКассы)
- payment_method (youkassa_autopay, etc.)
- status (success, pending, failed)
```

**Prodamus:**
- Аналогичные данные в уведомлениях
- transaction_id в поле order_id
- payment_type: "Автоплатеж"
- subscription блок с подробностями

**✅ СОВМЕСТИМОСТЬ:** Полная - аналогичная структура

---

## План миграции с ЮКассы на Prodamus

### Этап 1: Подготовка (1-2 дня)

#### 1.1 Создание нового модуля payment_prodamus.py
```python
# utils/payment_prodamus.py
def create_payment_link_prodamus(amount, user_id, description, sub_type, days, return_url, phone)
def create_autopayment_prodamus(user_id, amount, description, payment_method_id)
def verify_prodamus_signature(body_str, signature, secret_key)
```

#### 1.2 Обновление конфигурации
```python
# config.py
PRODAMUS_SHOP_ID = os.getenv("PRODAMUS_SHOP_ID")
PRODAMUS_SECRET_KEY = os.getenv("PRODAMUS_SECRET_KEY")
PAYMENT_PROVIDER = "prodamus"  # или "yookassa"
```

#### 1.3 Обновление базы данных
```sql
-- Добавление поля для ID платежного метода Prodamus
ALTER TABLE users ADD COLUMN prodamus_payment_method_id VARCHAR(255);
```

### Этап 2: Параллельная работа (3-5 дней)

#### 2.1 Дублирование обработчиков
```python
# handlers/webhook_handlers.py
async def process_yookassa_webhook()
async def process_prodamus_webhook()

@app.post("/webhook")
async def webhook_handler(request: Request):
    # Определение провайдера и вызов соответствующего обработчика
    if is_yookassa_webhook(request):
        return await process_yookassa_webhook(request)
    elif is_prodamus_webhook(request):
        return await process_prodamus_webhook(request)
```

#### 2.2 A/B тестирование
- 50% пользователей на ЮКассе
- 50% пользователей на Prodamus
- Сравнение конверсии и проблем

### Этап 3: Полная миграция (1-2 дня)

#### 3.1 Переключение платежей
```python
# utils/payment.py
def create_payment_link():
    if PAYMENT_PROVIDER == "prodamus":
        return create_payment_link_prodamus(...)
    else:
        return create_payment_link_yookassa(...)
```

#### 3.2 Миграция существующих подписок
```python
# Скрипт миграции
async def migrate_payment_methods():
    # Для пользователей с yookassa_payment_method_id
    # создать соответствующие записи в Prodamus через API
    # или отключить автопродление с уведомлением
```

---

## Сравнение API методов

| Функционал | ЮКасса | Prodamus | Совместимость |
|------------|---------|----------|---------------|
| Создание платежа | ✅ API payments | ✅ Формирование ссылки | ✅ Полная |
| Автоплатежи | ✅ payment_method_id | ✅ Автосписания | ✅ Полная |
| Вебхуки | ✅ payment.succeeded/canceled | ✅ action_code: auto_payment | ✅ Полная |
| Управление подписками | ❌ (через БД) | ✅ setActivity, setSubscriptionPaymentDate | ✅ Можно интегрировать |
| Сохранение карт | ✅ save_payment_method | ✅ Автоматически | ✅ Полная |

---

## Преимущества миграции на Prodamus

### 1. Специализация на подписках
- Prodamus изначально ориентирован на подписочные сервисы
- Лучшая поддержка автоплатежей
- Специфические уведомления для подписок

### 2. Детальная аналитика
- Подробные уведомления о всех действиях с подпиской
- Информация о причинах деактивации
- Статистика автоплатежей

### 3. Гибкое управление
- REST API для управления подписками
- Возможность сдвигать даты платежей
- Управление лимитами автоплатежей

---

## Необходимые изменения в коде

### 1. Замена платежного модуля
```python
# Вместо:
from utils.payment import create_payment_link, create_autopayment

# Станет:
from utils.payment_prodamus import create_payment_link, create_autopayment
```

### 2. Обновление обработки вебхуков
```python
# webhook_handlers.py
def verify_signature():
    # Вместо проверки подписи ЮКассы
    # Проверка подписи Prodamus
```

### 3. Изменение структуры метаданных
```python
# Вместо:
metadata = {
    "user_id": str(user_id),
    "sub_type": sub_type,
    "payment_label": payment_label,
    "days": str(days)
}

# Станет:
metadata = {
    "user_id": str(user_id),
    "sub_type": sub_type,
    "payment_label": payment_label,
    "days": str(days),
    "subscription": 1  # Флаг подписки для Prodamus
}
```

### 4. Обновление автопродления
```python
# process_subscription_auto_renewal()
# Вместо yookassa_payment_method_id
# Использовать prodamus_payment_method_id
```

---

## Риски и сложности

### 1. Миграция существующих подписок
- Пользователи с активными подписками на ЮКассе
- Необходимо сохранить их платежные методы или отключить автопродление

### 2. Тестирование
- Требуется тщательное тестирование всех сценариев
- Проверка обработки всех типов уведомлений Prodamus

### 3. Временные затраты
- Разработка: 5-7 дней
- Тестирование: 3-5 дней
- Миграция: 1-2 дня

---

## Заключение

**✅ РЕКОМЕНДАЦИЯ: Полная замена возможна и целесообразна**

### Преимущества перехода:
1. **Лучшая специализация** на подписках
2. **Более подробная аналитика** действий с подписками
3. **Гибкое управление** через REST API
4. **Специфические уведомления** для различных событий

### План реализации:
1. **Подготовка** - создание модуля payment_prodamus.py
2. **Параллельная работа** - A/B тестирование
3. **Полная миграция** - переключение всех платежей
4. **Мониторинг** - отслеживание проблем и их решение

### Ожидаемый результат:
- **Сохранение всего функционала** текущей системы
- **Улучшение аналитики** подписок
- **Упрощение управления** подписками через API
- **Повышение надежности** автоплатежей

**Рекомендуется начать миграцию после тщательного тестирования всех сценариев.**</content>
<parameter name="filePath">/Users/nikitasahanin/Desktop/momsclub/prodamus_migration_analysis.md
