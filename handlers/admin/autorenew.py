from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime
import logging

from database.config import AsyncSessionLocal
from database.models import User, Subscription
from database.crud import (
    get_user_by_telegram_id,
    extend_subscription,
    get_active_subscription,
    is_favorite,
    add_to_favorites,
    remove_from_favorites
)
from utils.admin_permissions import is_admin, can_manage_admins
from utils.constants import LIFETIME_THRESHOLD

logger = logging.getLogger(__name__)
autorenew_router = Router()

# Количество пользователей на странице
USERS_PER_PAGE = 10


@autorenew_router.callback_query(F.data == "admin_autorenew_menu")
async def show_autorenew_menu(callback: CallbackQuery):
    """Показывает главное меню управления автопродлениями"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        # Подсчитываем количество пользователей с включенным и выключенным автопродлением
        async with AsyncSessionLocal() as session:
            # Пользователи с включенным автопродлением
            query_enabled = select(User).where(User.is_recurring_active == True)
            result_enabled = await session.execute(query_enabled)
            enabled_count = len(result_enabled.scalars().all())
            
            # Пользователи с выключенным автопродлением И активной подпиской (НЕ lifetime)
            # (в зоне риска - подписка истечёт и не продлится)
            query_disabled = (
                select(User)
                .join(Subscription, User.id == Subscription.user_id)
                .where(
                    User.is_recurring_active == False,
                    Subscription.is_active == True,
                    Subscription.end_date > datetime.now(),
                    Subscription.end_date < LIFETIME_THRESHOLD  # Исключаем пожизненные (end_date < 2099-01-01)
                )
                .distinct()
            )
            result_disabled = await session.execute(query_disabled)
            disabled_count = len(result_disabled.scalars().all())
        
        text = (
            "🔄 <b>Управление автопродлениями</b>\n\n"
            f"✅ <b>Включено:</b> {enabled_count} чел.\n"
            f"❌ <b>Выключено (с активной подпиской):</b> {disabled_count} чел.\n\n"
            "<i>В разделе 'Выключено' показаны пользователи с активной подпиской,\n"
            "но без автопродления - они в зоне риска!</i>\n\n"
            "Выберите раздел:"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"✅ Включено ({enabled_count})",
                callback_data="admin_autorenew_enabled:0"
            )],
            [InlineKeyboardButton(
                text=f"❌ Выключено ({disabled_count})",
                callback_data="admin_autorenew_disabled:0"
            )],
            [InlineKeyboardButton(
                text="« Назад",
                callback_data="admin_back"
            )]
        ])
        
        # Удаляем старое сообщение (может быть с картинкой)
        try:
            await callback.message.delete()
        except Exception:
            pass
        
        # Отправляем новое сообщение
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в show_autorenew_menu: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке меню", show_alert=True)


@autorenew_router.callback_query(F.data.startswith("admin_autorenew_enabled:"))
async def show_autorenew_enabled(callback: CallbackQuery):
    """Показывает список пользователей с включенным автопродлением"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        parts = callback.data.split(":")
        page = int(parts[1])
        sort_order = parts[2] if len(parts) > 2 else "asc"  # asc = ближайшие первыми, desc = дальние первыми
        
        async with AsyncSessionLocal() as session:
            # Получаем всех пользователей с включенным автопродлением и их активные подписки
            # Сортируем через JOIN для корректной сортировки по дате подписки
            if sort_order == "asc":
                order_clause = Subscription.end_date.asc().nulls_last()
            else:
                order_clause = Subscription.end_date.desc().nulls_last()
            
            query = (
                select(User)
                .join(Subscription, User.id == Subscription.user_id)
                .where(
                    User.is_recurring_active == True,
                    Subscription.is_active == True
                )
                .options(selectinload(User.subscriptions))
                .distinct()
                .order_by(order_clause)
            )
            result = await session.execute(query)
            all_users = result.scalars().all()
            
            total_users = len(all_users)
            total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            
            if total_users == 0:
                text = "✅ <b>Пользователи с включенным автопродлением</b>\n\n📭 Список пуст"
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад", callback_data="admin_autorenew_menu")]
                ])
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
                await callback.answer()
                return
            
            # Пагинация
            start_idx = page * USERS_PER_PAGE
            end_idx = start_idx + USERS_PER_PAGE
            page_users = all_users[start_idx:end_idx]
            
            text = f"✅ <b>Включено автопродление</b> (стр. {page + 1}/{total_pages})\n"
            text += f"Всего: {total_users}\n\n"
            text += "<i>⚡ Быстрые действия под каждым пользователем</i>"
            
            # Формируем кнопки для каждого пользователя
            keyboard_buttons = []
            for i, usr in enumerate(page_users, start=start_idx + 1):
                user_name = usr.first_name or ""
                if usr.last_name:
                    user_name += f" {usr.last_name}"
                if usr.username:
                    user_name += f" (@{usr.username})"
                if not user_name.strip():
                    user_name = f"ID: {usr.telegram_id}"
                
                # Получаем активную подписку
                active_sub = None
                for sub in usr.subscriptions:
                    if sub.is_active and sub.end_date > datetime.now():
                        active_sub = sub
                        break
                
                if active_sub:
                    days_left = (active_sub.end_date - datetime.now()).days
                    
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
                    button_text = f"⚫ {i}. {user_name}"
                
                # Кнопка с именем пользователя
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"renew_info:{usr.telegram_id}:{page}:{sort_order}:enabled"
                )])
                
                # Быстрые действия под пользователем
                action_buttons = [
                    InlineKeyboardButton(text="👁️ Bio", callback_data=f"renew_bio:{usr.telegram_id}:{page}:{sort_order}:enabled"),
                    InlineKeyboardButton(text="➕7д", callback_data=f"renew_add:{usr.telegram_id}:7:{page}:{sort_order}:enabled"),
                    InlineKeyboardButton(text="➕30д", callback_data=f"renew_add:{usr.telegram_id}:30:{page}:{sort_order}:enabled"),
                    InlineKeyboardButton(text="⭐", callback_data=f"renew_fav:{usr.telegram_id}:{page}:{sort_order}:enabled")
                ]
                keyboard_buttons.append(action_buttons)
            
            # Кнопки сортировки
            sort_buttons = []
            if sort_order == "desc":
                sort_buttons.append(InlineKeyboardButton(
                    text="⏰ Ближайшие сначала",
                    callback_data=f"admin_autorenew_enabled:0:asc"
                ))
            else:
                sort_buttons.append(InlineKeyboardButton(
                    text="📅 Дальние сначала",
                    callback_data=f"admin_autorenew_enabled:0:desc"
                ))
            keyboard_buttons.append(sort_buttons)
            
            # Навигация
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"admin_autorenew_enabled:{page - 1}:{sort_order}"
                ))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="Вперёд ▶️",
                    callback_data=f"admin_autorenew_enabled:{page + 1}:{sort_order}"
                ))
            
            if nav_buttons:
                keyboard_buttons.append(nav_buttons)
            
            # Кнопка назад
            keyboard_buttons.append([InlineKeyboardButton(
                text="« Назад к автопродлениям",
                callback_data="admin_autorenew_menu"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()
            
    except Exception as e:
        logger.error(f"Ошибка в show_autorenew_enabled: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке списка", show_alert=True)


@autorenew_router.callback_query(F.data.startswith("admin_autorenew_disabled:"))
async def show_autorenew_disabled(callback: CallbackQuery):
    """Показывает список пользователей с выключенным автопродлением"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        parts = callback.data.split(":")
        page = int(parts[1])
        sort_order = parts[2] if len(parts) > 2 else "asc"  # asc = ближайшие первыми (срочные), desc = дальние
        
        async with AsyncSessionLocal() as session:
            # Получаем пользователей с выключенным автопродлением И активной подпиской (НЕ lifetime)
            if sort_order == "asc":
                order_clause = Subscription.end_date.asc()
            else:
                order_clause = Subscription.end_date.desc()
            
            query = (
                select(User)
                .join(Subscription, User.id == Subscription.user_id)
                .where(
                    User.is_recurring_active == False,
                    Subscription.is_active == True,
                    Subscription.end_date > datetime.now(),
                    Subscription.end_date < LIFETIME_THRESHOLD  # Исключаем пожизненные (end_date < 2099-01-01)
                )
                .options(selectinload(User.subscriptions))
                .distinct()
                .order_by(order_clause)
            )
            result = await session.execute(query)
            all_users = result.scalars().all()
            
            total_users = len(all_users)
            total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            
            if total_users == 0:
                text = (
                    "❌ <b>Выключено автопродление</b>\n\n"
                    "🎉 Отлично! Все активные пользователи включили автопродление.\n\n"
                    "<i>Здесь показываются только те, у кого есть активная подписка,\n"
                    "но автопродление выключено.</i>"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад", callback_data="admin_autorenew_menu")]
                ])
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
                await callback.answer()
                return
            
            # Пагинация
            start_idx = page * USERS_PER_PAGE
            end_idx = start_idx + USERS_PER_PAGE
            page_users = all_users[start_idx:end_idx]
            
            text = f"❌ <b>Выключено автопродление</b> (стр. {page + 1}/{total_pages})\n"
            text += f"⚠️ В зоне риска: {total_users}\n\n"
            text += "<i>⚡ Быстрые действия под каждым пользователем</i>"
            
            # Формируем кнопки для каждого пользователя
            keyboard_buttons = []
            for i, usr in enumerate(page_users, start=start_idx + 1):
                user_name = usr.first_name or ""
                if usr.last_name:
                    user_name += f" {usr.last_name}"
                if usr.username:
                    user_name += f" (@{usr.username})"
                if not user_name.strip():
                    user_name = f"ID: {usr.telegram_id}"
                
                # Получаем активную или последнюю подписку
                active_sub = None
                last_sub = None
                
                for sub in usr.subscriptions:
                    if sub.is_active:
                        if sub.end_date > datetime.now():
                            active_sub = sub
                        else:
                            last_sub = sub
                    elif not last_sub or sub.end_date > last_sub.end_date:
                        last_sub = sub
                
                if active_sub:
                    days_left = (active_sub.end_date - datetime.now()).days
                    
                    # Визуальные индикаторы по срочности
                    if days_left <= 1:
                        status_emoji = "🔴"
                    elif days_left <= 3:
                        status_emoji = "🟠"
                    elif days_left <= 7:
                        status_emoji = "🟡"
                    else:
                        status_emoji = "�"
                    
                    button_text = f"{status_emoji} {i}. {user_name} - {days_left}д"
                elif last_sub:
                    button_text = f"⚫ {i}. {user_name} (истекла)"
                else:
                    button_text = f"⚫ {i}. {user_name}"
                
                # Кнопка с именем пользователя
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"renew_info:{usr.telegram_id}:{page}:{sort_order}:disabled"
                )])
                
                # Быстрые действия под пользователем
                action_buttons = [
                    InlineKeyboardButton(text="👁️ Bio", callback_data=f"renew_bio:{usr.telegram_id}:{page}:{sort_order}:disabled"),
                    InlineKeyboardButton(text="➕7д", callback_data=f"renew_add:{usr.telegram_id}:7:{page}:{sort_order}:disabled"),
                    InlineKeyboardButton(text="➕30д", callback_data=f"renew_add:{usr.telegram_id}:30:{page}:{sort_order}:disabled"),
                    InlineKeyboardButton(text="⭐", callback_data=f"renew_fav:{usr.telegram_id}:{page}:{sort_order}:disabled")
                ]
                keyboard_buttons.append(action_buttons)
            
            # Кнопки сортировки
            sort_buttons = []
            if sort_order == "desc":
                sort_buttons.append(InlineKeyboardButton(
                    text="⚠️ Срочные сначала",
                    callback_data=f"admin_autorenew_disabled:0:asc"
                ))
            else:
                sort_buttons.append(InlineKeyboardButton(
                    text="📅 Дальние сначала",
                    callback_data=f"admin_autorenew_disabled:0:desc"
                ))
            keyboard_buttons.append(sort_buttons)
            
            # Навигация
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"admin_autorenew_disabled:{page - 1}:{sort_order}"
                ))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="Вперёд ▶️",
                    callback_data=f"admin_autorenew_disabled:{page + 1}:{sort_order}"
                ))
            
            if nav_buttons:
                keyboard_buttons.append(nav_buttons)
            
            # Кнопка назад
            keyboard_buttons.append([InlineKeyboardButton(
                text="« Назад к автопродлениям",
                callback_data="admin_autorenew_menu"
            )])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()
            
    except Exception as e:
        logger.error(f"Ошибка в show_autorenew_disabled: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке списка", show_alert=True)


# Быстрые действия для автопродлений
@autorenew_router.callback_query(F.data.startswith("renew_info:"))
async def show_renew_user_info(callback: CallbackQuery):
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
        logger.error(f"Ошибка в show_renew_user_info: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@autorenew_router.callback_query(F.data.startswith("renew_bio:"))
async def open_renew_bio(callback: CallbackQuery):
    """Открывает полный bio пользователя"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        
        from handlers.admin.users import process_update_user_info
        await process_update_user_info(callback, telegram_id)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в open_renew_bio: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@autorenew_router.callback_query(F.data.startswith("renew_add:"))
async def confirm_renew_add_days(callback: CallbackQuery):
    """Запрашивает подтверждение добавления дней"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        days = int(parts[2])
        page = int(parts[3])
        sort_order = parts[4]
        source = parts[5]  # enabled или disabled
        
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
                InlineKeyboardButton(text="✅ Да, добавить", callback_data=f"renew_add_confirm:{telegram_id}:{days}:{page}:{sort_order}:{source}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_autorenew_{source}:{page}:{sort_order}")
            ]
        ])
        
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в confirm_renew_add_days: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@autorenew_router.callback_query(F.data.startswith("renew_add_confirm:"))
async def renew_add_days_confirmed(callback: CallbackQuery):
    """Добавляет дни к подписке после подтверждения"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        days = int(parts[2])
        page = int(parts[3])
        sort_order = parts[4]
        source = parts[5]
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            await extend_subscription(session, user.id, days, 0, "admin_quick_action")
            await callback.answer(f"✅ Добавлено {days} дн.", show_alert=True)
            
            # Обновляем список
            callback.data = f"admin_autorenew_{source}:{page}:{sort_order}"
            if source == "enabled":
                await show_autorenew_enabled(callback)
            else:
                await show_autorenew_disabled(callback)
    except Exception as e:
        logger.error(f"Ошибка в renew_add_days_confirmed: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


@autorenew_router.callback_query(F.data.startswith("renew_fav:"))
async def toggle_renew_favorite(callback: CallbackQuery):
    """Добавляет/удаляет пользователя из избранного"""
    try:
        parts = callback.data.split(":")
        telegram_id = int(parts[1])
        page = int(parts[2])
        sort_order = parts[3]
        source = parts[4]
        
        async with AsyncSessionLocal() as session:
            is_fav = await is_favorite(session, callback.from_user.id, telegram_id)
            
            if is_fav:
                await remove_from_favorites(session, callback.from_user.id, telegram_id)
                await callback.answer("❌ Удалено из избранного", show_alert=True)
            else:
                await add_to_favorites(session, callback.from_user.id, telegram_id, note=None)
                await callback.answer("⭐ Добавлено в избранное", show_alert=True)
            
            # Обновляем список
            callback.data = f"admin_autorenew_{source}:{page}:{sort_order}"
            if source == "enabled":
                await show_autorenew_enabled(callback)
            else:
                await show_autorenew_disabled(callback)
    except Exception as e:
        logger.error(f"Ошибка в toggle_renew_favorite: {e}", exc_info=True)
        await callback.answer("❌ Ошибка", show_alert=True)


def register_autorenew_handlers(dp):
    """Регистрирует обработчики модуля автопродлений"""
    dp.include_router(autorenew_router)
