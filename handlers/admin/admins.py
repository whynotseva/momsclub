"""
Обработчики для управления группами администраторов
"""
from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
import logging

from utils.constants import ADMIN_IDS, ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR, ADMIN_GROUP_EMOJIS, ADMIN_GROUP_NAMES
from utils.admin_permissions import is_admin, can_manage_admins
from utils.helpers import html_kv
from database.config import AsyncSessionLocal
from database.crud import get_user_by_telegram_id, get_user_by_username
from database.models import User
from sqlalchemy import update, select

logger = logging.getLogger(__name__)

admins_router = Router(name="admin_admins")


class AdminManagementStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_group = State()


def register_admin_admins_handlers(dp):
    dp.include_router(admins_router)
    logger.info("[admins] Админ-обработчики управления админами зарегистрированы")


@admins_router.callback_query(F.data == "admin_manage_admins")
async def admin_manage_admins_menu(callback: CallbackQuery):
    """Главное меню управления админами"""
    logger.info(f"[admins] Обработчик admin_manage_admins вызван от пользователя {callback.from_user.id}")
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            logger.info(f"[admins] Пользователь {callback.from_user.id}: user={user}, admin_group={user.admin_group if user else None}")
            if not is_admin(user) or not can_manage_admins(user):
                logger.warning(f"[admins] Пользователь {callback.from_user.id} не имеет прав на управление админами")
                await callback.answer("У вас нет доступа к этой функции", show_alert=True)
                return
        
        # Получаем всех админов
        query = select(User).where(
            User.admin_group.in_([ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR])
        ).order_by(
            User.admin_group.desc(),  # Сначала создательница, потом разработчик, потом кураторы
            User.created_at.asc()
        )
        result = await session.execute(query)
        admin_users = result.scalars().all()
        
        # Добавляем старых админов из ADMIN_IDS, если они еще не в списке
        admin_telegram_ids = {u.telegram_id for u in admin_users}
        for admin_id in ADMIN_IDS:
            if admin_id not in admin_telegram_ids:
                old_admin = await get_user_by_telegram_id(session, admin_id)
                if old_admin:
                    admin_users.append(old_admin)
        
        if not admin_users:
            text = "<b>👥 Управление админами</b>\n\nАдминистраторы не найдены."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Назначить админа", callback_data="admin_add_admin")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
            ])
        else:
            text = "<b>👥 Управление админами</b>\n\n<b>Текущие администраторы:</b>\n\n"
            keyboard_buttons = []
            
            for admin_user in admin_users:
                group_emoji = ADMIN_GROUP_EMOJIS.get(admin_user.admin_group, "👤")
                group_name = ADMIN_GROUP_NAMES.get(admin_user.admin_group, "Админ (старый)")
                username = f"@{admin_user.username}" if admin_user.username else f"ID: {admin_user.telegram_id}"
                name = f"{admin_user.first_name or ''} {admin_user.last_name or ''}".strip() or username
                
                text += f"{group_emoji} <b>{group_name}</b>\n"
                text += f"   {name} ({username})\n\n"
                
                keyboard_buttons.append([InlineKeyboardButton(
                    text=f"{group_emoji} {name}",
                    callback_data=f"admin_edit_admin:{admin_user.telegram_id}"
                )])
            
            keyboard_buttons.append([InlineKeyboardButton(text="➕ Назначить админа", callback_data="admin_add_admin")])
            keyboard_buttons.append([InlineKeyboardButton(text="« Назад", callback_data="admin_back")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        logger.info(f"[admins] Отправка меню управления админами пользователю {callback.from_user.id}")
        try:
            # Пытаемся отредактировать сообщение, если это возможно
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as edit_error:
            # Если не удалось отредактировать (например, это фото), отправляем новое сообщение
            logger.warning(f"[admins] Не удалось отредактировать сообщение, отправляем новое: {edit_error}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
    except Exception as e:
        logger.error(f"[admins] Ошибка в admin_manage_admins_menu: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при загрузке меню управления админами", show_alert=True)


@admins_router.callback_query(F.data == "admin_add_admin")
async def admin_add_admin_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса назначения админа"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
        
        await state.set_state(AdminManagementStates.waiting_for_user_id)
        await callback.message.edit_text(
            "<b>➕ Назначение админа</b>\n\n"
            "Введите Telegram ID или Username пользователя для назначения администратором:\n"
            "(ID должен быть числом, username — с символом @)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data="admin_manage_admins")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()


@admins_router.message(StateFilter(AdminManagementStates.waiting_for_user_id))
async def admin_add_admin_process_user(message: Message, state: FSMContext):
    """Обработка ввода пользователя для назначения админа"""
    async with AsyncSessionLocal() as session:
        current_user = await get_user_by_telegram_id(session, message.from_user.id)
        if not is_admin(current_user) or not can_manage_admins(current_user):
            await message.answer("У вас нет доступа к этой функции.")
            await state.clear()
            return
        
        search_term = message.text.strip()
        target_user = None
        
        if search_term.startswith("@"):
            username = search_term[1:]
            target_user = await get_user_by_username(session, username)
        else:
            try:
                user_id = int(search_term)
                target_user = await get_user_by_telegram_id(session, user_id)
            except ValueError:
                await message.answer("❌ Некорректный формат! Введите числовой ID или username с символом @")
                return
        
        if not target_user:
            await message.answer(f"❌ Пользователь '{search_term}' не найден.")
            await state.clear()
            return
        
        # Сохраняем ID пользователя в состоянии
        await state.update_data(target_user_id=target_user.telegram_id)
        await state.set_state(AdminManagementStates.waiting_for_group)
        
        # Показываем выбор группы
        username = f"@{target_user.username}" if target_user.username else f"ID: {target_user.telegram_id}"
        name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip() or username
        current_group = ADMIN_GROUP_NAMES.get(target_user.admin_group, "Нет") if target_user.admin_group else "Нет"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{ADMIN_GROUP_EMOJIS[ADMIN_GROUP_CREATOR]} {ADMIN_GROUP_NAMES[ADMIN_GROUP_CREATOR]}",
                callback_data=f"admin_set_group:{target_user.telegram_id}:{ADMIN_GROUP_CREATOR}"
            )],
            [InlineKeyboardButton(
                text=f"{ADMIN_GROUP_EMOJIS[ADMIN_GROUP_DEVELOPER]} {ADMIN_GROUP_NAMES[ADMIN_GROUP_DEVELOPER]}",
                callback_data=f"admin_set_group:{target_user.telegram_id}:{ADMIN_GROUP_DEVELOPER}"
            )],
            [InlineKeyboardButton(
                text=f"{ADMIN_GROUP_EMOJIS[ADMIN_GROUP_CURATOR]} {ADMIN_GROUP_NAMES[ADMIN_GROUP_CURATOR]}",
                callback_data=f"admin_set_group:{target_user.telegram_id}:{ADMIN_GROUP_CURATOR}"
            )],
            [InlineKeyboardButton(
                text="❌ Убрать права админа",
                callback_data=f"admin_remove_admin:{target_user.telegram_id}"
            )],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_manage_admins")]
        ])
        
        await message.answer(
            f"<b>👤 Пользователь:</b> {name} ({username})\n"
            f"<b>Текущая группа:</b> {current_group}\n\n"
            f"Выберите группу администратора:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.clear()


@admins_router.callback_query(F.data.startswith("admin_edit_admin:"))
async def admin_edit_admin(callback: CallbackQuery):
    """Редактирование группы админа"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
        
        try:
            target_telegram_id = int(callback.data.split(":")[1])
        except Exception:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        
        target_user = await get_user_by_telegram_id(session, target_telegram_id)
        if not target_user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        username = f"@{target_user.username}" if target_user.username else f"ID: {target_user.telegram_id}"
        name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip() or username
        current_group = ADMIN_GROUP_NAMES.get(target_user.admin_group, "Нет") if target_user.admin_group else "Нет"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{ADMIN_GROUP_EMOJIS[ADMIN_GROUP_CREATOR]} {ADMIN_GROUP_NAMES[ADMIN_GROUP_CREATOR]}",
                callback_data=f"admin_set_group:{target_telegram_id}:{ADMIN_GROUP_CREATOR}"
            )],
            [InlineKeyboardButton(
                text=f"{ADMIN_GROUP_EMOJIS[ADMIN_GROUP_DEVELOPER]} {ADMIN_GROUP_NAMES[ADMIN_GROUP_DEVELOPER]}",
                callback_data=f"admin_set_group:{target_telegram_id}:{ADMIN_GROUP_DEVELOPER}"
            )],
            [InlineKeyboardButton(
                text=f"{ADMIN_GROUP_EMOJIS[ADMIN_GROUP_CURATOR]} {ADMIN_GROUP_NAMES[ADMIN_GROUP_CURATOR]}",
                callback_data=f"admin_set_group:{target_telegram_id}:{ADMIN_GROUP_CURATOR}"
            )],
            [InlineKeyboardButton(
                text="❌ Убрать права админа",
                callback_data=f"admin_remove_admin:{target_telegram_id}"
            )],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_manage_admins")]
        ])
        
        await callback.message.edit_text(
            f"<b>👤 Пользователь:</b> {name} ({username})\n"
            f"<b>Текущая группа:</b> {current_group}\n\n"
            f"Выберите группу администратора:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()


@admins_router.callback_query(F.data.startswith("admin_set_group:"))
async def admin_set_group(callback: CallbackQuery):
    """Установка группы админа"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
        
        try:
            parts = callback.data.split(":")
            target_telegram_id = int(parts[1])
            group = parts[2]
        except Exception:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        
        if group not in [ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR]:
            await callback.answer("Некорректная группа", show_alert=True)
            return
        
        target_user = await get_user_by_telegram_id(session, target_telegram_id)
        if not target_user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Сохраняем старую группу для уведомления
        old_group = target_user.admin_group
        
        # Обновляем группу
        await session.execute(
            update(User)
            .where(User.id == target_user.id)
            .values(admin_group=group, updated_at=datetime.now())
        )
        await session.commit()
        
        group_name = ADMIN_GROUP_NAMES.get(group, group)
        group_emoji = ADMIN_GROUP_EMOJIS.get(group, "")
        username = f"@{target_user.username}" if target_user.username else f"ID: {target_user.telegram_id}"
        name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip() or username
        
        await callback.answer(f"✅ Пользователю {name} назначена группа: {group_emoji} {group_name}", show_alert=True)
        
        # Отправляем уведомление пользователю
        try:
            if old_group != group:  # Только если группа действительно изменилась
                notification_text = (
                    f"✨ <b>Ваш статус администратора обновлен!</b>\n\n"
                    f"{group_emoji} <b>{group_name}</b>\n\n"
                    f"Теперь у вас есть доступ к административной панели Mom's Club.\n"
                    f"Используйте команду /admin для входа в админ-панель.\n\n"
                    f"💎 Ваш статус отображается в личном кабинете."
                )
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")],
                    [InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_back")]
                ])
                
                await callback.bot.send_message(
                    chat_id=target_user.telegram_id,
                    text=notification_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                logger.info(f"Отправлено уведомление пользователю {target_user.telegram_id} о назначении группы {group}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {target_user.telegram_id}: {e}")
        
        # Возвращаемся к списку админов
        await admin_manage_admins_menu(callback)


@admins_router.callback_query(F.data.startswith("admin_remove_admin:"))
async def admin_remove_admin(callback: CallbackQuery):
    """Удаление прав админа"""
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user) or not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
        
        try:
            target_telegram_id = int(callback.data.split(":")[1])
        except Exception:
            await callback.answer("Некорректные данные", show_alert=True)
            return
        
        target_user = await get_user_by_telegram_id(session, target_telegram_id)
        if not target_user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Сохраняем старую группу для уведомления
        old_group = target_user.admin_group
        
        # Убираем группу админа
        await session.execute(
            update(User)
            .where(User.id == target_user.id)
            .values(admin_group=None, updated_at=datetime.now())
        )
        await session.commit()
        
        username = f"@{target_user.username}" if target_user.username else f"ID: {target_user.telegram_id}"
        name = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip() or username
        
        await callback.answer(f"✅ У пользователя {name} убраны права администратора", show_alert=True)
        
        # Отправляем уведомление пользователю
        try:
            if old_group:  # Только если у пользователя была группа админа
                old_group_name = ADMIN_GROUP_NAMES.get(old_group, "администратора")
                old_group_emoji = ADMIN_GROUP_EMOJIS.get(old_group, "")
                
                notification_text = (
                    f"ℹ️ <b>Изменение статуса администратора</b>\n\n"
                    f"У вас были сняты права {old_group_emoji} <b>{old_group_name}</b>.\n\n"
                    f"Теперь вы являетесь обычным пользователем Mom's Club.\n"
                    f"Спасибо за вашу работу в качестве администратора! 💙"
                )
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
                ])
                
                await callback.bot.send_message(
                    chat_id=target_user.telegram_id,
                    text=notification_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                logger.info(f"Отправлено уведомление пользователю {target_user.telegram_id} о снятии прав админа")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {target_user.telegram_id}: {e}")
        
        # Возвращаемся к списку админов
        await admin_manage_admins_menu(callback)

