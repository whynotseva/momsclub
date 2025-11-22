from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import logging
from datetime import datetime
from utils.constants import ADMIN_IDS
from utils.admin_permissions import is_admin
from database.crud import (
    get_user_by_telegram_id,
    get_sorted_active_subscriptions,
    extend_subscription,
    get_active_subscription,
    is_favorite,
    add_to_favorites,
    remove_from_favorites
)
from utils.helpers import html_kv
from database.config import AsyncSessionLocal

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
        filter_type = parts[2] if len(parts) > 2 else "all"  # all, urgent (1-5д), warning (7-14д)
    except Exception:
        page = 0
        filter_type = "all"

    await state.set_state(AdminSubscriptionStates.viewing_page)
    await state.update_data(current_page=page, filter_type=filter_type)

    async with AsyncSessionLocal() as session:
        subscriptions_data = await get_sorted_active_subscriptions(session)
    
    # Фильтрация
    now = datetime.now()
    from utils.helpers import is_lifetime_subscription
    
    if filter_type != "all":
        filtered_data = []
        for user, subscription in subscriptions_data:
            if not is_lifetime_subscription(subscription):
                days_left = (subscription.end_date - now).days
                
                if filter_type == "urgent" and days_left <= 5:
                    filtered_data.append((user, subscription))
                elif filter_type == "warning" and 7 <= days_left <= 14:
                    filtered_data.append((user, subscription))
        
        subscriptions_data = filtered_data

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
    
    # Заголовок с активным фильтром
    filter_names = {
        "all": "Все",
        "urgent": "⚠️ 1-5 дней",
        "warning": "📅 7-14 дней"
    }
    
    message_text = f"<b>📅 Активные подписки</b> (стр. {page+1}/{total_pages})\n"
    message_text += f"Фильтр: {filter_names.get(filter_type, 'Все')}\n"
    message_text += f"Найдено: {total_items}\n\n"
    message_text += "<i>⚡ Быстрые действия под каждым пользователем</i>"
    
    inline_kb = []
    
    # Кнопки фильтров - 3 штуки в одну линию
    filter_buttons = [
        InlineKeyboardButton(
            text="Все" if filter_type != "all" else "✅ Все",
            callback_data=f"admin_subscription_dates:0:all"
        ),
        InlineKeyboardButton(
            text="⚠️ 1-5д" if filter_type != "urgent" else "✅ 1-5д",
            callback_data=f"admin_subscription_dates:0:urgent"
        ),
        InlineKeyboardButton(
            text="📅 7-14д" if filter_type != "warning" else "✅ 7-14д",
            callback_data=f"admin_subscription_dates:0:warning"
        )
    ]
    
    inline_kb.append(filter_buttons)
    
    if not current_items:
        message_text = f"<b>📅 Активные подписки</b>\n\nПо фильтру \"{filter_names.get(filter_type)}\" ничего не найдено."
    else:
        # Формируем кнопки для каждого пользователя
        for i, (user, subscription) in enumerate(current_items, 1):
            user_name = user.first_name or ""
            if user.last_name:
                user_name += f" {user.last_name}"
            if user.username:
                user_name += f" (@{user.username})"
            if not user_name.strip():
                user_name = f"ID: {user.telegram_id}"
            
            # Формируем текст кнопки пользователя
            if is_lifetime_subscription(subscription):
                user_button_text = f"♾️ {start_idx + i}. {user_name}"
            else:
                days_left = (subscription.end_date - now).days
                
                # Визуальные индикаторы по срочности
                if days_left <= 1:
                    status_emoji = "🔴"
                elif days_left <= 3:
                    status_emoji = "🟠"
                elif days_left <= 7:
                    status_emoji = "🟡"
                else:
                    status_emoji = "🟢"
                
                user_button_text = f"{status_emoji} {start_idx + i}. {user_name} - {days_left}д"
            
            # Кнопка с именем пользователя
            inline_kb.append([InlineKeyboardButton(
                text=user_button_text,
                callback_data=f"sub_user_info:{user.telegram_id}:{page}"
            )])
            
            # Быстрые действия под пользователем
            action_buttons = [
                InlineKeyboardButton(text="👁️ Bio", callback_data=f"sub_bio:{user.telegram_id}:{page}"),
                InlineKeyboardButton(text="➕7д", callback_data=f"sub_add:{user.telegram_id}:7:{page}"),
                InlineKeyboardButton(text="➕30д", callback_data=f"sub_add:{user.telegram_id}:30:{page}"),
                InlineKeyboardButton(text="⭐", callback_data=f"sub_fav:{user.telegram_id}:{page}")
            ]
            inline_kb.append(action_buttons)
    
    # Навигация с сохранением фильтра
    pagination = []
    if page > 0:
        pagination.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_subscription_dates:{page-1}:{filter_type}"))
    if page < total_pages - 1:
        pagination.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_subscription_dates:{page+1}:{filter_type}"))
    if pagination:
        inline_kb.append(pagination)
    if total_pages > 1:
        inline_kb.append([InlineKeyboardButton(text=f"Страница {page+1}/{total_pages}", callback_data="ignore")])

    inline_kb.append([InlineKeyboardButton(text="📊 Экспорт в Excel", callback_data="admin_export_subscriptions")])
    inline_kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_subscription_dates:{page}:{filter_type}")])
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
        
        # Определяем статус по той же логике что и в интерфейсе
        if is_lifetime_subscription(subscription):
            status = "Пожизненная"
        elif days_left <= 1:
            status = "🔴 КРИТИЧНО"
        elif days_left <= 3:
            status = "🟠 СРОЧНО"
        elif days_left <= 7:
            status = "🟡 ВНИМАНИЕ"
        else:
            status = "🟢 НОРМА"
        
        data.append({
            "ID пользователя": user.telegram_id,
            "Имя пользователя": user_name,
            "Username": f"@{user.username}" if user.username else "",
            "Дата окончания": subscription.end_date.strftime("%d.%m.%Y"),
            "Осталось дней": days_left,
            "Статус": status
        })

    df = pd.DataFrame(data)
    from datetime import datetime as dt
    filename = f"exports/subscriptions_{dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    os.makedirs("exports", exist_ok=True)
    df.to_excel(filename, index=False)
    doc = FSInputFile(filename)
    await callback.message.answer_document(document=doc, caption="📊 Экспорт данных о подписках")


