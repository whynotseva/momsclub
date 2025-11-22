# 🎯 РЕФЕРАЛЬНАЯ СИСТЕМА 2.0 - TODO (ЧАСТЬ 2/3)

## 💼 ЭТАП 3: ЛИЧНЫЙ КАБИНЕТ РЕФЕРАЛЬНОЙ ПРОГРАММЫ

### 3.1 Обновить handlers/user_handlers.py

**process_referral_program (строки 2678-2755):**

Заменить текст на:
```python
text = f"""🤝 <b>Реферальная программа</b>

💰 <b>Ваш баланс:</b> {user.referral_balance:,}₽
📊 <b>Всего заработано:</b> {user.total_earned_referral:,}₽
👥 <b>Приглашено друзей:</b> {total_referrals}
💳 <b>Оплатили подписку:</b> {user.total_referrals_paid}

📈 <b>Ваш уровень:</b> {level_name} ({bonus_percent}%)

💡 <b>Как это работает:</b>
1️⃣ Отправьте свою реферальную ссылку друзьям
2️⃣ Когда друг перейдет по ссылке и оформит подписку
3️⃣ Вы получите выбор: <b>деньги ({bonus_percent}%)</b> или <b>7 дней</b> к подписке 🎁

🔗 <b>Ваша реферальная ссылка:</b>
<code>{referral_link}</code>

Нажмите кнопку ниже, чтобы поделиться ссылкой! 💌"""
```

Обновить клавиатуру:
```python
keyboard_buttons = [
    [InlineKeyboardButton(text="📤 Поделиться ссылкой", switch_inline_query=f"...")],
    [InlineKeyboardButton(text="💸 Вывести средства", callback_data="ref_withdraw")]
    if user.referral_balance >= MIN_WITHDRAWAL_AMOUNT else [],
    [InlineKeyboardButton(text="📊 История начислений", callback_data="ref_history")],
    [InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")]
]
```

### 3.2 История начислений

**Новый обработчик ref_history:**
```python
@user_router.callback_query(F.data == "ref_history")
async def process_referral_history(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        rewards = await get_referral_rewards(session, user.id, limit=10)
        
        if not rewards:
            text = "📊 <b>История начислений</b>\n\nУ вас пока нет начислений"
        else:
            text = "📊 <b>История начислений</b>\n\n"
            for reward, referee in rewards:
                referee_name = referee.username or referee.first_name or f"ID:{referee.telegram_id}"
                reward_icon = "💰" if reward.reward_type == "money" else "📅"
                amount_text = f"{reward.reward_amount:,}₽" if reward.reward_type == "money" else f"{reward.reward_amount}д"
                
                text += f"{reward_icon} <b>{amount_text}</b> от @{referee_name}\n"
                text += f"   {reward.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Назад", callback_data="referral_program")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
```

---

## 💸 ЭТАП 4: ВЫВОД СРЕДСТВ

### 4.1 FSM состояния (handlers/user_handlers.py)

```python
class WithdrawalStates(StatesGroup):
    waiting_payment_method = State()
    waiting_card_number = State()
    waiting_phone_number = State()
    waiting_confirmation = State()
```

### 4.2 Начало вывода

**Обработчик ref_withdraw:**
```python
@user_router.callback_query(F.data == "ref_withdraw")
async def start_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        if user.referral_balance < MIN_WITHDRAWAL_AMOUNT:
            await callback.answer(
                f"❌ Минимальная сумма для вывода: {MIN_WITHDRAWAL_AMOUNT}₽",
                show_alert=True
            )
            return
        
        text = f"""💸 <b>Вывод средств</b>

💰 Доступно к выводу: {user.referral_balance:,}₽
⚠️ Минимальная сумма: {MIN_WITHDRAWAL_AMOUNT}₽
⏰ Срок зачисления: от 1 часа до 5 дней

Выберите способ вывода:"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Банковская карта", callback_data="withdraw_card")],
            [InlineKeyboardButton(text="📱 СБП (по номеру телефона)", callback_data="withdraw_sbp")],
            [InlineKeyboardButton(text="« Отмена", callback_data="referral_program")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
```

