from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime
import logging

from database.config import AsyncSessionLocal
from database.models import User, Subscription
from database.crud import get_user_by_telegram_id
from utils.admin_permissions import is_admin

logger = logging.getLogger(__name__)
autorenew_router = Router()

# Количество пользователей на странице
USERS_PER_PAGE = 10


@autorenew_router.callback_query(F.data == "admin_autorenew_menu")
async def show_autorenew_menu(callback: CallbackQuery):
    """Показывает главное меню управления автопродлениями"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        # Подсчитываем количество пользователей с включенным и выключенным автопродлением
        async with AsyncSessionLocal() as session:
            # Пользователи с включенным автопродлением
            query_enabled = select(User).where(User.is_recurring_active == True)
            result_enabled = await session.execute(query_enabled)
            enabled_count = len(result_enabled.scalars().all())
            
            # Пользователи с выключенным автопродлением (но которые когда-то имели подписку)
            query_disabled = select(User).where(User.is_recurring_active == False, User.first_payment_date.isnot(None))
            result_disabled = await session.execute(query_disabled)
            disabled_count = len(result_disabled.scalars().all())
        
        text = (
            "🔄 <b>Управление автопродлениями</b>\n\n"
            f"✅ <b>Включено:</b> {enabled_count} чел.\n"
            f"❌ <b>Выключено:</b> {disabled_count} чел.\n\n"
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
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        page = int(callback.data.split(":")[1])
        
        async with AsyncSessionLocal() as session:
            # Получаем всех пользователей с включенным автопродлением и их активные подписки
            query = (
                select(User)
                .where(User.is_recurring_active == True)
                .options(selectinload(User.subscriptions))
                .order_by(User.updated_at.desc())
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
            
            text = f"✅ <b>Включено автопродление</b> (стр. {page + 1}/{total_pages})\n\n"
            text += f"Всего пользователей: {total_users}\n\n"
            
            # Формируем кнопки для каждого пользователя
            keyboard_buttons = []
            for i, usr in enumerate(page_users, start=start_idx + 1):
                username_display = f"@{usr.username}" if usr.username else f"ID: {usr.telegram_id}"
                
                # Получаем активную подписку
                subscription_info = ""
                active_sub = None
                for sub in usr.subscriptions:
                    if sub.is_active and sub.end_date > datetime.now():
                        active_sub = sub
                        break
                
                if active_sub:
                    days_left = (active_sub.end_date - datetime.now()).days
                    if days_left > 0:
                        subscription_info = f" (осталось {days_left} дн.)"
                    else:
                        subscription_info = " (истекает сегодня)"
                else:
                    subscription_info = " (нет активной)"
                
                button_text = f"{i}. {username_display}{subscription_info}"
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"admin_user_id:{usr.telegram_id}"
                )])
            
            # Навигация
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"admin_autorenew_enabled:{page - 1}"
                ))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="Вперёд ▶️",
                    callback_data=f"admin_autorenew_enabled:{page + 1}"
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
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    
    try:
        page = int(callback.data.split(":")[1])
        
        async with AsyncSessionLocal() as session:
            # Получаем всех пользователей с выключенным автопродлением (но которые когда-то имели подписку)
            query = (
                select(User)
                .where(
                    User.is_recurring_active == False,
                    User.first_payment_date.isnot(None)
                )
                .options(selectinload(User.subscriptions))
                .order_by(User.updated_at.desc())
            )
            result = await session.execute(query)
            all_users = result.scalars().all()
            
            total_users = len(all_users)
            total_pages = (total_users + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            
            if total_users == 0:
                text = "❌ <b>Пользователи с выключенным автопродлением</b>\n\n📭 Список пуст"
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
            
            text = f"❌ <b>Выключено автопродление</b> (стр. {page + 1}/{total_pages})\n\n"
            text += f"Всего пользователей: {total_users}\n\n"
            
            # Формируем кнопки для каждого пользователя
            keyboard_buttons = []
            for i, usr in enumerate(page_users, start=start_idx + 1):
                username_display = f"@{usr.username}" if usr.username else f"ID: {usr.telegram_id}"
                
                # Получаем активную или последнюю подписку
                subscription_info = ""
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
                    if days_left > 0:
                        subscription_info = f" (осталось {days_left} дн.)"
                    else:
                        subscription_info = " (истекает сегодня)"
                elif last_sub:
                    days_ago = (datetime.now() - last_sub.end_date).days
                    if days_ago > 0:
                        subscription_info = f" (истекла {days_ago} дн. назад)"
                    else:
                        subscription_info = " (истекла)"
                else:
                    subscription_info = " (нет подписки)"
                
                button_text = f"{i}. {username_display}{subscription_info}"
                keyboard_buttons.append([InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"admin_user_id:{usr.telegram_id}"
                )])
            
            # Навигация
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"admin_autorenew_disabled:{page - 1}"
                ))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton(
                    text="Вперёд ▶️",
                    callback_data=f"admin_autorenew_disabled:{page + 1}"
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


def register_autorenew_handlers(dp):
    """Регистрирует обработчики модуля автопродлений"""
    dp.include_router(autorenew_router)
