from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import logging
from datetime import datetime
from utils.constants import ADMIN_IDS
from utils.admin_permissions import is_admin
from database.crud import get_user_by_telegram_id
from utils.helpers import html_kv
from database.config import AsyncSessionLocal
from database.crud import get_sorted_active_subscriptions

logger = logging.getLogger(__name__)

# Импортируем из общих констант и helpers
from utils.constants import LIFETIME_THRESHOLD, LIFETIME_SUBSCRIPTION_GROUP
from utils.helpers import is_lifetime_subscription

subscriptions_router = Router()

SUBSCRIPTIONS_PAGE_SIZE = 10


class AdminSubscriptionStates(StatesGroup):
    viewing_page = State()


def register_admin_subscriptions_handlers(dp):
    dp.include_router(subscriptions_router)


@subscriptions_router.callback_query(F.data.startswith("admin_subscription_dates"))
async def process_subscription_dates(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[subscriptions] admin_subscription_dates: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    parts = callback.data.split(":")
    try:
        page = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        page = 0

    await state.set_state(AdminSubscriptionStates.viewing_page)
    await state.update_data(current_page=page)

    async with AsyncSessionLocal() as session:
        subscriptions_data = await get_sorted_active_subscriptions(session)

    total_items = len(subscriptions_data)
    total_pages = max(1, (total_items + SUBSCRIPTIONS_PAGE_SIZE - 1) // SUBSCRIPTIONS_PAGE_SIZE)
    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0

    start_idx = page * SUBSCRIPTIONS_PAGE_SIZE
    end_idx = min(start_idx + SUBSCRIPTIONS_PAGE_SIZE, total_items)
    current_items = subscriptions_data[start_idx:end_idx]

    now = datetime.now()
    if not current_items:
        message_text = "<b>📅 Активные подписки</b>\n\nАктивных подписок не найдено."
    else:
        lines = ["<b>📅 Активные подписки</b>", ""]
        for i, (user, subscription) in enumerate(current_items, 1):
            user_name = user.first_name or ""
            if user.last_name:
                user_name += f" {user.last_name}"
            if user.username:
                user_name += f" (@{user.username})"
            if not user_name.strip():
                user_name = f"ID: {user.telegram_id}"
            
            if is_lifetime_subscription(subscription):
                lines.append(f"∞ {start_idx + i}. <b>{user_name}</b>")
                lines.append(html_kv("📅 Статус", "∞ Пожизненная подписка") + "\n")
            else:
                days_left = (subscription.end_date - now).days
                expiring_soon = "🔴 " if days_left <= 7 else "🟢 "
                date_formatted = subscription.end_date.strftime("%d.%m.%Y")
                lines.append(f"{expiring_soon}{start_idx + i}. <b>{user_name}</b>")
                lines.append(html_kv("📅 Дата окончания", date_formatted))
                lines.append(html_kv("⏱ Осталось дней", str(days_left)) + "\n")
        message_text = "\n".join(lines)

    inline_kb = []
    pagination = []
    if page > 0:
        pagination.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_subscription_dates:{page-1}"))
    if page < total_pages - 1:
        pagination.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_subscription_dates:{page+1}"))
    if pagination:
        inline_kb.append(pagination)
    if total_pages > 1:
        inline_kb.append([InlineKeyboardButton(text=f"Страница {page+1}/{total_pages}", callback_data="ignore")])

    inline_kb.append([InlineKeyboardButton(text="📊 Экспорт в Excel", callback_data="admin_export_subscriptions")])
    inline_kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_subscription_dates:{page}")])
    inline_kb.append([InlineKeyboardButton(text="« Назад", callback_data="admin_back")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_kb)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")


@subscriptions_router.callback_query(F.data == "admin_export_subscriptions")
async def export_subscriptions(callback: CallbackQuery):
    logger.info(f"[subscriptions] admin_export_subscriptions by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    await callback.answer("Подготовка экспорта...")

    async with AsyncSessionLocal() as session:
        subscriptions_data = await get_sorted_active_subscriptions(session)
    if not subscriptions_data:
        await callback.message.answer("Нет активных подписок для экспорта.")
        return

    import pandas as pd
    import os
    data = []
    now = datetime.now()
    for user, subscription in subscriptions_data:
        days_left = (subscription.end_date - now).days
        user_name = user.first_name or ""
        if user.last_name:
            user_name += f" {user.last_name}"
        data.append({
            "ID пользователя": user.telegram_id,
            "Имя пользователя": user_name,
            "Username": f"@{user.username}" if user.username else "",
            "Дата окончания": subscription.end_date.strftime("%d.%m.%Y"),
            "Осталось дней": days_left,
            "Статус": "Скоро истекает" if days_left <= 7 else "Активна"
        })

    df = pd.DataFrame(data)
    from datetime import datetime as dt
    filename = f"exports/subscriptions_{dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    os.makedirs("exports", exist_ok=True)
    df.to_excel(filename, index=False)
    doc = FSInputFile(filename)
    await callback.message.answer_document(document=doc, caption="📊 Экспорт данных о подписках")