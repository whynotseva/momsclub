"""
Обработчик досрочного продления подписки
"""

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id, get_active_subscription
from utils.early_renewal import (
    check_early_renewal_eligibility,
    format_subscription_status_message,
    format_renewal_options_message
)
from utils.constants import (
    SUBSCRIPTION_PRICE,
    SUBSCRIPTION_PRICE_2MONTHS,
    SUBSCRIPTION_PRICE_3MONTHS
)
import logging

logger = logging.getLogger(__name__)

early_renewal_router = Router()


@early_renewal_router.callback_query(F.data == "early_renewal")
async def process_early_renewal(callback: types.CallbackQuery):
    """
    Обработчик кнопки досрочного продления из личного кабинета
    """
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            
            # Проверяем возможность досрочного продления
            can_renew, reason, info = await check_early_renewal_eligibility(session, user.id)
            
            if not can_renew:
                await callback.answer(reason or "Продление недоступно", show_alert=True)
                return
            
            if not info:
                await callback.answer("Ошибка получения информации о подписке", show_alert=True)
                return
            
            # Формируем сообщение
            status_msg = format_subscription_status_message(
                info['days_left'],
                info['end_date'],
                info['has_autopay']
            )
            
            renewal_msg = format_renewal_options_message(
                info['end_date'],
                info['days_left'],
                info['bonus_eligible'],
                info['has_autopay']
            )
            
            full_message = f"{status_msg}\n\n{renewal_msg}"
            
            # Кнопки с тарифами
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"📦 1 месяц — {SUBSCRIPTION_PRICE}₽",
                        callback_data="payment_1month"
                    )],
                    [InlineKeyboardButton(
                        text=f"📦 2 месяца — {SUBSCRIPTION_PRICE_2MONTHS}₽ 💰",
                        callback_data="payment_2months"
                    )],
                    [InlineKeyboardButton(
                        text=f"📦 3 месяца — {SUBSCRIPTION_PRICE_3MONTHS}₽ 💰",
                        callback_data="payment_3months"
                    )],
                    [InlineKeyboardButton(
                        text="« Назад к управлению",
                        callback_data="manage_subscription"
                    )]
                ]
            )
            
            try:
                await callback.message.edit_text(
                    full_message,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка редактирования сообщения: {e}")
                await callback.message.answer(
                    full_message,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            
            await callback.answer()
            
    except Exception as e:
        logger.error(f"Ошибка в process_early_renewal: {e}", exc_info=True)
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)
