# Техническая документация по автоплатежам Prodamus

## Содержание
1. [Формирование ссылки на оплату](#формирование-ссылки-на-оплату)
2. [Управление клубным функционалом](#управление-клубным-функционалом)
3. [REST API методы](#rest-api-методы)
   - [Управление статусами подписки (setActivity)](#управление-статусами-подписки-setactivity)
   - [Установка даты следующего платежа (setSubscriptionPaymentDate)](#установка-даты-следующего-платежа-setsubscriptionpaymentdate)
4. [Завершение подписки](#завершение-подписки)
5. [Уведомления при автосписании](#уведомления-при-автосписании)
6. [Деактивация и повторная активация подписки](#деактивация-и-повторная-активация-подписки)
7. [Параметры URL-уведомления по подписке](#параметры-url-уведомления-по-подписке)
8. [Коды ошибок](#коды-ошибок)

---

## Формирование ссылки на оплату

Данные запроса для формирования ссылки на оплату передаются методом GET или POST в кодировке UTF-8 на URL-адрес платежной формы в системе Продамус.

**Адрес демо-формы:** https://demo.payform.ru

**Секретный ключ демо-формы:**
```
2y2aw4oknnke80bp1a8fniwuuq7tdkwmmuq7vwi4nzbr8z1182ftbn6p8mhw3bhz
```

Список доступных параметров можно найти на странице [инструкции для самостоятельной интеграции](https://help.prodamus.ru/payform/integracii/rest-api/instrukcii-dlya-samostoyatelnaya-integracii-servisov).

### Пример формирования ссылки на оплату:

```php
<?php

header('Content-type:text/plain;charset=utf-8');

$linktoform = 'https://demo.payform.ru/';

$data = [
    'order_id' => '',
    'customer_phone' => '+79278820060',
    'customer_email' => 'site_testing@prodamus.ru',
    'subscription' => 1,
    'vk_user_id' => 12345,
    'vk_user_name' => 'Фамилия Имя Отчество',
    'customer_extra' => '',
    'do' => 'link',
    'urlReturn' => 'https://demo.payform.ru/demo-return',
    'urlSuccess' => 'https://demo.payform.ru/demo-success',
    'sys' => 'getcourse',
    'discount_value' => 100.00,
    'link_expired' => '2021-01-01 00:00:00',
    'subscription_date_start' => '2021-01-01 00:00:00',
    'subscription_limit_autopayments' => 10
];

$link = file_get_contents($linktoform . '?' . http_build_query($data));
```

---

## Управление клубным функционалом

Управление клубным функционалом осуществляется при помощи методов [Rest API](https://help.prodamus.ru/payform/integracii/rest-api-1):

- [Управление статусами подписки](https://help.prodamus.ru/payform/integracii/rest-api-1/setactivity)
- [Управление скидкой по подписке](https://help.prodamus.ru/payform/integracii/rest-api-1/setsubscriptiondiscount)
- [Установка даты следующего платежа по подписке](https://help.prodamus.ru/payform/integracii/rest-api-1/setsubscriptionpaymentdate)

---

## REST API методы

### Управление статусами подписки (setActivity)

**setActivity** - данный метод служит для управления статусами (активация/деактивация) подписки.

**Endpoint:** `POST https://demo.payform.ru/rest/setActivity/`

Управление осуществляется от лица менеджера и пользователя:

> **Менеджер** - владелец платежной страницы
> 
> **Пользователь** - покупатель

Если решение по отключению подписки принято владельцем платежной страницы, то деактивация должна осуществляться от лица менеджера. А если отписку инициирует покупатель, то от лица пользователя.

После деактивации подписки от лица пользователя, активировать ее повторно не возможно.

Для возобновления доступа к подписке, пользователь может оформить ее повторно.

#### Пример запроса:

```php
header('Content-type:text/plain;charset=utf-8');

require_once __DIR__ . '/Hmac.php';

$url = 'https://demo.payform.ru/rest/setActivity/';
$secret_key = '2y2aw4oknnke80bp1a8fniwuuq7tdkwmmuq7vwi4nzbr8z1182ftbn6p8mhw3bhz';

$data = [
  'subscription' => 1,
  'vk_user_id' => 123,
  'active_manager' => 0
];

$data['signature'] = Hmac::create($data, $secret_key);

$ch = curl_init($url);

curl_setopt_array($ch, [
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_SSL_VERIFYHOST => false,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POSTFIELDS => http_build_query($data)
]);

$response = curl_exec($ch);
```

**Ответы:**
- `200` - Запрос успешно обработан (success)
- `400` - Не передана подпись запроса

### Установка даты следующего платежа (setSubscriptionPaymentDate)

**setSubscriptionPaymentDate** - данный метод предназначен для установки даты следующего платежа.

**Endpoint:** `POST https://demo.payform.ru/rest/setSubscriptionPaymentDate/`

С помощью данного метода можно сдвинуть дату следующего платежа по подписке. Сдвигать дату можно только "в будущее" относительно текущей установленной даты следующего платежа. Тем самым увеличивая срок пребывания в клубе.

Например, можно применять в качестве бонуса для подписчиков.

#### Пример запроса:

```php
header('Content-type:text/plain;charset=utf-8');

require_once __DIR__ . '/Hmac.php';

$url = 'https://demo.payform.ru/rest/setSubscriptionPaymentDate/';
$secret_key = '2y2aw4oknnke80bp1a8fniwuuq7tdkwmmuq7vwi4nzbr8z1182ftbn6p8mhw3bhz';

$data = [
  'subscription' => 1,
  'auth_type' => 'vk_user_id',
  'vk_user_id' => 123,
  'date' => '2021-12-31 23:59'
];

$data['signature'] = Hmac::create($data, $secret_key);

$ch = curl_init($url);

curl_setopt_array($ch, [
    CURLOPT_SSL_VERIFYPEER => false,
    CURLOPT_SSL_VERIFYHOST => false,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POSTFIELDS => http_build_query($data)
]);

$response = curl_exec($ch);
```

**Ответы:**
- `200` - Запрос успешно обработан (success)
- `400` - Не передана подпись запроса

---

## Завершение подписки

Завершенная подписка - это подписка с истекшим оплаченным периодом, по которой не возможно совершить очередное продление.

Продление подписки не возможно в следующих случаях:

- для подписки установлено максимальное количество автосписаний и было совершено последнее списание
- подписка была деактивирована менеджером/пользователем
- после нескольких попыток не удалось списать деньги с карты пользователя

### Примеры завершения подписки:

#### Вариант 1
- клиент оформил месячную подписку, по которой предполагается 5 продлений
- с интервалом в 30 дней было произведено 5 автосписаний (продление подписки)
- наступает дата очередного продления подписки
- подписка завершается, т.к. 5 продлений уже были выполнены

#### Вариант 2
- клиент оформил подписку
- клиент или менеджер деактивирует подписку
- отправляется уведомление о деактивации подписки
- наступает дата очередного продления подписки
- подписка завершается, т.к. она была деактивирована

#### Вариант 3
- клиент оформил подписку (для подписок установлено 3 попытки списания при неудаче)
- наступает дата очередного продления подписки
- было предпринято 3 неудачные попытки списания
- подписка завершается, т.к. была последняя попытка списания

Управление завершенными подписками не допускается. Например, в ЛК, вместо переключателей статусов подписки, будет отображен статус "Завершена", а при попытке изменить данные через REST API будет получен ответ со следующей ошибкой:

```
subscription {id} completed, data modification is prohibited
```

При завершении подписки будет отправлено уведомление на почту клиенту и менеджерам, а так же веб-хук, на URL-адрес, указанный в настройках подписок ЛК.

### Примеры веб-хуков при завершении подписки:

#### Совершено максимальное количество автосписаний:

```php
Array
(
    [date] => 2020-07-17T18:22:02+03:00
    [order_id] => 0
    [order_num] => 
    [domain] => demo.payform.ru
    [sum] => 1.00
    [customer_phone] => +79999999999
    [payment_type] => Автоплатеж
    [attempt] => 1
    [discount_value] => 0.00
    [subscription] => Array
        (
            [type] => action
            [action_code] => finish
            [action_reason] => completed
            [date] => 2020-07-17 18:21
            [id] => 593600
            [active] => 1
            [active_manager] => 1
            [active_user] => 1
            [cost] => 1.00
            [name] => Доступ в клуб "Девелопер клаб" – тестовая подписка
            [limit_autopayments] => 3
            [autopayments_num] => 3
            [first_payment_discount] => 0.00
            [next_payment_discount] => 0.00
            [next_payment_discount_num] => 
            [date_create] => 2020-03-16 12:42:32
            [date_first_payment] => 2020-03-17 12:42:32
            [date_last_payment] => 2020-06-17 14:40:53
            [date_next_payment] => 
            [date_next_payment_discount] => 
            [current_attempt] => 1
            [payment_num] => 4
            [autopayment] => 1
        )
)
```

#### Завершение деактивированной подписки:

```php
Array
(
    [date] => 2020-07-17T18:22:02+03:00
    [order_id] => 0
    [order_num] => 
    [domain] => demo.payform.ru
    [sum] => 1.00
    [customer_phone] => +79999999999
    [payment_type] => Автоплатеж
    [attempt] => 1
    [discount_value] => 0.00
    [subscription] => Array
        (
            [type] => action
            [action_code] => finish
            [action_reason] => deactivated
            [date] => 2020-07-17 18:21
            [id] => 593600
            [active] => 0
            [active_manager] => 1
            [active_user] => 0
            [cost] => 1.00
            [name] => Доступ в клуб "Девелопер клаб" – тестовая подписка
            [limit_autopayments] => 3
            [autopayments_num] => 3
            [first_payment_discount] => 0.00
            [next_payment_discount] => 0.00
            [next_payment_discount_num] => 
            [date_create] => 2020-03-16 12:42:32
            [date_first_payment] => 2020-03-17 12:42:32
            [date_last_payment] => 2020-06-17 14:40:53
            [date_next_payment] => 
            [date_next_payment_discount] => 
            [current_attempt] => 1
            [payment_num] => 4
            [autopayment] => 1
        )
)
```

#### При очередном продлении, не удалось списать деньги со счета клиента (достигнут лимит попыток списания):

```php
Array
(
    [date] => 2020-07-17T18:31:02+03:00
    [order_id] => 287190
    [order_num] => тест
    [domain] => demo.payform.ru
    [sum] => 1.00
    [customer_phone] => +79999999999
    [payment_type] => Автоплатеж
    [attempt] => 1
    [discount_value] => 0.00
    [subscription] => Array
        (
            [type] => action
            [action_code] => deactivation
            [error_code] => insufficient_funds
            [error] => Недостаточно средств
            [last_attempt] => yes
            [attempt_num] => 2
            [payment_date] => 2020-07-17 18:30:44
            [id] => 593600
            [active] => 0
            [active_manager] => 0
            [active_user] => 1
            [cost] => 1.00
            [name] => Доступ в клуб "Девелопер клаб" – тестовая подписка
            [limit_autopayments] => 
            [autopayments_num] => 3
            [first_payment_discount] => 0.00
            [next_payment_discount] => 0.00
            [next_payment_discount_num] => 
            [date_create] => 2020-03-16 12:42:32
            [date_first_payment] => 2020-03-17 12:42:32
            [date_last_payment] => 2020-06-17 14:40:53
            [date_next_payment] => 
            [date_next_payment_discount] => 
            [current_attempt] => 1
            [payment_num] => 4
        )
)
```

---

## Уведомления при автосписании

При автосписании по подписке будут отправлены следующие типы уведомлений:

- веб-хук на URL адрес, указанный на странице настроек платежной формы, в блоке "Настройка уведомлений"
- e-mail уведомление на адреса менеджеров, указанных на странице настроек подписок, в блоке "Общие настройки"

### Пример URL уведомления:

**Заголовок:**
```
Sign: b20d453561eccafb6874d95a986449f2185df25e3f0237319976df6d788342e6
```

**Тело запроса:**
```php
array (
  'date' => '2020-07-27T12:36:02+03:00',
  'order_id' => '300169',
  'order_num' => '',
  'domain' => 'demo.payform.ru',
  'sum' => '100.00',
  'customer_phone' => '+79999999999',
  'customer_email' => 'test@domain.ru',
  'customer_extra' => '',
  'payment_type' => 'Автоплатеж',
  'attempt' => '1',
  'commission' => '3.9',
  'commission_sum' => '0.04',
  'discount_value' => '0.00',
  'subscription' => 
  array (
    'type' => 'action',
    'action_code' => 'auto_payment',
    'payment_date' => '2020-07-27 12:35',
    'id' => '593600',
    'active' => '1',
    'active_manager' => '1',
    'active_user' => '1',
    'cost' => '100.00',
    'name' => 'Доступ в клуб "Девелопер клаб" – тестовая подписка',
    'limit_autopayments' => '',
    'autopayments_num' => '1',
    'first_payment_discount' => '0.00',
    'next_payment_discount' => '0.00',
    'next_payment_discount_num' => '',
    'date_create' => '2020-07-23 20:38:57',
    'date_first_payment' => '2020-06-27 20:38:57',
    'date_last_payment' => '2020-07-27 12:35:08',
    'date_next_payment' => '2020-08-25 12:30:37',
    'date_next_payment_discount' => '2020-07-23 20:38:57',
    'current_attempt' => '1',
    'payment_num' => '2',
    'autopayment' => '1',
  ),
)
```

---

## Деактивация и повторная активация подписки

Если подписка была деактивирована менеджером или пользователем, будут отправлены следующие типы уведомлений:

- веб-хук на URL адрес, указанный на странице настроек платежной формы, в блоке "Настройка уведомлений"
- e-mail уведомление на адреса менеджеров, указанных на странице настроек подписок, в блоке "Общие настройки"

При этом, если подписка была повторно активирована менеджером или пользователем до наступления следующей плановой даты списания, будут отправлены те же типы уведомлений с данными о повторной активации подписки.

### Пример URL уведомления о деактивации подписки:

```php
$_POST = Array
(
    [date] => 2024-09-01T00:00:00+03:00
    [order_id] => 0
    [order_num] => 9999999999
    [domain] => testingqa.payform.ru
    [sum] => 50.00
    [currency] => rub
    [customer_phone] => +79999999997
    [customer_email] => test.subscribtion@prodamus.ru
    [customer_extra] => 
    [payment_type] => Автоплатеж
    [attempt] => 1
    [discount_value] => 0.00
    [subscription] => Array
        (
            [type] => action
            [action_code] => deactivation
            [action_reason] => deactivated
            [date] => 2024-08-28 15:14
            [id] => 1000000
            [active] => 1
            [active_manager] => 1
            [active_user] => 1
            [cost] => 50.00
            [name] => Тестовая подписка
            [limit_autopayments] => 3
            [autopayments_num] => 0
            [first_payment_discount] => 0.00
            [next_payment_discount] => 0.00
            [next_payment_discount_num] => 
            [date_create] => 2024-09-01 00:00:42
            [date_first_payment] => 2024-09-01 00:00:42
            [date_last_payment] => 2024-09-01 00:00:42
            [date_next_payment] => 2024-10-27 00:00:42
            [date_next_payment_discount] =>2024-09-01 00:00:42
            [current_attempt] => 1
            [payment_num] => 1
            [autopayment] => 1
        )
)
```

### Пример URL уведомления о повторной активации подписки:

```php
$_POST = Array
(
    [date] => 2024-09-01T00:00:00+03:00
    [order_id] => 0
    [order_num] => 9999999999
    [domain] => testingqa.payform.ru
    [sum] => 50.00
    [currency] => rub
    [customer_phone] => +79999999997
    [customer_email] => test.subscribtion@prodamus.ru
    [customer_extra] => 
    [payment_type] => Автоплатеж
    [attempt] => 1
    [discount_value] => 0.00
    [subscription] => Array
        (
            [type] => action
            [action_code] => reactivation
            [action_reason] => reactivated
            [date] => 2024-09-01 00:00
            [id] => 1000000
            [active] => 0
            [active_manager] => 0
            [active_user] => 1
            [cost] => 50.00
            [name] => Тестовая подписка
            [limit_autopayments] => 3
            [autopayments_num] => 0
            [first_payment_discount] => 0.00
            [next_payment_discount] => 0.00
            [next_payment_discount_num] => 
            [date_create] =>2024-09-01 15:08:42
            [date_first_payment] => 2024-09-01 00:00:42
            [date_last_payment] => 2024-09-01 00:00:42
            [date_next_payment] => 2024-10-27 00:00:42
            [date_next_payment_discount] => 2024-09-01 00:00:42
            [current_attempt] => 1
            [payment_num] => 1
            [autopayment] => 1
        )
)
```

---

## Параметры URL-уведомления по подписке

URL-уведомления по подпискам отличаются от уведомлений по обычным платежам только наличием блока subscription.

Все параметры кроме subscription описаны в разделе [Уведомления](https://help.prodamus.ru/payform/uvedomleniya).

### Описание параметров subscription:

| Параметр | Описание |
|----------|----------|
| type | Тип действия |
| action_code | Код действия |
| action_reason | Причина действия |
| date | Дата |
| id | ID подписки |
| active | Активность подписки |
| active_manager | Активность от менеджера |
| active_user | Активность от пользователя |
| cost | Стоимость |
| name | Название подписки |
| limit_autopayments | Лимит автоплатежей |
| autopayments_num | Количество автоплатежей |
| first_payment_discount | Скидка первого платежа |
| next_payment_discount | Скидка следующего платежа |
| next_payment_discount_num | Номер следующего платежа со скидкой |
| date_create | Дата создания |
| date_first_payment | Дата первого платежа |
| date_last_payment | Дата последнего платежа |
| date_next_payment | Дата следующего платежа |
| date_next_payment_discount | Дата следующего платежа со скидкой |
| current_attempt | Текущая попытка |
| payment_num | Номер платежа |
| autopayment | Флаг автоплатежа |

---

## Коды ошибок

| Код ошибки | Описание |
|------------|----------|
| insufficient_funds | Недостаточно средств |
| card_expired | Карта просрочена |
| invalid_card | Неверная карта |
| transaction_declined | Транзакция отклонена |
| payment_limit_exceeded | Превышен лимит платежа |
| subscription_completed | Подписка завершена |
| subscription_deactivated | Подписка деактивирована |

---

**Информация носит исключительно справочный характер и не является офертой. С актуальной редакцией оферты и тарифами можно ознакомиться в разделе [Документы](https://prodamus.ru/documents).**

---

*Документация собрана с официального сайта help.prodamus.ru*
