# 🎯 РЕФЕРАЛЬНАЯ СИСТЕМА 2.0 - TODO (ЧАСТЬ 1/3)

## ✅ ЭТАП 0: ПОДГОТОВКА
- [x] Создан бэкап: momsclub_backup_22112025 (1.5GB)
- [x] Составлен план

---

## 🗄️ ЭТАП 1: БАЗА ДАННЫХ

### 1.1 Модели (database/models.py)

**Новые поля в User (после строки 44):**
```python
# Реферальная система 2.0
referral_balance = Column(Integer, default=0)
total_referrals_paid = Column(Integer, default=0)
total_earned_referral = Column(Integer, default=0)
```

**ReferralReward (после FavoriteUser):**
```python
class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    id, referrer_id, referee_id, payment_amount
    reward_type, reward_amount, loyalty_level, bonus_percent
    created_at
```

**WithdrawalRequest (после ReferralReward):**
```python
class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"
    id, user_id, amount, payment_method, payment_details
    status, created_at, processed_at, admin_comment
```

### 1.2 Миграция
Файл: database/migrations/add_referral_system_v2.py
- ALTER TABLE users ADD COLUMN referral_balance...
- CREATE TABLE referral_rewards...
- CREATE TABLE withdrawal_requests...
- CREATE INDEX...

### 1.3 CRUD (database/crud.py)
- add_referral_balance(session, user_id, amount)
- deduct_referral_balance(session, user_id, amount)
- create_referral_reward(...)
- get_referral_rewards(session, user_id, limit=10)
- is_eligible_for_money_reward(session, user_id)
- create_withdrawal_request(...)
- get_withdrawal_requests(session, status=None)
- process_withdrawal_request(...)

---

## 🎁 ЭТАП 2: ВЫБОР НАГРАДЫ

### 2.0 НОВЫЕ ФАЙЛЫ (ЧИСТЫЙ КОД!)

**2.0.1 Создать `utils/referral_helpers.py`:**
- calculate_referral_bonus(amount, loyalty_level)
- format_balance_text(balance)
- mask_card_number(card)
- validate_card_number(card)
- validate_phone_number(phone)
- get_loyalty_emoji(level)
- get_loyalty_name(level)

**2.0.2 Создать `utils/referral_messages.py`:**
- get_reward_choice_text(...)
- get_money_reward_success_text(...)
- get_days_reward_success_text(...)
- get_withdrawal_request_created_text(...)
- get_referral_program_text(...)

### 2.1 Константы (utils/constants.py)
```python
REFERRAL_MONEY_PERCENT = {
    'none': 10, 'silver': 15, 'gold': 20, 'platinum': 20
}
MIN_WITHDRAWAL_AMOUNT = 500
```

### 2.2 Webhook (webhook_handlers.py)
Заменить логику реферального бонуса (строки 229-253):
- Импортировать helpers
- Рассчитать процент через calculate_referral_bonus()
- Вызвать send_referral_reward_choice(...)
- ⚠️ ВАЖНО: НЕ смешивать SQL и бизнес-логику!

### 2.3 Обработчики (handlers/user_handlers.py)
- ref_reward_money:{referee_id} → начислить деньги
- ref_reward_days:{referee_id} → начислить дни
- ⚠️ ВАЖНО: Обработчик < 50 строк, логику в helpers!

**ТЕКСТЫ ПУШЕЙ:**

1. Уведомление о выборе:
```
🎁 Отличные новости!

Пользователь @username оплатил подписку!

💰 Ваш бонус: 360₽ (15% 🥈)

Выберите награду:
[💰 Получить 360₽ на баланс]
[📅 Получить 7 дней подписки]
```

2. После выбора денег:
```
✅ Успешно зачислено!

💰 +360₽ на ваш реферальный баланс

📊 Текущий баланс: 740₽

Используйте баланс для оплаты подписки или выведите от 500₽ на карту!
```

3. После выбора дней:
```
✅ Успешно зачислено!

📅 +7 дней к вашей подписке

🗓 Новая дата окончания: 05.12.2025

Спасибо за участие в реферальной программе! 💖
```