### 4.3 Выбор карты

**Обработчик withdraw_card:**
```python
@user_router.callback_query(F.data == "withdraw_card")
async def choose_card_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        await state.update_data(payment_method="card", user_balance=user.referral_balance)
    
    await callback.message.delete()
    await callback.message.answer(
        "💳 <b>Вывод на банковскую карту</b>\n\n"
        "Введите номер карты (16 цифр):\n\n"
        "Например: <code>1234567812345678</code>\n\n"
        "Или нажмите /cancel для отмены",
        parse_mode="HTML"
    )
    await state.set_state(WithdrawalStates.waiting_card_number)
```

### 4.4 Ввод номера карты

**Обработчик ввода карты:**
```python
@user_router.message(WithdrawalStates.waiting_card_number)
async def process_card_number(message: types.Message, state: FSMContext):
    card_number = message.text.strip().replace(" ", "")
    
    # Валидация
    if not card_number.isdigit() or len(card_number) != 16:
        await message.answer(
            "❌ Неверный формат номера карты\n\n"
            "Введите 16 цифр без пробелов:"
        )
        return
    
    data = await state.get_data()
    balance = data['user_balance']
    
    # Маскируем номер карты
    masked_card = f"{card_number[:4]} **** **** {card_number[-4:]}"
    
    await state.update_data(card_number=card_number)
    
    text = f"""💳 <b>Подтверждение вывода</b>

💰 Сумма: {balance:,}₽
📇 Карта: <code>{masked_card}</code>

⚠️ Заявка будет отправлена на модерацию администраторам.
⏰ Средства поступят от 1 часа до 5 дней.

Подтвердите вывод:"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_withdrawal")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_withdrawal")]
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(WithdrawalStates.waiting_confirmation)
```

### 4.5 Подтверждение вывода

**Обработчик confirm_withdrawal:**
```python
@user_router.callback_query(F.data == "confirm_withdrawal")
async def confirm_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    payment_method = data.get('payment_method')
    payment_details = data.get('card_number') or data.get('phone_number')
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        success = await create_withdrawal_request(
            session,
            user.id,
            user.referral_balance,
            payment_method,
            payment_details
        )
        
        if success:
            await callback.message.edit_text(
                "✅ <b>Заявка создана!</b>\n\n"
                f"💰 Сумма: {user.referral_balance:,}₽\n"
                f"📇 Реквизиты: {payment_details}\n\n"
                "📋 Ваша заявка отправлена на модерацию.\n"
                "⏰ Средства поступят от 1 часа до 5 дней.\n\n"
                "Вы получите уведомление о результате! 💌",
                parse_mode="HTML"
            )
            
            # Уведомление админам
            await notify_admins_about_withdrawal(callback.bot, user, user.referral_balance, payment_details)
        else:
            await callback.answer("❌ Ошибка при создании заявки", show_alert=True)
    
    await state.clear()
```

### 4.6 СБП аналогично
Обработчики withdraw_sbp и waiting_phone_number по аналогии с картой

---

## 👨‍💼 ЭТАП 5: АДМИНКА - МОДЕРАЦИЯ ВЫВОДОВ

### 5.1 Новый файл handlers/admin/withdrawals.py

