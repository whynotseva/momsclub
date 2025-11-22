"""
Обработчики для модерации заявок на вывод реферальных средств
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.config import AsyncSessionLocal
from database.crud import (
    get_withdrawal_requests,
    process_withdrawal_request,
    get_user_by_telegram_id,
    get_user_by_id
)
from utils.admin_permissions import is_admin
import logging

logger = logging.getLogger(__name__)
withdrawals_router = Router()


class WithdrawalRejectionStates(StatesGroup):
    """Состояния FSM для отклонения заявки на вывод"""
    waiting_reason = State()


def register_admin_withdrawals_handlers(dp):
    """Регистрирует обработчики модерации выводов"""
    dp.include_router(withdrawals_router)


@withdrawals_router.callback_query(F.data == "admin_withdrawals")
async def show_withdrawal_requests(callback: CallbackQuery):
    """Показывает список заявок на вывод"""
    try:
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
            
            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                # Если не получилось отредактировать (сообщение с картинкой)
                await callback.message.delete()
                await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в show_withdrawal_requests: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@withdrawals_router.callback_query(F.data.startswith("admin_withdrawal_view:"))
async def view_withdrawal_request(callback: CallbackQuery):
    """Показывает детали заявки на вывод"""
    try:
        withdrawal_id = int(callback.data.split(":")[1])
        
        async with AsyncSessionLocal() as session:
            from database.models import WithdrawalRequest
            withdrawal = await session.get(WithdrawalRequest, withdrawal_id)
            
            if not withdrawal:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return
            
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
            
            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                # Если не получилось отредактировать (сообщение с картинкой)
                await callback.message.delete()
                await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в view_withdrawal_request: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@withdrawals_router.callback_query(F.data.startswith("admin_withdrawal_approve:"))
async def approve_withdrawal(callback: CallbackQuery):
    """Одобряет заявку на вывод"""
    try:
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
                
                from utils.referral_messages import get_withdrawal_approved_text
                text = get_withdrawal_approved_text(withdrawal.amount, withdrawal.payment_details)
                
                try:
                    await callback.bot.send_message(
                        user.telegram_id,
                        text,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {user.telegram_id}: {e}")
                
                await callback.answer("✅ Заявка одобрена", show_alert=True)
            else:
                await callback.answer("❌ Ошибка при обработке", show_alert=True)
        
        # Возвращаемся к списку заявок
        await show_withdrawal_requests(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в approve_withdrawal: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@withdrawals_router.callback_query(F.data.startswith("admin_withdrawal_reject:"))
async def reject_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Запрашивает причину отклонения заявки"""
    try:
        withdrawal_id = int(callback.data.split(":")[1])
        
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, callback.from_user.id)
            if not is_admin(admin):
                await callback.answer("❌ Нет доступа", show_alert=True)
                return
            
            # Получаем заявку
            from database.models import WithdrawalRequest
            withdrawal = await session.get(WithdrawalRequest, withdrawal_id)
            
            if not withdrawal:
                await callback.answer("❌ Заявка не найдена", show_alert=True)
                return
            
            user = await get_user_by_id(session, withdrawal.user_id)
            
            # Сохраняем данные в state
            await state.update_data(
                withdrawal_id=withdrawal_id,
                user_telegram_id=user.telegram_id,
                amount=withdrawal.amount
            )
            
            # Запрашиваем причину
            text = f"❌ <b>Отклонение заявки на вывод</b>\n\n"
            text += f"💰 Сумма: {withdrawal.amount:,}₽\n"
            text += f"👤 Пользователь: {user.first_name or 'Без имени'}\n\n"
            text += f"Введите причину отклонения:\n"
            text += f"Например: <code>Неверные реквизиты</code>, <code>Недостаточно средств</code>, <code>Подозрительная активность</code>"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data="admin_withdrawals")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await state.set_state(WithdrawalRejectionStates.waiting_reason)
            
    except Exception as e:
        logger.error(f"Ошибка в reject_withdrawal: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@withdrawals_router.message(WithdrawalRejectionStates.waiting_reason)
async def process_rejection_reason(message: Message, state: FSMContext):
    """Обрабатывает введенную причину отклонения"""
    try:
        reason = message.text.strip()
        
        if len(reason) < 3:
            await message.answer("❌ Причина слишком короткая. Введите более подробную причину:")
            return
        
        if len(reason) > 500:
            await message.answer("❌ Причина слишком длинная (макс. 500 символов). Сократите:")
            return
        
        # Получаем данные
        data = await state.get_data()
        withdrawal_id = data['withdrawal_id']
        user_telegram_id = data['user_telegram_id']
        amount = data['amount']
        
        async with AsyncSessionLocal() as session:
            admin = await get_user_by_telegram_id(session, message.from_user.id)
            
            # Отклоняем заявку
            success = await process_withdrawal_request(
                session,
                withdrawal_id,
                admin.id,
                'rejected',
                admin_comment=reason
            )
            
            if success:
                # Уведомляем пользователя
                from utils.referral_messages import get_withdrawal_rejected_text
                text = get_withdrawal_rejected_text(amount, reason)
                
                try:
                    await message.bot.send_message(
                        user_telegram_id,
                        text,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {user_telegram_id}: {e}")
                
                await message.answer(
                    f"✅ <b>Заявка отклонена</b>\n\n"
                    f"💰 Сумма: {amount:,}₽\n"
                    f"📝 Причина: {reason}\n\n"
                    f"Пользователь уведомлен.",
                    parse_mode="HTML"
                )
            else:
                await message.answer("❌ Ошибка при обработке заявки")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в process_rejection_reason: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка")
        await state.clear()
