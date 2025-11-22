"""
Обработчики для работы с избранными пользователями в админке
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging
from datetime import datetime

from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_admin_favorites,
    add_to_favorites,
    remove_from_favorites,
    update_favorite_note,
    is_favorite,
    get_active_subscription,
    extend_subscription
)
from utils.admin_permissions import is_admin
from utils.helpers import html_kv
from handlers.admin.users import format_subscription_status

logger = logging.getLogger(__name__)

favorites_router = Router()

FAVORITES_PER_PAGE = 10


class FavoriteStates(StatesGroup):
    """Состояния для работы с избранными"""
    waiting_for_note = State()
    editing_note = State()


def register_admin_favorites_handlers(dp):
    """Регистрирует обработчики избранных пользователей"""
    dp.include_router(favorites_router)
    logger.info("[favorites] Обработчики избранных пользователей зарегистрированы")


@favorites_router.callback_query(F.data.startswith("admin_favorites"))
async def show_favorites_list(callback: CallbackQuery):
    """Показывает список избранных пользователей админа"""
    async with AsyncSessionLocal() as session:
        admin = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(admin):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        parts = callback.data.split(":")
        page = int(parts[1]) if len(parts) > 1 else 0
        
        async with AsyncSessionLocal() as session:
            favorites_data, total_count = await get_admin_favorites(
                session,
                callback.from_user.id,
                limit=FAVORITES_PER_PAGE,
                page=page
            )
            
            if total_count == 0:
                text = (
                    "⭐ <b>Избранные пользователи</b>\n\n"
                    "📋 Список пуст\n\n"
                    "<i>Добавляйте важных пользователей в избранное,\n"
                    "чтобы быстро получать к ним доступ.</i>"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
                ])
                
                try:
                    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
                except Exception:
                    try:
                        await callback.message.delete()
                    except:
                        pass
                    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
                
                await callback.answer()
                return
            
            total_pages = (total_count + FAVORITES_PER_PAGE - 1) // FAVORITES_PER_PAGE
            start_idx = page * FAVORITES_PER_PAGE
            
            text = f"⭐ <b>Избранные пользователи</b> (стр. {page + 1}/{total_pages})\n"
            text += f"Всего: {total_count}\n\n"
            text += "<i>⚡ Быстрые действия под каждым пользователем</i>"
            
            keyboard_buttons = []
            
            for i, (user, favorite) in enumerate(favorites_data, start=start_idx + 1):
                # Имя пользователя
                user_name = user.first_name or ""
                if user.last_name:
                    user_name += f" {user.last_name}"
                if user.username:
                    user_name += f" (@{user.username})"
                if not user_name.strip():
                    user_name = f"ID: {user.telegram_id}"
                
                # Получаем статус подписки
                subscription = await get_active_subscription(session, user.id)
                
                # Формируем текст кнопки
                if subscription:
                    days_left = (subscription.end_date - datetime.now()).days
                    
                    # Визуальные индикаторы
                    if days_left <= 1:
                        status_emoji = "🔴"
                    elif days_left <= 3:
                        status_emoji = "🟠"
                    elif days_left <= 7:
                        status_emoji = "🟡"
                    else:
                        status_emoji = "🟢"
                    
                    button_text = f"{status_emoji} {i}. {user_name} - {days_left}д"
                else:
                    button_text = f"❌ {i}. {user_name}"
                
                # Кнопка с именем пользователя
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"fav_info:{user.telegram_id}:{page}"
                )])
                
                # Быстрые действия под пользователем
                action_buttons = [
                    InlineKeyboardButton(text="👁️ Bio", callback_data=f"fav_bio:{user.telegram_id}:{page}"),
                    InlineKeyboardButton(text="➕7д", callback_data=f"fav_add:{user.telegram_id}:7:{page}"),
                    InlineKeyboardButton(text="➕30д", callback_data=f"fav_add:{user.telegram_id}:30:{page}"),
                    InlineKeyboardButton(text="✏️", callback_data=f"admin_edit_favorite_note:{user.telegram_id}:{page}")
                ]
                keyboard_buttons.append(action_buttons)
            
            # Навигация
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"admin_favorites:{page - 1}"
                ))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="Вперёд ▶️",
                    callback_data=f"admin_favorites:{page + 1}"
                ))
            
            if nav_buttons:
                keyboard_buttons.append(nav_buttons)
            
            # Назад
            keyboard_buttons.append([InlineKeyboardButton(
                text="« Назад в админку",
                callback_data="admin_back"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            
            try:
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except Exception as edit_error:
                # Если не можем отредактировать (например, сообщение с картинкой), удаляем и отправляем новое
                try:
                    await callback.message.delete()
                except:
                    pass
                await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
            await callback.answer()
            
    except Exception as e:
        logger.error(f"Ошибка в show_favorites_list: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке списка", show_alert=True)


@favorites_router.callback_query(F.data.startswith("admin_favorite_user:"))
async def show_favorite_user_actions(callback: CallbackQuery):
    """Показывает действия с избранным пользователем"""
    try:
        parts = callback.data.split(":")
        user_telegram_id = int(parts[1])
        return_page = int(parts[2]) if len(parts) > 2 else 0
        
        # Получаем заметку
        async with AsyncSessionLocal() as session:
            from database.crud import get_favorite, get_user_by_telegram_id
            
            favorite = await get_favorite(session, callback.from_user.id, user_telegram_id)
            user = await get_user_by_telegram_id(session, user_telegram_id)
            
            user_name = user.first_name or ""
            if user.last_name:
                user_name += f" {user.last_name}"
            if user.username:
                user_name += f" (@{user.username})"
            if not user_name.strip():
                user_name = f"ID: {user.telegram_id}"
        
        text = f"⭐ <b>Действия с избранным</b>\n\n<b>Пользователь:</b> {user_name}\n"
        
        if favorite and favorite.note:
            text += f"\n<b>💬 Заметка:</b>\n{favorite.note}\n"
        else:
            text += "\n<i>Заметка не указана</i>\n"
        
        text += "\nВыберите действие:"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="👁️ Открыть профиль",
                callback_data=f"admin_user_info_from_favorites:{user_telegram_id}:{return_page}"
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить заметку",
                callback_data=f"admin_edit_favorite_note:{user_telegram_id}:{return_page}"
            )],
            [InlineKeyboardButton(
                text="🗑️ Удалить из избранного",
                callback_data=f"admin_remove_favorite_confirm:{user_telegram_id}:{return_page}"
            )],
            [InlineKeyboardButton(
                text="« Назад к списку",
                callback_data=f"admin_favorites:{return_page}"
            )]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в show_favorite_user_actions: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@favorites_router.callback_query(F.data.startswith("admin_remove_favorite_confirm:"))
async def remove_favorite_confirm_handler(callback: CallbackQuery):
    """Удаляет пользователя из избранного (из списка избранных)"""
    try:
        parts = callback.data.split(":")
        user_telegram_id = int(parts[1])
        return_page = int(parts[2]) if len(parts) > 2 else 0
        
        async with AsyncSessionLocal() as session:
            success = await remove_from_favorites(
                session,
                callback.from_user.id,
                user_telegram_id
            )
            
            if success:
                await callback.answer("✅ Удалено из избранного", show_alert=True)
            else:
                await callback.answer("❌ Не найдено в избранном", show_alert=True)
        
        # Возвращаемся к списку
        callback.data = f"admin_favorites:{return_page}"
        await show_favorites_list(callback)
        
    except Exception as e:
        logger.error(f"Ошибка в remove_favorite_confirm_handler: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при удалении", show_alert=True)


@favorites_router.callback_query(F.data.startswith("admin_edit_favorite_note:"))
async def edit_favorite_note_start(callback: CallbackQuery, state: FSMContext):
    """Начинает процесс изменения заметки"""
    try:
        parts = callback.data.split(":")
        user_telegram_id = int(parts[1])
        return_page = int(parts[2]) if len(parts) > 2 else 0
        
        await state.set_state(FavoriteStates.editing_note)
        await state.update_data(
            user_telegram_id=user_telegram_id,
            return_page=return_page
        )
        
        text = (
            "✏️ <b>Изменение заметки</b>\n\n"
            "Введите новую заметку для этого пользователя:\n\n"
            "<i>Примеры:\n"
            "• На контроле - истекает подписка\n"
            "• Проблемная - много вопросов\n"
            "• Активная в группе\n"
            "• Постоянный клиент</i>"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"admin_favorites:{return_page}"
            )]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в edit_favorite_note_start: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@favorites_router.message(FavoriteStates.editing_note)
async def edit_favorite_note_finish(message: Message, state: FSMContext):
    """Завершает изменение заметки"""
    try:
        data = await state.get_data()
        user_telegram_id = data.get("user_telegram_id")
        return_page = data.get("return_page", 0)
        note = message.text.strip()
        
        if len(note) > 500:
            await message.answer("❌ Заметка слишком длинная (макс. 500 символов)")
            return
        
        async with AsyncSessionLocal() as session:
            success = await update_favorite_note(
                session,
                message.from_user.id,
                user_telegram_id,
                note
            )
            
            if success:
                await message.answer("✅ Заметка обновлена!")
            else:
                await message.answer("❌ Ошибка при обновлении заметки")
        
        await state.clear()
        
        # Показываем список избранных
        text = "⭐ Возвращаемся к списку избранных..."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📋 К списку избранных",
                callback_data=f"admin_favorites:{return_page}"
            )]
        ])
        await message.answer(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Ошибка в edit_favorite_note_finish: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка")
        await state.clear()


# Быстрые действия для избранных
@favorites_router.callback_query(F.data.startswith("fav_info:"))
async def show_fav_user_info(callback: CallbackQuery):
    """Показывает краткую информацию о пользователе"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            subscription = await get_active_subscription(session, user.id)
            if subscription:
                days_left = (subscription.end_date - datetime.now()).days
                date_str = subscription.end_date.strftime("%d.%m.%Y")
                text = f"👤 {user.first_name or 'Пользователь'}\n\n📅 До: {date_str}\n⏱ Осталось: {days_left} дн."
            else:
                text = f"👤 {user.first_name or 'Пользователь'}\n\n❌ Нет активной подписки"
            
            await callback.answer(text, show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в show_fav_user_info: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@favorites_router.callback_query(F.data.startswith("fav_bio:"))
async def open_fav_bio(callback: CallbackQuery):
    """Открывает полный bio пользователя"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        
        from handlers.admin.users import process_update_user_info
        await process_update_user_info(callback, telegram_id, return_to_favorites_page=page)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в open_fav_bio: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@favorites_router.callback_query(F.data.startswith("fav_add:"))
async def confirm_fav_add_days(callback: CallbackQuery):
    """Запрашивает подтверждение добавления дней"""
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
                InlineKeyboardButton(text="✅ Да, добавить", callback_data=f"fav_add_confirm:{telegram_id}:{days}:{page}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_favorites:{page}")
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в confirm_fav_add_days: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@favorites_router.callback_query(F.data.startswith("fav_add_confirm:"))
async def fav_add_days_confirmed(callback: CallbackQuery):
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
            
            await extend_subscription(session, user.id, days, 0, "admin_quick_action")
            await callback.answer(f"✅ Добавлено {days} дн.", show_alert=True)
            
            # Обновляем список
            callback.data = f"admin_favorites:{page}"
            await show_favorites_list(callback)
    except Exception as e:
        logger.error(f"Ошибка в fav_add_days_confirmed: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)