```python
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import (
    get_withdrawal_requests,
    process_withdrawal_request,
    get_user_by_telegram_id,
    get_user_by_id
)
from utils.admin_permissions import is_admin, can_manage_admins
import logging

logger = logging.getLogger(__name__)
withdrawals_router = Router()

def register_admin_withdrawals_handlers(dp):
    dp.include_router(withdrawals_router)

@withdrawals_router.callback_query(F.data == "admin_withdrawals")
async def show_withdrawal_requests(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        admin = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(admin):
            await callback.answer("❌ Нет доступа", show_alert=True)
            return
        
        # Получаем ожидающие заявки
        pending = await get_withdrawal_requests(session, status='pending')
        
        text = "💸 <b>Заявки на вывод средств</b>\n\n"
        
        if not pending:
            text += "📋 Нет ожидающих заявок"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_withdrawals")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
            ])
        else:
            text += f"📋 Ожидают обработки: {len(pending)}\n\n"
            
            keyboard_buttons = []
            for withdrawal, user in pending[:10]:
                user_info = user.username or user.first_name or f"ID:{user.telegram_id}"
                btn_text = f"💰 {withdrawal.amount:,}₽ - @{user_info}"
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text=btn_text,
                        callback_data=f"admin_withdrawal_view:{withdrawal.id}"
                    )
                ])
            
            keyboard_buttons.append([
                InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_withdrawals")
            ])
            keyboard_buttons.append([
                InlineKeyboardButton(text="« Назад", callback_data="admin_back")
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@withdrawals_router.callback_query(F.data.startswith("admin_withdrawal_view:"))
async def view_withdrawal_request(callback: CallbackQuery):
    withdrawal_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        from database.models import WithdrawalRequest
        withdrawal = await session.get(WithdrawalRequest, withdrawal_id)
        user = await get_user_by_id(session, withdrawal.user_id)
        
        method_text = "💳 Карта" if withdrawal.payment_method == "card" else "📱 СБП"
        
        text = f"""💸 <b>Заявка #{withdrawal.id}</b>

👤 <b>Пользователь:</b> {user.first_name or 'Без имени'}
📱 @{user.username or 'без username'} (ID: {user.telegram_id})

💰 <b>Сумма:</b> {withdrawal.amount:,}₽
{method_text} <b>Реквизиты:</b> <code>{withdrawal.payment_details}</code>

📅 <b>Создана:</b> {withdrawal.created_at.strftime('%d.%m.%Y %H:%M')}
📊 <b>Статус:</b> {withdrawal.status}

Одобрить заявку?"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"admin_withdrawal_approve:{withdrawal_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_withdrawal_reject:{withdrawal_id}")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_withdrawals")]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

@withdrawals_router.callback_query(F.data.startswith("admin_withdrawal_approve:"))
async def approve_withdrawal(callback: CallbackQuery):
    withdrawal_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        admin = await get_user_by_telegram_id(session, callback.from_user.id)
        
        success = await process_withdrawal_request(
            session,
            withdrawal_id,
            admin.id,
            'approved',
            admin_comment="Одобрено"
        )
        
        if success:
            # Уведомляем пользователя
            from database.models import WithdrawalRequest
            withdrawal = await session.get(WithdrawalRequest, withdrawal_id)
            user = await get_user_by_id(session, withdrawal.user_id)
            
            await callback.bot.send_message(
                user.telegram_id,
                f"✅ <b>Заявка на вывод одобрена!</b>\n\n"
                f"💰 Сумма: {withdrawal.amount:,}₽\n"
                f"📇 Реквизиты: {withdrawal.payment_details}\n\n"
                f"⏰ Средства поступят от 1 часа до 5 дней! 💌",
                parse_mode="HTML"
            )
            
            await callback.answer("✅ Заявка одобрена", show_alert=True)
        else:
            await callback.answer("❌ Ошибка при обработке", show_alert=True)
    
    await show_withdrawal_requests(callback)

@withdrawals_router.callback_query(F.data.startswith("admin_withdrawal_reject:"))
async def reject_withdrawal(callback: CallbackQuery):
    # Аналогично approve, но со статусом 'rejected'
    pass
```

### 5.2 Добавить в админ меню

**handlers/admin/core.py (функция _admin_menu_keyboard):**
```python
# После кнопки "Автопродления"
keyboard_buttons.append([
    InlineKeyboardButton(text="💸 Заявки на вывод", callback_data="admin_withdrawals")
])
```

### 5.3 Регистрация роутера

**bot.py:**
```python
from handlers.admin.withdrawals import register_admin_withdrawals_handlers

# В функции main() после других регистраций:
register_admin_withdrawals_handlers(dp)
```