# Быстрые действия
@subscriptions_router.callback_query(F.data.startswith("sub_user_info:"))
async def show_sub_user_info(callback: CallbackQuery):
    """Показывает краткую информацию о подписке пользователя"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            subscription = await get_active_subscription(session, user.id)
            if not subscription:
                await callback.answer("❌ Подписка не найдена", show_alert=True)
                return
            
            if is_lifetime_subscription(subscription):
                text = f"👤 {user.first_name or 'Пользователь'}\n\n♾️ Пожизненная подписка"
            else:
                days_left = (subscription.end_date - datetime.now()).days
                date_str = subscription.end_date.strftime("%d.%m.%Y")
                text = f"👤 {user.first_name or 'Пользователь'}\n\n📅 До: {date_str}\n⏱ Осталось: {days_left} дн."
            
            await callback.answer(text, show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в show_sub_user_info: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@subscriptions_router.callback_query(F.data.startswith("sub_bio:"))
async def open_sub_bio(callback: CallbackQuery):
    """Открывает полный bio пользователя"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        
        # Импортируем функцию из users.py
        from handlers.admin.users import process_update_user_info
        
        await process_update_user_info(callback, telegram_id)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в open_sub_bio: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@subscriptions_router.callback_query(F.data.startswith("sub_add:"))
async def confirm_add_subscription_days(callback: CallbackQuery):
    """Запрашивает подтверждение добавления дней к подписке"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        days = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            user_name = user.first_name or "Пользователь"
            if user.username:
                user_name += f" (@{user.username})"
        
        text = (
            f"⚠️ <b>Подтверждение</b>\n\n"
            f"Добавить <b>{days} дней</b> к подписке?\n\n"
            f"👤 {user_name}"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, добавить", callback_data=f"sub_add_confirm:{telegram_id}:{days}:{page}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_subscription_dates:{page}")
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в confirm_add_subscription_days: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@subscriptions_router.callback_query(F.data.startswith("sub_add_confirm:"))
async def add_subscription_days_confirmed(callback: CallbackQuery):
    """Добавляет дни к подписке после подтверждения"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        days = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            # Продлеваем подписку
            await extend_subscription(session, user.id, days, 0, "admin_quick_action")
            await callback.answer(f"✅ Добавлено {days} дн.", show_alert=True)
            
            # Обновляем список
            callback.data = f"admin_subscription_dates:{page}"
            await process_subscription_dates(callback, None)
    except Exception as e:
        logger.error(f"Ошибка в add_subscription_days_confirmed: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@subscriptions_router.callback_query(F.data.startswith("sub_fav:"))
async def toggle_sub_favorite(callback: CallbackQuery):
    """Добавляет/удаляет пользователя из избранного"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        
        async with AsyncSessionLocal() as session:
            is_fav = await is_favorite(session, callback.from_user.id, telegram_id)
            
            if is_fav:
                await remove_from_favorites(session, callback.from_user.id, telegram_id)
                await callback.answer("❌ Удалено из избранного", show_alert=True)
            else:
                await add_to_favorites(session, callback.from_user.id, telegram_id, note=None)
                await callback.answer("⭐ Добавлено в избранное", show_alert=True)
            
            # Обновляем список
            callback.data = f"admin_subscription_dates:{page}"
            await process_subscription_dates(callback, None)
    except Exception as e:
        logger.error(f"Ошибка в toggle_sub_favorite: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)