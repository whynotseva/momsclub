from aiogram import Router, types, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from database.config import AsyncSessionLocal
from database.crud import (
    get_total_users_count, 
    get_active_subscriptions_count, 
    get_expired_subscriptions_count, 
    get_total_payments_amount,
    get_user_by_telegram_id,
    get_active_subscription,
    extend_subscription,
    create_payment_log,
    get_user_by_username,
    get_all_users_with_subscriptions,
    get_users_with_active_subscriptions,
    get_users_with_expired_subscriptions,
    deactivate_subscription,
    create_subscription,
    get_user_by_id,
    get_total_promo_code_uses_count,
    has_user_used_any_promo_code,
    get_all_promo_codes,
    delete_promo_code_by_id,
    get_promo_code_by_code,
    create_promo_code,
    get_total_promo_codes_count,
    has_active_subscription,  # Добавлен импорт недостающей функции
    update_promo_code, # <-- Добавляем импорт
    get_sorted_active_subscriptions, # <-- Добавляем импорт новой функции
    get_users_with_birthdays, # <-- Добавляем импорт для функции дней рождения
    get_pending_cancellation_requests,
    get_cancellation_request_by_id,
    update_cancellation_request_status,
    mark_cancellation_request_contacted,
    disable_user_auto_renewal,
    get_all_cancellation_requests,
    get_cancellation_requests_stats
)
from database.models import User, Subscription, PromoCode
from datetime import datetime, timedelta
import os
import re # <-- Добавляем импорт модуля re
from utils.helpers import log_message
from utils.constants import CLUB_CHANNEL_URL, ADMIN_IDS, CLUB_GROUP_ID, NOTIFICATION_DAYS_BEFORE, SUBSCRIPTION_PRICE, SUBSCRIPTION_DAYS
from sqlalchemy import update, select
import pandas as pd
import openpyxl
import logging
import math # <-- Добавляем импорт math для ceil
import asyncio # <-- Добавляем импорт asyncio
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from typing import Optional
# Удаляем импорт escape_markdown_v2 отсюда
# from aiogram.utils.markdown import escape_markdown_v2

# Меняем импорт escape_markdown_v2 из user_handlers на helpers
# from .user_handlers import escape_markdown_v2
from utils.helpers import escape_markdown_v2

# Константа для пагинации промокодов
PROMO_PAGE_SIZE = 5 # Количество промокодов на странице

# Создаем роутер для административных команд
admin_router = Router()
logger = logging.getLogger(__name__)

# Список ID администраторов
ADMIN_IDS = []
admin_ids_str = os.getenv("ADMIN_ID", "")
if admin_ids_str:
    try:
        # Разбиваем строку с ID администраторов по запятой
        ADMIN_IDS = [int(admin_id.strip()) for admin_id in admin_ids_str.split(",") if admin_id.strip()]
        logger.info(f"Загружены ID администраторов: {ADMIN_IDS}")
        if not ADMIN_IDS:
            logger.warning("ВНИМАНИЕ: Список администраторов пуст! Проверьте переменную окружения ADMIN_ID")
    except Exception as e:
        logger.error(f"Ошибка при загрузке ID администраторов: {e}", exc_info=True)
        logger.critical("ВНИМАНИЕ: Установка ID администратора по умолчанию не выполнена. Административные функции будут недоступны!")
else:
    logger.critical("ВНИМАНИЕ: Переменная окружения ADMIN_ID не установлена. Административные функции будут недоступны!")

# Состояния для FSM (конечного автомата)
class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()
    waiting_for_end_date = State()
    export_type = State()
    waiting_for_test_user_id = State()
    waiting_for_test_minutes = State()
    # Состояния для создания промокода
    waiting_for_promo_code_text = State()
    waiting_for_promo_value = State()
    waiting_for_promo_max_uses = State()
    waiting_for_promo_expiry_date = State()
    # Состояния для редактирования промокода
    editing_promo = State() # Общее состояние для отображения информации
    editing_promo_max_uses = State()
    editing_promo_expiry_date = State()
    # Состояния для рассылки сообщений
    broadcast_format = State() # Выбор формата (HTML или MarkdownV2)
    broadcast_text = State() # Ввод текста сообщения
    broadcast_media = State() # Прикрепление медиа (опционально)
    broadcast_confirm = State() # Подтверждение отправки
    broadcast_error_page = State() # Состояние для пагинации ошибок рассылки
    
# Обработчик команды /admin для проверки прав
@admin_router.message(Command("admin"))
async def cmd_admin_check(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Вызвана команда /admin от пользователя с ID: {user_id}")
    if not ADMIN_IDS:
         logger.warning("Список ADMIN_IDS пуст или не загружен!")

    if user_id in ADMIN_IDS:
        logger.info(f"Доступ разрешен для ID {user_id}")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
                [InlineKeyboardButton(text="👤 Поиск пользователя", callback_data="admin_find_user")],
                [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_grant_subscription")],
                [InlineKeyboardButton(text="📣 Рассылка сообщений", callback_data="admin_broadcast")],
                [InlineKeyboardButton(text="📨 Сообщения пользователям", callback_data="admin_direct_message")],
                [InlineKeyboardButton(text="📝 Шаблоны сообщений", callback_data="admin_message_templates")],
                [InlineKeyboardButton(text="🎟️ Управление промокодами", callback_data="admin_manage_promocodes")],
                [InlineKeyboardButton(text="📅 Сроки подписок", callback_data="admin_subscription_dates")],
                [InlineKeyboardButton(text="🎂 Дни рождения пользователей", callback_data="admin_birthdays:0")],
                [InlineKeyboardButton(text="🚫 Заявки на отмену автопродления", callback_data="admin_cancellation_requests")],
                [InlineKeyboardButton(text="📥 Экспорт пользователей", callback_data="admin_export_users")],
                [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]
            ]
        )
        
        # Локальный баннер для админки
        banner_path = os.path.join(os.getcwd(), "media", "админка.jpg")
        
        # Отправляем баннер с подписью и кнопками
        banner_photo = FSInputFile(banner_path)
        await message.answer_photo(
            photo=banner_photo,
            caption="Панель администратора Mom\'s Club:",
            reply_markup=keyboard
        )
    else:
        logger.warning(f"В доступе отказано для ID {user_id}")
        await message.answer("У вас нет прав доступа к этой команде.")

# Обработчик запроса статистики
@admin_router.callback_query(F.data == "admin_stats")
async def process_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    try:
        # Показываем индикатор загрузки
        await callback.answer("Загрузка статистики...", show_alert=False)
        
        # Получение статистики из базы данных
        async with AsyncSessionLocal() as session:
            total_users = await get_total_users_count(session)
            active_subs = await get_active_subscriptions_count(session)
            expired_subs = await get_expired_subscriptions_count(session)
            total_payments = await get_total_payments_amount(session)
            total_promo_uses = await get_total_promo_code_uses_count(session)
        
        # Расчет дополнительной статистики
        conversion_rate = round((active_subs / total_users * 100), 1) if total_users > 0 else 0
        avg_payment = round(total_payments / (active_subs + expired_subs), 1) if (active_subs + expired_subs) > 0 else 0
        
        # Формирование текста статистики с текущей датой
        current_time = datetime.now().strftime('%d.%m.%Y %H:%M')
        stats_text = f"""
<b>📊 Статистика Mom's Club:</b>

👥 <b>Всего пользователей:</b> {total_users}
✅ <b>Активных подписок:</b> {active_subs}
❌ <b>Истекших подписок:</b> {expired_subs}
🎁 <b>Использовано промокодов:</b> {total_promo_uses} раз(а)
💰 <b>Общая сумма платежей:</b> {total_payments} ₽

📈 <b>Конверсия (активные/всего):</b> {conversion_rate}%
💵 <b>Средний платеж:</b> {avg_payment} ₽

<i>Данные актуальны на: {current_time}</i>
"""
        
        # Кнопки для действий со статистикой
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Обновить данные", callback_data="admin_stats")],
                [InlineKeyboardButton(text="📥 Экспорт пользователей", callback_data="admin_export_users")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
            ]
        )
        
        # Отправляем новое сообщение вместо редактирования
        try:
            # Удаляем текущее сообщение
            await callback.message.delete()
            
            # Отправляем статистику в новом сообщении
            await callback.message.answer(
                stats_text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
            
        except Exception as edit_error:
            # Если не можем удалить сообщение, отправляем новое
            logging.error(f"Ошибка при обновлении статистики: {edit_error}", exc_info=True)
            await callback.message.answer(
                stats_text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
    
    except Exception as e:
        # Обработка ошибок при получении статистики
        logging.error(f"Ошибка при получении статистики: {e}", exc_info=True)
        
        # Сообщаем об ошибке
        try:
            # Удаляем текущее сообщение и отправляем новое с ошибкой
            await callback.message.delete()
            
            await callback.message.answer(
                f"❌ Произошла ошибка при получении статистики: {str(e)}\n\nПожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="admin_stats")],
                        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
                    ]
                )
            )
        except Exception:
            # Если не удалось удалить, пробуем просто отправить новое сообщение
            await callback.message.answer(
                f"❌ Произошла ошибка при получении статистики: {str(e)}\n\nПожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="admin_stats")],
                        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
                    ]
                )
            )

# Обработчик поиска пользователя
@admin_router.callback_query(F.data == "admin_find_user")
async def process_find_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_user_id)
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            "Введите Telegram ID или Username пользователя для поиска:\n"
            "(ID должен быть числом, username - с символом @)",
            reply_markup=keyboard
        )
    except Exception as e:
        # Если не можем удалить, просто отправляем новое сообщение
        logger.error(f"Ошибка при удалении сообщения в процессе поиска пользователя: {e}")
        await callback.message.answer(
            "Введите Telegram ID или Username пользователя для поиска:\n"
            "(ID должен быть числом, username - с символом @)",
            reply_markup=keyboard
        )
    
    await callback.answer()

# Обработчик ID пользователя
@admin_router.message(StateFilter(AdminStates.waiting_for_user_id))
async def process_user_id(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    search_term = message.text.strip()
    
    async with AsyncSessionLocal() as session:
        user = None
        
        # Определяем, это ID или username
        if search_term.startswith("@"):
            # Поиск по username (убираем @ в начале)
            username = search_term[1:]
            # Импортируем нужную функцию для поиска по username
            user = await get_user_by_username(session, username)
        else:
            try:
                # Поиск по ID
                user_id = int(search_term)
                user = await get_user_by_telegram_id(session, user_id)
            except ValueError:
                await message.answer("❌ Некорректный формат! Введите числовой ID или username с символом @")
                return
        
        if user:
            # Получаем информацию о подписке
            subscription = await get_active_subscription(session, user.id)
            
            if subscription:
                days_left = (subscription.end_date - datetime.now()).days
                subscription_status = f"✅ Активна до {subscription.end_date.strftime('%d.%m.%Y')} (осталось дней: {days_left})"
            else:
                subscription_status = "❌ Отсутствует или истекла"
            
            user_info = f"""
<b>👤 Информация о пользователе:</b>

<b>ID в базе:</b> {user.id}
<b>Telegram ID:</b> {user.telegram_id}
<b>Username:</b> {user.username or "Не указан"}
<b>Имя:</b> {user.first_name or "Не указано"}
<b>Фамилия:</b> {user.last_name or "Не указана"}
<b>Статус:</b> {"Активен" if user.is_active else "Неактивен"}
<b>Создан:</b> {user.created_at.strftime('%d.%m.%Y %H:%M')}
<b>Обновлен:</b> {user.updated_at.strftime('%d.%m.%Y %H:%M')}

<b>Подписка:</b> {subscription_status}
"""
            
            # Кнопки управления пользователем
            keyboard = InlineKeyboardButton(text="🎁 Выдать подписку", callback_data=f"admin_grant:{user.telegram_id}")
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [keyboard],
                    [
                        InlineKeyboardButton(text="➕ Добавить 30 дней", callback_data=f"admin_add_days:{user.telegram_id}:30"),
                        InlineKeyboardButton(text="➖ Убрать 30 дней", callback_data=f"admin_reduce_days:{user.telegram_id}:30")
                    ],
                    [InlineKeyboardButton(text="📨 Написать пользователю", callback_data=f"admin_message_to:{user.telegram_id}")],
                    [InlineKeyboardButton(text="🚫 Забанить пользователя", callback_data=f"admin_ban_user:{user.telegram_id}")],
                    [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
                ]
            )
            
            await message.answer(user_info, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(f"❌ Пользователь '{search_term}' не найден.")
        
        # Сбрасываем состояние
        await state.clear()

# Обработчик добавления дней к подписке
@admin_router.callback_query(F.data.startswith("admin_add_days:"))
async def process_add_days(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Разбираем данные из callback
    parts = callback.data.split(":")
    telegram_id = int(parts[1])
    days = int(parts[2])
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем текущую подписку
        subscription = await get_active_subscription(session, user.id)
        
        if subscription:
            # Продлеваем подписку на указанное количество дней
            new_subscription = await extend_subscription(session, user.id, days, 0, "admin_extension")
            
            # Определяем кол-во оставшихся дней
            days_left = (new_subscription.end_date - datetime.now()).days
            
            # Отправляем уведомление
            await callback.answer(f"Подписка продлена на {days} дней", show_alert=True)
            
            # Обновляем информацию о пользователе
            await process_update_user_info(callback, telegram_id)
        else:
            # Если подписки нет, создаем новую
            end_date = datetime.now() + timedelta(days=days)
            await create_subscription(session, user.id, end_date, 0, "admin_grant")
            
            await callback.answer(f"Выдана новая подписка на {days} дней", show_alert=True)
            
            # Обновляем информацию о пользователе
            await process_update_user_info(callback, telegram_id)

# Обработчик уменьшения дней подписки
@admin_router.callback_query(F.data.startswith("admin_reduce_days:"))
async def process_reduce_days(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Разбираем данные из callback
    parts = callback.data.split(":")
    telegram_id = int(parts[1])
    days = int(parts[2])
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем текущую подписку
        subscription = await get_active_subscription(session, user.id)
        
        if subscription:
            # Уменьшаем срок подписки
            new_end_date = subscription.end_date - timedelta(days=days)
            
            # Если новая дата окончания в прошлом, деактивируем подписку
            if new_end_date < datetime.now():
                await deactivate_subscription(session, subscription.id)
                await callback.answer("Подписка деактивирована, т.к. новая дата окончания в прошлом", show_alert=True)
            else:
                # Обновляем дату окончания
                query = (
                    update(Subscription)
                    .where(Subscription.id == subscription.id)
                    .values(end_date=new_end_date)
                )
                await session.execute(query)
                await session.commit()
                
                # Отправляем уведомление
                await callback.answer(f"Срок подписки уменьшен на {days} дней", show_alert=True)
            
            # Обновляем информацию о пользователе
            await process_update_user_info(callback, telegram_id)
        else:
            # Если подписки нет
            await callback.answer("У пользователя нет активной подписки", show_alert=True)

# Функция обновления информации о пользователе
async def process_update_user_info(callback: CallbackQuery, telegram_id: int):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем информацию о подписке
        subscription = await get_active_subscription(session, user.id)
        
        if subscription:
            days_left = (subscription.end_date - datetime.now()).days
            subscription_status = f"✅ Активна до {subscription.end_date.strftime('%d.%m.%Y')} (осталось дней: {days_left})"
        else:
            subscription_status = "❌ Отсутствует или истекла"
        
        user_info = f"""
<b>👤 Информация о пользователе:</b>

<b>ID в базе:</b> {user.id}
<b>Telegram ID:</b> {user.telegram_id}
<b>Username:</b> {user.username or "Не указан"}
<b>Имя:</b> {user.first_name or "Не указано"}
<b>Фамилия:</b> {user.last_name or "Не указана"}
<b>Статус:</b> {"Активен" if user.is_active else "Неактивен"}
<b>Создан:</b> {user.created_at.strftime('%d.%m.%Y %H:%M')}
<b>Обновлен:</b> {user.updated_at.strftime('%d.%m.%Y %H:%M')}

<b>Подписка:</b> {subscription_status}
"""
        
        # Кнопки управления пользователем
        keyboard = InlineKeyboardButton(text="🎁 Выдать подписку", callback_data=f"admin_grant:{user.telegram_id}")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [keyboard],
                [
                    InlineKeyboardButton(text="➕ Добавить 30 дней", callback_data=f"admin_add_days:{user.telegram_id}:30"),
                    InlineKeyboardButton(text="➖ Убрать 30 дней", callback_data=f"admin_reduce_days:{user.telegram_id}:30")
                ],
                [InlineKeyboardButton(text="📨 Написать пользователю", callback_data=f"admin_message_to:{user.telegram_id}")],
                [InlineKeyboardButton(text="🚫 Забанить пользователя", callback_data=f"admin_ban_user:{user.telegram_id}")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
            ]
        )
        
        # Обновляем сообщение с информацией
        await callback.message.edit_text(user_info, reply_markup=keyboard, parse_mode="HTML")

# Обработчик бана пользователя
@admin_router.callback_query(F.data.startswith("admin_ban_user:"))
async def process_ban_user(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID пользователя
    telegram_id = int(callback.data.split(":")[1])
    
    # Запрашиваем подтверждение
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_ban_confirm:{telegram_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_user_info:{telegram_id}")
            ]
        ]
    )
    
    await callback.message.edit_text(
        f"⚠️ <b>Вы действительно хотите забанить пользователя ID {telegram_id}?</b>\n\n"
        f"Это действие исключит пользователя из группы и деактивирует его подписку.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

# Обработчик подтверждения бана
@admin_router.callback_query(F.data.startswith("admin_ban_confirm:"))
async def process_ban_confirm(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID пользователя
    telegram_id = int(callback.data.split(":")[1])
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        try:
            # Импортируем GroupManager для исключения из группы
            from utils.group_manager import GroupManager
            group_manager = GroupManager(callback.bot)
            
            # Исключаем пользователя из группы
            kicked = await group_manager.kick_user(telegram_id)
            
            # Деактивируем подписку
            subscription = await get_active_subscription(session, user.id)
            if subscription:
                await deactivate_subscription(session, subscription.id)
            
            # Отмечаем пользователя как неактивного
            query = (
                update(User)
                .where(User.id == user.id)
                .values(is_active=False)
            )
            await session.execute(query)
            await session.commit()
            
            # Уведомляем о результате
            if kicked:
                status_text = "Пользователь успешно забанен и исключен из группы."
            else:
                status_text = "Пользователь забанен в системе, но возникла ошибка при исключении из группы."
            
            await callback.answer(status_text, show_alert=True)
            
            # Возвращаемся к информации о пользователе
            await process_update_user_info(callback, telegram_id)
            
        except Exception as e:
            logging.error(f"Ошибка при бане пользователя {telegram_id}: {e}", exc_info=True)
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

# Обработчик выдачи подписки
@admin_router.callback_query(F.data == "admin_grant_subscription")
async def process_grant_subscription(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_user_id)
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            "Введите Telegram ID пользователя, которому хотите выдать подписку:",
            reply_markup=keyboard
        )
    except Exception as e:
        # Если не можем удалить, просто отправляем новое сообщение
        logger.error(f"Ошибка при удалении сообщения в процессе выдачи подписки: {e}")
        await callback.message.answer(
            "Введите Telegram ID пользователя, которому хотите выдать подписку:",
            reply_markup=keyboard
        )
        
    await callback.answer()

# Обработчик выдачи подписки конкретному пользователю
@admin_router.callback_query(F.data.startswith("admin_grant:"))
async def process_grant_specific(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Извлекаем Telegram ID пользователя из callback data
    user_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID в состоянии
    await state.update_data(telegram_id=user_id)
    await state.set_state(AdminStates.waiting_for_days)
    
    # Клавиатура с предустановленными сроками
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="30 дней", callback_data="admin_days:30"),
                InlineKeyboardButton(text="60 дней", callback_data="admin_days:60"),
                InlineKeyboardButton(text="90 дней", callback_data="admin_days:90")
            ],
            [
                InlineKeyboardButton(text="✨ Пожизненно", callback_data="admin_lifetime"),
                InlineKeyboardButton(text="🗓 Указать дату", callback_data="admin_set_date")
            ],
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    await callback.message.edit_text(
        f"На сколько дней выдать подписку пользователю ID {user_id}?\n"
        "Выберите из предложенных вариантов или введите количество дней:",
        reply_markup=keyboard
    )
    await callback.answer()

# Обработчик выбора предустановленного количества дней
@admin_router.callback_query(F.data.startswith("admin_days:"))
async def process_preset_days(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Извлекаем количество дней из callback data
    days = int(callback.data.split(":")[1])
    
    # Получаем Telegram ID пользователя из состояния
    user_data = await state.get_data()
    telegram_id = user_data.get("telegram_id")
    
    # Выдаем подписку
    await grant_subscription(callback.message, telegram_id, days)
    
    # Сбрасываем состояние
    await state.clear()
    await callback.answer()

# Обработчик ввода количества дней
@admin_router.message(StateFilter(AdminStates.waiting_for_days))
async def process_days_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        days = int(message.text.strip())
        
        if days <= 0:
            await message.answer("Количество дней должно быть положительным числом. Попробуйте еще раз:")
            return
        
        # Получаем Telegram ID пользователя из состояния
        user_data = await state.get_data()
        telegram_id = user_data.get("telegram_id")
        
        # Выдаем подписку
        await grant_subscription(message, telegram_id, days)
        
        # Сбрасываем состояние
        await state.clear()
    
    except ValueError:
        await message.answer("Пожалуйста, введите корректное количество дней (только цифры)")

# Обработчик выбора пожизненной подписки
@admin_router.callback_query(F.data == "admin_lifetime")
async def process_lifetime_subscription(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем Telegram ID пользователя из состояния
    user_data = await state.get_data()
    telegram_id = user_data.get("telegram_id")
    
    # Выдаем пожизненную подписку
    await grant_subscription(callback.message, telegram_id, days=0, is_lifetime=True)
    
    # Сбрасываем состояние
    await state.clear()
    await callback.answer()

# Обработчик для указания конкретной даты окончания подписки
@admin_router.callback_query(F.data == "admin_set_date")
async def process_set_date(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_end_date)
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    # Текущая дата для примера
    current_date = datetime.now().strftime("%d_%m_%Y")
    
    await callback.message.edit_text(
        "Введите дату окончания подписки в формате ДД_ММ_ГГГГ\n"
        f"Например: {current_date}",
        reply_markup=keyboard
    )
    await callback.answer()

# Обработчик ввода даты окончания подписки
@admin_router.message(StateFilter(AdminStates.waiting_for_end_date))
async def process_end_date_input(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    date_input = message.text.strip()
    
    try:
        # Разбираем введенную дату
        day, month, year = map(int, date_input.split('_'))
        end_date = datetime(year, month, day, 23, 59, 59)  # Устанавливаем время на конец дня
        
        # Проверяем, что дата не в прошлом
        if end_date < datetime.now():
            await message.answer("❌ Нельзя установить дату окончания в прошлом. Пожалуйста, введите корректную дату:")
            return
        
        # Получаем Telegram ID пользователя из состояния
        user_data = await state.get_data()
        telegram_id = user_data.get("telegram_id")
        
        # Выдаем подписку с конкретной датой окончания
        await grant_subscription(message, telegram_id, days=0, is_lifetime=False, end_date=end_date)
        
        # Сбрасываем состояние
        await state.clear()
    
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Пожалуйста, введите дату в формате ДД_ММ_ГГГГ\n"
            "Например: 31_12_2023"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при обработке даты: {str(e)}")

# Функция выдачи подписки
async def grant_subscription(message, telegram_id, days, is_lifetime=False, end_date=None):
    """
    Выдает подписку пользователю по Telegram ID
    
    Args:
        message: Сообщение пользователя
        telegram_id: Telegram ID пользователя
        days: Количество дней (если не lifetime)
        is_lifetime: Флаг бессрочной подписки
        end_date: Конкретная дата окончания (если указана)
    """
    bot = message.bot  # Всегда используем корректный объект бота для уведомлений
    
    # Форматирование деталей для логов
    if is_lifetime:
        details = "Бессрочная подписка, выдана администратором"
    elif end_date:
        details = f"Подписка до {end_date.strftime('%d.%m.%Y')}, выдана администратором"
    else:
        details = f"Подписка на {days} дней, выдана администратором"
    
    # Рассчитываем дату окончания, если не указана
    if not end_date and not is_lifetime:
        end_date = datetime.now() + timedelta(days=days)
    elif is_lifetime:
        # Для бессрочной подписки ставим дату через 100 лет
        end_date = datetime.now() + timedelta(days=36500)  # ~100 лет
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
        ]
    )
    
    try:
        async with AsyncSessionLocal() as session:
            # Получаем пользователя
            user = await get_user_by_telegram_id(session, telegram_id)
            
            if not user:
                await message.answer(f"❌ Пользователь с ID {telegram_id} не найден", reply_markup=keyboard)
                return False
            
            # Проверяем есть ли активная подписка
            has_subscription = await has_active_subscription(session, user.id)
            
            # Создаем новую подписку или продлеваем существующую
            if has_subscription:
                # Если есть активная, но выбрана опция lifetime, то деактивируем старую
                if is_lifetime:
                    # Получаем текущую активную подписку
                    active_sub = await get_active_subscription(session, user.id)
                    if active_sub:
                        # Деактивируем
                        await deactivate_subscription(session, active_sub.id)
                        
                        # И создаем новую
                        new_sub = await create_subscription(session, user.id, end_date, 0, "admin_lifetime")
                    else:
                        # На всякий случай, если has_active_subscription и get_active_subscription не согласованы
                        new_sub = await create_subscription(session, user.id, end_date, 0, "admin_lifetime")
                elif end_date:
                    # Если указана конкретная дата окончания
                    active_sub = await get_active_subscription(session, user.id)
                    if active_sub:
                        # Обновляем дату окончания
                        query = (
                            update(Subscription)
                            .where(Subscription.id == active_sub.id)
                            .values(end_date=end_date)
                        )
                        await session.execute(query)
                        await session.commit()
                        
                        # Получаем обновленную подписку
                        await session.refresh(active_sub)
                        new_sub = active_sub
                    else:
                        # На всякий случай
                        new_sub = await create_subscription(session, user.id, end_date, 0, "admin_date")
                else:
                    # Продлеваем на указанное количество дней
                    new_sub = await extend_subscription(session, user.id, days, 0, "admin_extend")
                
                # Создаем запись в логе платежей для истории и отчётности
                await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=new_sub.id,
                    amount=0,  # Бесплатно
                    status="success",
                    payment_method="admin",
                    transaction_id=None,
                    details=details
                )
                
                # Отправляем уведомление об успехе
                days_text = "бессрочно" if is_lifetime else f"до {new_sub.end_date.strftime('%d.%m.%Y')}"
                
                await message.answer(
                    f"✅ Пользователю {user.first_name or ''} {user.last_name or ''} "
                    f"(@{user.username or str(user.telegram_id)}) успешно обновлена подписка!\n\n"
                    f"Подписка активна {days_text}.",
                    reply_markup=keyboard
                )
                
                # Отправляем уведомление пользователю
                try:
                    user_notification = (
                        f"🎁 Администратор продлил вашу подписку на Mom's Club!\n\n"
                        f"Ваша подписка теперь активна {days_text}.\n\n"
                        f"Вы можете перейти в закрытый канал по кнопке ниже:"
                    )
                    
                    user_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)]
                        ]
                    )
                    
                    await bot.send_message(
                        user.telegram_id,
                        user_notification,
                        reply_markup=user_keyboard
                    )
                except Exception as e:
                    # Если не удалось отправить уведомление пользователю
                    logging.error(f"Ошибка при отправке уведомления пользователю {user.telegram_id} о продлении подписки: {e}")
                    # Сообщаем администратору, но не считаем это ошибкой выдачи подписки
                    await message.answer(
                        f"⚠️ Подписка успешно продлена, но не удалось отправить уведомление пользователю: {str(e)}",
                        reply_markup=keyboard
                    )
                
                return True
            else:
                # Создаем новую подписку
                new_sub = await create_subscription(session, user.id, end_date, 0, "admin_grant")
                
                # Создаем запись в логе платежей
                await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=new_sub.id,
                    amount=0,  # Бесплатно
                    status="success",
                    payment_method="admin",
                    transaction_id=None,
                    details=details
                )
                
                # Отправляем уведомление об успехе
                days_text = "бессрочно" if is_lifetime else f"до {new_sub.end_date.strftime('%d.%m.%Y')}"
                
                await message.answer(
                    f"✅ Пользователю {user.first_name or ''} {user.last_name or ''} "
                    f"(@{user.username or str(user.telegram_id)}) успешно выдана подписка!\n\n"
                    f"Подписка активна {days_text}.",
                    reply_markup=keyboard
                )
                
                # Отправляем уведомление пользователю
                try:
                    user_notification = (
                        f"🎁 Администратор выдал вам подписку на Mom's Club!\n\n"
                        f"Ваша подписка активна {days_text}.\n\n"
                        f"Вы можете перейти в закрытый канал по кнопке ниже:"
                    )
                    
                    user_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)]
                        ]
                    )
                    
                    await bot.send_message(
                        user.telegram_id,
                        user_notification,
                        reply_markup=user_keyboard
                    )
                except Exception as e:
                    # Если не удалось отправить уведомление пользователю
                    logging.error(f"Ошибка при отправке уведомления пользователю {user.telegram_id}: {e}")
                    # Сообщаем администратору
                    await message.answer(
                        f"⚠️ Подписка успешно выдана, но не удалось отправить уведомление пользователю: {str(e)}",
                        reply_markup=keyboard
                    )
                
                return True
    
    except Exception as e:
        logging.error(f"Ошибка при выдаче подписки пользователю {telegram_id}: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка при выдаче подписки: {str(e)}", reply_markup=keyboard)
        return False

# Обработчик отмены операции
@admin_router.callback_query(F.data == "admin_cancel")
async def process_cancel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Сбрасываем состояние
    await state.clear()
    
    # Возвращаемся в главное меню администратора
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="👤 Поиск пользователя", callback_data="admin_find_user")],
            [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_grant_subscription")],
            [InlineKeyboardButton(text="📣 Рассылка сообщений", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="📨 Сообщения пользователям", callback_data="admin_direct_message")],
            [InlineKeyboardButton(text="📝 Шаблоны сообщений", callback_data="admin_message_templates")],
            [InlineKeyboardButton(text="🎟️ Управление промокодами", callback_data="admin_manage_promocodes")],
            [InlineKeyboardButton(text="📅 Сроки подписок", callback_data="admin_subscription_dates")],
            [InlineKeyboardButton(text="🎂 Дни рождения пользователей", callback_data="admin_birthdays:0")],
            [InlineKeyboardButton(text="🚫 Заявки на отмену автопродления", callback_data="admin_cancellation_requests")],
            [InlineKeyboardButton(text="📥 Экспорт пользователей", callback_data="admin_export_users")],
            [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]
        ]
    )
    
    try:
        # Локальный баннер для админки
        banner_path = os.path.join(os.getcwd(), "media", "админка.jpg")
        
        # Сначала удаляем текущее сообщение, затем отправляем новое с баннером
        await callback.message.delete()
        
        # Отправляем баннер с подписью и кнопками
        banner_photo = FSInputFile(banner_path)
        await callback.message.answer_photo(
            photo=banner_photo,
            caption="Операция отменена.\nПанель администратора Mom's Club:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при возврате в главное меню админки после отмены: {e}")
        # Если удаление не удалось, пробуем просто отправить новое сообщение
        banner_photo_fallback = FSInputFile(os.path.join(os.getcwd(), "media", "админка.jpg"))
        await callback.message.answer_photo(
            photo=banner_photo_fallback,
            caption="Операция отменена.\nПанель администратора Mom's Club:",
            reply_markup=keyboard
        )
    
    await callback.answer()

# Обработчик возврата в главное меню
@admin_router.callback_query(F.data == "admin_back")
async def process_back(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Вернуться в меню'"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Проверяем, находимся ли мы в состоянии просмотра ошибок рассылки
    current_state = await state.get_state()
    if current_state == AdminStates.broadcast_error_page.state:
        # Сбрасываем состояние при выходе из просмотра ошибок
        await state.clear()
    
    # Отвечаем на колбэк, чтобы убрать часики
    await callback.answer()
    
    # Отображаем главное меню администратора
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="👤 Поиск пользователя", callback_data="admin_find_user")],
            [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_grant_subscription")],
            [InlineKeyboardButton(text="📣 Рассылка сообщений", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="📨 Сообщения пользователям", callback_data="admin_direct_message")],
            [InlineKeyboardButton(text="📝 Шаблоны сообщений", callback_data="admin_message_templates")],
            [InlineKeyboardButton(text="🎟️ Управление промокодами", callback_data="admin_manage_promocodes")],
            [InlineKeyboardButton(text="📅 Сроки подписок", callback_data="admin_subscription_dates")],
            [InlineKeyboardButton(text="🎂 Дни рождения пользователей", callback_data="admin_birthdays:0")],
            [InlineKeyboardButton(text="🚫 Заявки на отмену автопродления", callback_data="admin_cancellation_requests")],
            [InlineKeyboardButton(text="📥 Экспорт пользователей", callback_data="admin_export_users")],
            [InlineKeyboardButton(text="✖️ Закрыть", callback_data="admin_close")]
        ]
    )
    
    # Локальный баннер для админки
    banner_path = os.path.join(os.getcwd(), "media", "админка.jpg")
    banner_photo = FSInputFile(banner_path)
    
    # Пытаемся редактировать сообщение, если оно с фото
    try:
        if callback.message.photo:
            # Если сообщение с фото - редактируем его
            await callback.message.edit_caption(
                caption="Панель администратора Mom\'s Club:",
                reply_markup=keyboard
            )
        else:
            # Если текстовое сообщение - удаляем и отправляем новое с фото
            try:
                await callback.message.delete()
            except:
                pass
            await callback.message.answer_photo(
                photo=banner_photo,
                caption="Панель администратора Mom\'s Club:",
                reply_markup=keyboard
            )
    except Exception as e:
        # Если редактирование не удалось - удаляем и отправляем новое
        logger.warning(f"Не удалось отредактировать сообщение, отправляем новое: {e}")
        try:
            await callback.message.delete()
        except:
            pass
        await callback.message.answer_photo(
            photo=banner_photo,
            caption="Панель администратора Mom\'s Club:",
            reply_markup=keyboard
        )

# Обработчик закрытия админ-панели
@admin_router.callback_query(F.data == "admin_close")
async def process_close(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Закрыть'"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Сбрасываем состояние
    await state.clear()
    
    # Удаляем сообщение
    await callback.message.delete()
    
    # Отправляем ответ на колбэк, чтобы убрать часики
    await callback.answer()

# Обработчик нажатия "Экспорт пользователей"
@admin_router.callback_query(F.data == "admin_export_users")
async def process_export_users(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Запрашиваем тип экспорта
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Все пользователи", callback_data="admin_export:all")],
            [InlineKeyboardButton(text="✅ Только с активными подписками", callback_data="admin_export:active")],
            [InlineKeyboardButton(text="❌ Только с истекшими подписками", callback_data="admin_export:expired")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_stats")]
        ]
    )
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            "Выберите тип экспорта пользователей:",
            reply_markup=keyboard
        )
    except Exception as e:
        # Если не можем удалить, просто отправляем новое сообщение
        logger.error(f"Ошибка при удалении сообщения в процессе экспорта: {e}")
        await callback.message.answer(
            "Выберите тип экспорта пользователей:",
            reply_markup=keyboard
        )
    
    await callback.answer()

# Обработчик типа экспорта
@admin_router.callback_query(F.data.startswith("admin_export:"))
async def process_export_type(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем тип экспорта
    export_type = callback.data.split(":")[1]
    
    # Уведомляем о начале формирования файла
    await callback.answer("Начинаем формирование Excel файла...", show_alert=False)
    
    try:
        # Получаем данные пользователей
        users_data = []
        async with AsyncSessionLocal() as session:
            try:
                if export_type == "all":
                    # Получаем всех пользователей
                    users_data = await get_all_users_with_subscriptions(session)
                    export_title = "Все пользователи"
                
                elif export_type == "active":
                    # Получаем пользователей с активными подписками
                    users_data = await get_users_with_active_subscriptions(session)
                    export_title = "Пользователи с активными подписками"
                
                elif export_type == "expired":
                    # Получаем пользователей с истекшими подписками
                    users_data = await get_users_with_expired_subscriptions(session)
                    export_title = "Пользователи с истекшими подписками"
            except Exception as db_error:
                logging.error(f"Ошибка при получении данных из БД: {db_error}", exc_info=True)
                raise Exception(f"Ошибка запроса к базе данных: {str(db_error)}")
        
        if not users_data:
            # Отправляем новое сообщение, а не редактируем старое
            try:
                # Удаляем текущее сообщение
                await callback.message.delete()
                
                # Отправляем информацию об отсутствии данных
                await callback.message.answer(
                    f"ℹ️ Нет пользователей для экспорта в категории '{export_title}'",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="« Назад к экспорту", callback_data="admin_export_users")],
                            [InlineKeyboardButton(text="« Вернуться к статистике", callback_data="admin_stats")]
                        ]
                    )
                )
            except Exception as e:
                # Если не можем удалить, просто отправляем новое сообщение
                logger.error(f"Ошибка при удалении сообщения: {e}")
                await callback.message.answer(
                    f"ℹ️ Нет пользователей для экспорта в категории '{export_title}'",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="« Назад к экспорту", callback_data="admin_export_users")],
                            [InlineKeyboardButton(text="« Вернуться к статистике", callback_data="admin_stats")]
                        ]
                    )
                )
            return
        
        # Преобразуем данные в формат для pandas
        export_data = []
        async with AsyncSessionLocal() as session: # Создаем сессию для проверки промокодов
            for user, subscription in users_data:
                # Проверяем, использовал ли юзер промокод
                used_promo = await has_user_used_any_promo_code(session, user.id)
                
                user_data = {
                    "ID": user.id,
                    "Telegram ID": user.telegram_id,
                    "Username": user.username or "",
                    "Имя": user.first_name or "",
                    "Фамилия": user.last_name or "",
                    "Использовал промокод": "Да" if used_promo else "Нет", # <-- Новая колонка
                    "Статус": "Активен" if user.is_active else "Неактивен",
                    "Дата регистрации": user.created_at.strftime("%d.%m.%Y %H:%M"),
                    "Подписка": "Есть" if subscription else "Нет"
                }
                
                if subscription:
                    user_data.update({
                        "Начало подписки": subscription.start_date.strftime("%d.%m.%Y"),
                        "Окончание подписки": subscription.end_date.strftime("%d.%m.%Y"),
                        "Активна": "Да" if subscription.is_active else "Нет",
                        "Стоимость": f"{subscription.price} ₽"
                    })
                else:
                    user_data.update({
                        "Начало подписки": "",
                        "Окончание подписки": "",
                        "Активна": "Нет",
                        "Стоимость": ""
                    })
                
                export_data.append(user_data)
        
        # Создаем DataFrame
        df = pd.DataFrame(export_data)
        
        # Определяем путь к файлу
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"export_{export_type}_{timestamp}.xlsx"
        export_path = os.path.join("exports", export_filename)
        
        # Создаем директорию, если её нет
        os.makedirs("exports", exist_ok=True)
        
        # Сохраняем в Excel
        df.to_excel(export_path, index=False, engine="openpyxl")
        
        # Отправляем файл пользователю
        doc = FSInputFile(export_path)
        
        await callback.message.answer_document(
            document=doc,
            caption=f"📊 Экспорт: {export_title}\n📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n👥 Пользователей: {len(export_data)}"
        )
        
        # Возвращаемся к экрану статистики
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад к экспорту", callback_data="admin_export_users")],
                [InlineKeyboardButton(text="« Вернуться к статистике", callback_data="admin_stats")]
            ]
        )
        
        # Отправляем новое сообщение вместо редактирования
        try:
            # Удаляем текущее сообщение
            await callback.message.delete()
            
            # Отправляем сообщение об успешном экспорте
            await callback.message.answer(
                f"✅ Экспорт успешно создан: {export_title}\n"
                f"📁 Файл: {export_filename}\n"
                f"👥 Пользователей: {len(export_data)}",
                reply_markup=keyboard
            )
        except Exception as e:
            # Если не можем удалить, просто отправляем новое сообщение
            logger.error(f"Ошибка при удалении сообщения после экспорта: {e}")
            await callback.message.answer(
                f"✅ Экспорт успешно создан: {export_title}\n"
                f"📁 Файл: {export_filename}\n"
                f"👥 Пользователей: {len(export_data)}",
                reply_markup=keyboard
            )
        
    except Exception as e:
        logging.error(f"Ошибка при экспорте пользователей: {e}", exc_info=True)
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="admin_export_users")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_stats")]
            ]
        )
        
        # Отправляем новое сообщение с ошибкой
        try:
            # Удаляем текущее сообщение
            await callback.message.delete()
            
            # Отправляем сообщение об ошибке
            await callback.message.answer(
                f"❌ Произошла ошибка при экспорте: {str(e)}\n\nПожалуйста, попробуйте позже.",
                reply_markup=keyboard
            )
        except Exception as del_error:
            # Если не можем удалить, просто отправляем новое сообщение
            logger.error(f"Ошибка при удалении сообщения после ошибки экспорта: {del_error}")
            await callback.message.answer(
                f"❌ Произошла ошибка при экспорте: {str(e)}\n\nПожалуйста, попробуйте позже.",
                reply_markup=keyboard
            )

@admin_router.message(Command("test_expire"))
async def cmd_test_expire(message: types.Message, state: FSMContext):
    """Начало процесса симуляции окончания подписки."""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        logger.warning(f"Попытка вызова /test_expire от не-админа ID: {user_id}")
        await message.answer("У вас нет прав доступа к этой команде.")
        return

    logger.info(f"Админ {user_id} вызвал команду /test_expire")
    await state.set_state(AdminStates.waiting_for_test_user_id)
    await message.answer("Введите Telegram ID пользователя для теста:")

@admin_router.message(StateFilter(AdminStates.waiting_for_test_user_id))
async def process_test_user_id(message: types.Message, state: FSMContext):
    """Получает ID пользователя для теста и запрашивает количество минут."""
    if message.from_user.id not in ADMIN_IDS: return # Доп. проверка на админа

    try:
        target_user_id = int(message.text.strip())
        logger.info(f"Админ {message.from_user.id} ввел ID {target_user_id} для теста /test_expire")

        # Проверим, существует ли пользователь в БД
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, target_user_id)
            if not user:
                await message.answer(f"❌ Пользователь с Telegram ID {target_user_id} не найден в базе. Попробуйте снова или отмените.")
                # Не сбрасываем состояние, чтобы можно было ввести другой ID
                return

        await state.update_data(test_target_user_id=target_user_id)
        await state.set_state(AdminStates.waiting_for_test_minutes)
        await message.answer("Через сколько минут должна 'закончиться' подписка? (Введите число)")

    except ValueError:
        await message.answer("❌ Некорректный ID. Пожалуйста, введите числовой Telegram ID.")
    except Exception as e:
        logger.error(f"Ошибка в process_test_user_id для админа {message.from_user.id}: {e}", exc_info=True)
        await message.answer(f"Произошла ошибка: {e}")
        await state.clear() # Сбрасываем состояние при ошибке

@admin_router.message(StateFilter(AdminStates.waiting_for_test_minutes))
async def process_test_minutes(message: types.Message, state: FSMContext):
    """Получает количество минут и изменяет/создает подписку."""
    if message.from_user.id not in ADMIN_IDS: return # Доп. проверка на админа

    try:
        minutes_to_expire = int(message.text.strip())
        if minutes_to_expire <= 0:
            await message.answer("Количество минут должно быть положительным числом. Попробуйте снова.")
            return

        logger.info(f"Админ {message.from_user.id} ввел {minutes_to_expire} минут для теста /test_expire")

        user_data = await state.get_data()
        target_user_id = user_data.get("test_target_user_id")

        if not target_user_id:
            logger.error(f"Не найден test_target_user_id в состоянии для админа {message.from_user.id}")
            await message.answer("Произошла ошибка: не найден ID пользователя в состоянии. Попробуйте начать заново с /test_expire.")
            await state.clear()
            return

        target_end_date = datetime.now() + timedelta(minutes=minutes_to_expire)
        end_date_str = target_end_date.strftime("%d.%m.%Y %H:%M:%S")
        logger.info(f"Целевая дата окончания подписки: {end_date_str} для пользователя {target_user_id}")


        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, target_user_id)
            if not user: # Доп. проверка, вдруг удалили пока админ вводил минуты
                await message.answer(f"❌ Пользователь с Telegram ID {target_user_id} больше не найден. Операция отменена.")
                await state.clear()
                return

            active_sub = await get_active_subscription(session, user.id)

            if active_sub:
                # Обновляем существующую активную подписку
                old_end_date_str = active_sub.end_date.strftime("%d.%m.%Y %H:%M:%S")
                query = (
                    update(Subscription)
                    .where(Subscription.id == active_sub.id)
                    .values(end_date=target_end_date, is_active=True) # Убедимся, что она активна
                )
                await session.execute(query)
                await session.commit()
                logger.info(f"Админ {message.from_user.id}: Обновлена подписка ID {active_sub.id} для пользователя {target_user_id}. Новая дата окончания: {end_date_str} (старая: {old_end_date_str})")
                await message.answer(f"✅ Подписка пользователя {target_user_id} обновлена. Окончание установлено на {end_date_str} (через ~{minutes_to_expire} мин).")

            else:
                # Создаем новую короткую подписку для теста
                new_sub = await create_subscription(
                    session=session,
                    user_id=user.id,
                    end_date=target_end_date,
                    price=0, # Тестовая бесплатная
                    payment_id=f"admin_test_expire_{datetime.now().timestamp()}"
                )
                await session.commit() # Убедимся, что подписка создана
                logger.info(f"Администратор {message.from_user.id} создал тестовую подписку ID {new_sub.id} для пользователя {target_user_id}. Дата окончания: {end_date_str}")
                await message.answer(f"✅ Новая тестовая подписка создана для пользователя {target_user_id}. Окончание установлено на {end_date_str} (через ~{minutes_to_expire} мин).")

        await state.clear() # Завершили

    except ValueError:
        await message.answer("❌ Некорректное число. Пожалуйста, введите количество минут (целое число).")
    except Exception as e:
        logger.error(f"Ошибка в process_test_minutes для админа {message.from_user.id}: {e}", exc_info=True)
        await message.answer(f"Произошла ошибка при установке даты подписки: {e}")
        await state.clear() # Сбрасываем состояние при ошибке

# --- Управление промокодами --- 

# Вспомогательная функция для формирования сообщения со списком промокодов
async def _build_promo_list_message(page: int = 0) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Формирует текст и клавиатуру для списка промокодов на указанной странице."""
    offset = page * PROMO_PAGE_SIZE
    
    async with AsyncSessionLocal() as session:
        promo_codes = await get_all_promo_codes(session, limit=PROMO_PAGE_SIZE, offset=offset)
        total_promos = await get_total_promo_codes_count(session)
        
    total_pages = math.ceil(total_promos / PROMO_PAGE_SIZE) if total_promos > 0 else 1
    current_page_display = page + 1

    keyboard_buttons = []
    text = ""

    if not promo_codes and page == 0:
        text = "🎟️ <b>Список промокодов пуст.</b>"
        keyboard_buttons = [
            [InlineKeyboardButton(text="➕ Добавить промокод", callback_data="admin_add_promo")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
        ]
    elif not promo_codes and page > 0:
        text = f"🎟️ <b>Ошибка:</b> Страница {current_page_display} не найдена."
        keyboard_buttons = [
             [InlineKeyboardButton(text="К началу списка", callback_data="admin_manage_promocodes_page_0")],
             [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
        ]
    else:
        text = f"🎟️ <b>Список промокодов (Стр. {current_page_display}/{total_pages}):</b>\n\n"
        for promo in promo_codes:
            expiry_date = promo.expiry_date.strftime("%d.%m.%Y") if promo.expiry_date else "бессрочный"
            max_uses = promo.max_uses if promo.max_uses is not None else "∞"
            status = "✅ Активен" if promo.is_active else "❌ Неактивен"
            details = f"<code>{promo.code}</code>: {promo.value} дн., исп: {promo.current_uses}/{max_uses}, до: {expiry_date}, {status}"
            text += f"• {details}\n"
            # Кнопки управления
            promo_actions_row = []
            if promo.is_active:
                promo_actions_row.append(InlineKeyboardButton(text="❌ Деактив.", callback_data=f"admin_toggle_promo_{promo.id}"))
            else:
                promo_actions_row.append(InlineKeyboardButton(text="✅ Актив.", callback_data=f"admin_toggle_promo_{promo.id}"))
            promo_actions_row.append(InlineKeyboardButton(text="✏️ Ред.", callback_data=f"admin_edit_promo_{promo.id}"))
            promo_actions_row.append(InlineKeyboardButton(text="🗑️ Удал.", callback_data=f"admin_delete_promo_{promo.id}"))
            keyboard_buttons.append(promo_actions_row)
        
        text += f"\nВсего промокодов: {total_promos}"
        
        # Кнопки пагинации
        pagination_row = []
        if page > 0:
            pagination_row.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"admin_manage_promocodes_page_{page-1}"))
        if total_pages > 1:
             pagination_row.append(InlineKeyboardButton(text=f"- {current_page_display}/{total_pages} -", callback_data="noop"))
        if current_page_display < total_pages:
            pagination_row.append(InlineKeyboardButton(text="➡️ След.", callback_data=f"admin_manage_promocodes_page_{page+1}"))
            
        if pagination_row:
             keyboard_buttons.append(pagination_row)

        # Кнопки "Добавить" и "Назад"
        keyboard_buttons.extend([
            [InlineKeyboardButton(text="➕ Добавить промокод", callback_data="admin_add_promo")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None
    return text, keyboard


# Обработчик кнопки "Управление промокодами" и пагинации
@admin_router.callback_query(F.data.startswith("admin_manage_promocodes")) 
async def admin_manage_promocodes(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    page = 0
    if "_page_" in callback.data:
        try:
            page = int(callback.data.split("_page_")[-1])
        except ValueError:
            page = 0

    await callback.answer(f"Загружаю стр. {page + 1}...")
    
    text, keyboard = await _build_promo_list_message(page)

    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramRetryAfter as e:
        # Если попали на флуд-лимит
        logger.warning(f"Flood control exceeded on initial promo list load (page {page}): {e}. Retrying in {e.retry_after}s.")
        try:
            # Отправляем новое сообщение без удаления
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение после флуд-лимита: {send_error}")
    except Exception as e:
        # Другие ошибки
        logger.error(f"Ошибка при обработке списка промокодов (стр. {page}): {e}")
        try:
            # Пробуем просто отправить новое сообщение без удаления
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение со списком промокодов: {send_error}")

# Обработчик нажатия на кнопку "Удалить промокод" (запрос подтверждения)
@admin_router.callback_query(F.data.startswith("admin_delete_promo_"))
async def admin_delete_promo_confirm(callback: CallbackQuery, state: FSMContext): 
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return

    try:
        promo_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        logger.error(f"Некорректный callback_data для удаления промокода: {callback.data}")
        await callback.answer("Ошибка: Неверный ID промокода.", show_alert=True)
        return

    # Нужен код промокода для сообщения подтверждения, получим его
    async with AsyncSessionLocal() as session:
        from database.models import PromoCode as PromoCodeModel # Явный импорт модели
        query = select(PromoCodeModel).where(PromoCodeModel.id == promo_id)
        result = await session.execute(query)
        promo = result.scalar_one_or_none()
    
    if not promo:
        await callback.answer("Промокод не найден. Возможно, он уже удален.", show_alert=True)
        # Пытаемся обновить список
        try:
            # Перенаправляем на обновление списка
            callback.data = "admin_manage_promocodes_page_0" 
            await admin_manage_promocodes(callback, state)
        except Exception as e:
            logger.error(f"Ошибка при обновлении списка после ненайденного промокода для удаления: {e}")
        return
        
    promo_code_text = promo.code

    text = f"🗑️ Вы уверены, что хотите удалить промокод <code>{promo_code_text}</code>?\n\n⚠️ Это действие необратимо! Также будут удалены записи об использовании этого промокода."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_delete_exec_{promo_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_manage_promocodes")] # Возврат к списку
        ]
    )
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer() # Просто чтобы убрать часики
    except Exception as e:
        logger.error(f"Ошибка при показе подтверждения удаления промокода {promo_id}: {e}")
        try:
            # Отправляем сообщение без удаления в случае ошибки
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение о подтверждении удаления: {send_error}")
            await callback.answer("Произошла ошибка.", show_alert=True)

# Обработчик подтверждения удаления промокода
@admin_router.callback_query(F.data.startswith("admin_delete_exec_"))
async def admin_delete_promo_execute(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return

    try:
        promo_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        logger.error(f"Некорректный callback_data для выполнения удаления: {callback.data}")
        await callback.answer("Ошибка: Неверный ID промокода.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        deleted = await delete_promo_code_by_id(session, promo_id)
    
    if deleted:
        await callback.answer("🗑️ Промокод успешно удален!", show_alert=False)
        logger.info(f"Администратор {callback.from_user.id} удалил промокод ID {promo_id}")
    else:
        await callback.answer("❌ Не удалось удалить промокод. Возможно, он уже был удален.", show_alert=True)
        logger.warning(f"Администратор {callback.from_user.id} пытался удалить промокод ID {promo_id}, но он не найден или произошла ошибка.")

    # Сообщаем результат и предлагаем вернуться к списку
    result_text = f"🗑️ Промокод (ID: {promo_id}) успешно удален!" if deleted else f"❌ Не удалось удалить промокод (ID: {promo_id})."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")
    ]])
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка при показе результата удаления промокода {promo_id}: {e}")
        # Если удаление не удалось, пробуем отправить новое сообщение
        try:
            await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as send_error:
             logger.error(f"Не удалось отправить новое сообщение после ошибки при удалении промокода: {send_error}")

# Обработчик активации/деактивации промокода
@admin_router.callback_query(F.data.startswith("admin_toggle_promo_"))
async def admin_toggle_promo_status(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
        
    try:
        promo_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        logger.error(f"Некорректный callback_data для переключения статуса промокода: {callback.data}")
        await callback.answer("Ошибка: Неверный ID промокода.", show_alert=True)
        return
        
    new_status = None
    async with AsyncSessionLocal() as session:
        # Получаем текущий промокод, чтобы узнать его статус
        promo_query = select(PromoCode).where(PromoCode.id == promo_id)
        promo_result = await session.execute(promo_query)
        current_promo = promo_result.scalar_one_or_none()
        
        if not current_promo:
            await callback.answer("Промокод не найден.", show_alert=True)
            # Перенаправляем на обновление списка
            callback.data = "admin_manage_promocodes_page_0" 
            await admin_manage_promocodes(callback, state)
            return
            
        # Определяем новый статус и обновляем
        new_status = not current_promo.is_active
        updated_promo = await update_promo_code(session, promo_id, is_active=new_status)

    if updated_promo is not None:
        action = "активирован" if new_status else "деактивирован"
        result_text = f"Статус промокода <code>{updated_promo.code}</code> изменен на: <b>{action.upper()}</b>."
        answer_text = f"Промокод {updated_promo.code} {action}."
    else:
        result_text = f"❌ Не удалось изменить статус промокода ID {promo_id}."
        answer_text = "Не удалось изменить статус промокода."

    # Показываем результат и кнопку возврата
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")
    ]])
    try:
        # Сначала отвечаем на колбэк
        await callback.answer(answer_text, show_alert=(updated_promo is None))
        
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка при показе результата toggle промокода {promo_id}: {e}")
        # Если редактирование не удалось, пробуем отправить новое сообщение
        try:
            await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as send_error:
             logger.error(f"Не удалось отправить новое сообщение после ошибки при изменении статуса промокода: {send_error}")

# --- Редактирование промокода --- 

# Шаг 1: Нажатие кнопки "Редактировать"
@admin_router.callback_query(F.data.startswith("admin_edit_promo_"))
async def admin_edit_promo_start(callback: Optional[CallbackQuery], state: FSMContext, message: Optional[types.Message] = None, promo_id: Optional[int] = None):
    # Эта функция теперь может вызываться либо из CallbackQuery, либо из Message
    user = callback.from_user if callback else message.from_user
    target_message = callback.message if callback else message
    
    if user.id not in ADMIN_IDS:
        if callback: await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return

    # Получаем ID промокода либо из callback.data, либо из переданного аргумента
    if callback and not promo_id:
        try:
            promo_id = int(callback.data.split("_")[-1])
        except (IndexError, ValueError):
            logger.error(f"Некорректный callback_data для редактирования промокода: {callback.data}")
            if callback: await callback.answer("Ошибка: Неверный ID промокода.", show_alert=True)
            return
    elif not promo_id: # Если не передан ни callback, ни promo_id
        logger.error("admin_edit_promo_start вызван без ID промокода")
        if callback: await callback.answer("Ошибка: ID промокода не найден.", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        query = select(PromoCode).where(PromoCode.id == promo_id)
        result = await session.execute(query)
        promo = result.scalar_one_or_none()
    
    if not promo:
        await callback.answer("Промокод не найден. Возможно, он уже удален.", show_alert=True)
        # Обновляем список
        callback.data = "admin_manage_promocodes_page_0" # Возврат на первую страницу
        await admin_manage_promocodes(callback, state)
        return
        
    # Сохраняем ID в состоянии для следующих шагов
    await state.set_state(AdminStates.editing_promo) # Устанавливаем состояние просмотра/редактирования
    await state.update_data(editing_promo_id=promo_id)
    
    # Формируем текст с текущими данными
    expiry_date_str = promo.expiry_date.strftime("%d.%m.%Y") if promo.expiry_date else "Бессрочный"
    max_uses_str = str(promo.max_uses) if promo.max_uses is not None else "Безлимитно"
    status_str = "✅ Активен" if promo.is_active else "❌ Неактивен"
    
    text = (
        f"✏️ <b>Редактирование промокода:</b> <code>{promo.code}</code>\n\n"
        f"🔢 Бонусные дни: {promo.value} (нельзя изменить)\n"
        f"♾️ Лимит использований: {max_uses_str}\n"
        f"🗓️ Действует до: {expiry_date_str}\n"
        f"⚙️ Статус: {status_str}\n\n"
        f"Что вы хотите изменить?"
    )
    
    # Кнопки редактирования
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾️ Изменить лимит", callback_data="edit_promo_set_max_uses")],
        [InlineKeyboardButton(text="🗓️ Изменить дату окончания", callback_data="edit_promo_set_expiry")],
        [InlineKeyboardButton(text="« Назад к списку", callback_data="admin_manage_promocodes_page_0")]
    ])
    
    try:
        if callback:
            # Удаляем текущее сообщение
            await callback.message.delete()
            
            # Отправляем новое сообщение
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()
        else:
            # Если функция вызвана с message, просто отправляем новое сообщение
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка при отображении данных для редактирования промокода {promo_id}: {e}")
        # Пробуем отправить сообщение без удаления старого
        if callback:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer("Произошла ошибка при удалении сообщения.", show_alert=True)
        else:
            await message.answer(f"Ошибка: {e}", parse_mode="HTML")

# Шаг 2.1: Нажатие "Изменить лимит"
@admin_router.callback_query(F.data == "edit_promo_set_max_uses", StateFilter(AdminStates.editing_promo))
async def edit_promo_ask_max_uses(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.editing_promo_max_uses)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="edit_promo_cancel_field")
    ]])
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            "♾️ Введите новый максимальный лимит использований \\(целое число, `0` или `нет` \\- безлимит\\):",
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при запросе лимита использований промокода: {e}")
        try:
            # Пробуем отправить без удаления
            await callback.message.answer(
                "♾️ Введите новый максимальный лимит использований \\(целое число, `0` или `нет` \\- безлимит\\):",
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            await callback.answer()
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение о вводе лимита: {send_error}")
    
# Шаг 3.1: Получение нового лимита
@admin_router.message(StateFilter(AdminStates.editing_promo_max_uses))
async def edit_promo_process_max_uses(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    max_uses_input = message.text.strip().lower()
    new_max_uses = None
    
    if max_uses_input in ['0', 'нет', 'no', 'none', 'null']:
        new_max_uses = None # Безлимит
    else:
        try:
            new_max_uses = int(max_uses_input)
            if new_max_uses < 0:
                await message.answer("❌ Количество использований не может быть отрицательным. Введите 0 или больше, или 'нет' для безлимита.")
                return
        except ValueError:
            await message.answer("❌ Некорректный ввод. Введите целое число или 'нет'.")
            return
            
    user_data = await state.get_data()
    promo_id = user_data.get('editing_promo_id')
    if not promo_id:
        await message.answer("❌ Ошибка: Не найден ID промокода для обновления.")
        await state.clear()
        return
        
    # Обновляем в базе
    async with AsyncSessionLocal() as session:
        updated_promo = await update_promo_code(session, promo_id, max_uses=new_max_uses)
        
    if updated_promo:
        await message.answer(f"✅ Лимит использований для промокода `{updated_promo.code}` обновлен.")
        # Отправляем новое сообщение с кнопкой возврата в редактор
        await state.clear() # Выходим из состояния ввода лимита
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
             InlineKeyboardButton(text="✏️ Вернуться к редактированию", callback_data=f"admin_edit_promo_{promo_id}")
        ]])
        await message.answer("Вы можете изменить другие параметры или вернуться к списку.", reply_markup=keyboard)
    else:
        await message.answer("❌ Не удалось обновить лимит промокода.")
        await state.set_state(AdminStates.editing_promo) # Возвращаем состояние просмотра
    
# Шаг 2.2: Нажатие "Изменить дату окончания"
@admin_router.callback_query(F.data == "edit_promo_set_expiry", StateFilter(AdminStates.editing_promo))
async def edit_promo_ask_expiry_date(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.editing_promo_expiry_date)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="edit_promo_cancel_field")
    ]])
    current_date_example = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            # Исправляем экранирование в этой строке (двойные слэши)
            f"🗓️ Введите новую дату истечения срока действия в формате `ДД\\.ММ\\.ГГГГ` \\(например, `{current_date_example}`\\) "
            f"или напишите `нет`, чтобы сделать промокод бессрочным:",
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при запросе даты окончания промокода: {e}")
        try:
            # Пробуем отправить без удаления
            await callback.message.answer(
                f"🗓️ Введите новую дату истечения срока действия в формате `ДД\\.ММ\\.ГГГГ` \\(например, `{current_date_example}`\\) "
                f"или напишите `нет`, чтобы сделать промокод бессрочным:",
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            await callback.answer()
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение о вводе даты: {send_error}")

# Шаг 3.2: Получение новой даты
@admin_router.message(StateFilter(AdminStates.editing_promo_expiry_date))
async def edit_promo_process_expiry_date(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    expiry_date_input = message.text.strip().lower()
    new_expiry_date = None
    
    if expiry_date_input not in ['нет', 'no', 'none', 'null']:
        try:
            new_expiry_date = datetime.strptime(expiry_date_input, "%d.%m.%Y")
            new_expiry_date = new_expiry_date.replace(hour=23, minute=59, second=59)
            if new_expiry_date < datetime.now():
                 await message.answer("❌ Дата истечения не может быть в прошлом. Попробуйте еще раз:")
                 return
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введите дату как `ДД.ММ.ГГГГ` или 'нет'.")
            return
            
    user_data = await state.get_data()
    promo_id = user_data.get('editing_promo_id')
    if not promo_id:
        await message.answer("❌ Ошибка: Не найден ID промокода для обновления.")
        await state.clear()
        return
        
    # Обновляем в базе
    async with AsyncSessionLocal() as session:
        updated_promo = await update_promo_code(session, promo_id, expiry_date=new_expiry_date)
        
    if updated_promo:
        await message.answer(f"✅ Дата окончания для промокода `{updated_promo.code}` обновлена.")
        # Отправляем новое сообщение с кнопкой возврата в редактор
        await state.clear() # Выходим из состояния ввода даты
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
             InlineKeyboardButton(text="✏️ Вернуться к редактированию", callback_data=f"admin_edit_promo_{promo_id}")
        ]])
        await message.answer("Вы можете изменить другие параметры или вернуться к списку.", reply_markup=keyboard)
    else:
        await message.answer("❌ Не удалось обновить дату промокода.")
        await state.set_state(AdminStates.editing_promo) # Возвращаем состояние просмотра

# Отмена редактирования поля
@admin_router.callback_query(F.data == "edit_promo_cancel_field", StateFilter(AdminStates.editing_promo_max_uses, AdminStates.editing_promo_expiry_date))
async def edit_promo_cancel_field(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    
    user_data = await state.get_data()
    promo_id = user_data.get('editing_promo_id')
    if not promo_id:
         await callback.answer("Ошибка: Не найден ID промокода.", show_alert=True)
         await state.clear()
         # Возврат к списку
         callback.data = "admin_manage_promocodes_page_0"
         await admin_manage_promocodes(callback, state)
         return
         
    await callback.answer("Изменение отменено.")
    
    # Вызываем функцию редактирования с текущим ID
    # Удаляем строку с изменением callback.data и передаем promo_id напрямую
    await admin_edit_promo_start(callback, state, promo_id=promo_id)


# --- Конец Редактирования промокода --- 


# --- Добавление промокода --- 

# Шаг 1: Нажатие кнопки "Добавить промокод"
@admin_router.callback_query(F.data == "admin_add_promo")
async def admin_add_promo_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_promo_code_text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel") # Кнопка отмены добавления
    ]])
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            "🆕 Введите текст нового промокода (3-50 символов, только буквы и цифры):",
            reply_markup=keyboard
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при запросе текста промокода: {e}")
        try:
            # Пробуем отправить без удаления
            await callback.message.answer(
                "🆕 Введите текст нового промокода (3-50 символов, только буквы и цифры):",
                reply_markup=keyboard
            )
            await callback.answer()
        except Exception as send_error:
            logger.error(f"Не удалось отправить сообщение о вводе текста промокода: {send_error}")
            await callback.answer("Произошла ошибка при обработке запроса.", show_alert=True)

# Обработчик отмены добавления/редактирования промокода
@admin_router.callback_query(F.data == "admin_promo_cancel", StateFilter(
    AdminStates.waiting_for_promo_code_text,
    AdminStates.waiting_for_promo_value,
    AdminStates.waiting_for_promo_max_uses,
    AdminStates.waiting_for_promo_expiry_date
))
async def admin_promo_cancel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return

    await state.clear()
    await callback.answer("Действие отменено.")
    
    # Возвращаемся к списку промокодов (первая страница)
    # Вызываем хендлер списка с правильным callback
    callback.data = "admin_manage_promocodes_page_0"
    await admin_manage_promocodes(callback, state)

# Шаг 2: Получение текста промокода
@admin_router.message(StateFilter(AdminStates.waiting_for_promo_code_text))
async def admin_promo_code_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    promo_code_text = message.text.strip().upper()
    if not promo_code_text or len(promo_code_text) < 3 or len(promo_code_text) > 50:
        await message.answer("❌ Некорректный код. Длина должна быть от 3 до 50 символов. Попробуйте еще раз:")
        return

    # Проверка на уникальность (опционально, но желательно)
    async with AsyncSessionLocal() as session:
        existing = await get_promo_code_by_code(session, promo_code_text)
        if existing:
            await message.answer(f"❌ Промокод `{promo_code_text}` уже существует. Придумайте другой:")
            return

    await state.update_data(promo_code_text=promo_code_text)
    await state.set_state(AdminStates.waiting_for_promo_value)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")
    ]])
    # ИСПРАВЛЕНО ЗДЕСЬ: одинарный \n
    await message.answer(
        f"✅ Код: `{promo_code_text}`\n🔢 Теперь введите количество бонусных дней \\(целое число, например, `7`\\):",
        reply_markup=keyboard,
        parse_mode="MarkdownV2"
    )

# Шаг 3: Получение количества дней
@admin_router.message(StateFilter(AdminStates.waiting_for_promo_value))
async def admin_promo_value_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    try:
        days = int(message.text.strip())
        if days <= 0:
            await message.answer("❌ Количество дней должно быть положительным числом. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое число.")
        return

    await state.update_data(promo_value=days)
    await state.set_state(AdminStates.waiting_for_promo_max_uses)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")
    ]])
    await message.answer(
        f"✅ Дней: `{days}`\n♾️ Теперь введите максимальное количество использований "
        f"\\(целое число, `0` или `нет` \\- безлимит\\):",
        reply_markup=keyboard,
        parse_mode="MarkdownV2"
    )

# Шаг 4: Получение максимального количества использований
@admin_router.message(StateFilter(AdminStates.waiting_for_promo_max_uses))
async def admin_promo_max_uses_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    max_uses_input = message.text.strip().lower()
    max_uses = None

    if max_uses_input not in ['0', 'нет', 'no', 'none', 'null']:
        try:
            max_uses = int(max_uses_input)
            if max_uses < 0:
                await message.answer("❌ Количество использований не может быть отрицательным. Введите 0 или больше, или 'нет' для безлимита.")
                return
        except ValueError:
            await message.answer("❌ Некорректный ввод. Введите целое число или 'нет'.")
            return
    
    await state.update_data(promo_max_uses=max_uses)
    await state.set_state(AdminStates.waiting_for_promo_expiry_date)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")
    ]])
    current_date_example = (datetime.now() + timedelta(days=30)).strftime("%d\\.%m\\.%Y") # Экранируем точки для MarkdownV2
    await message.answer(
        f"✅ Лимит: `{max_uses if max_uses is not None else '∞'}`\n" 
        f"🗓️ Теперь введите дату истечения срока действия в формате `ДД\\.ММ\\.ГГГГ` "
        f"\\(например, `{current_date_example}`\\) или напишите `нет`, чтобы сделать промокод бессрочным:",
        reply_markup=keyboard,
        parse_mode="MarkdownV2"
    )

# Шаг 5: Получение даты истечения и создание промокода
@admin_router.message(StateFilter(AdminStates.waiting_for_promo_expiry_date))
async def admin_promo_expiry_date_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return

    expiry_date_input = message.text.strip().lower()
    expiry_date = None

    if expiry_date_input not in ['нет', 'no', 'none', 'null']:
        try:
            # Убираем экранирование точек при парсинге
            expiry_date = datetime.strptime(expiry_date_input, "%d.%m.%Y")
            expiry_date = expiry_date.replace(hour=23, minute=59, second=59)
            if expiry_date < datetime.now():
                 await message.answer("❌ Дата истечения не может быть в прошлом. Попробуйте еще раз:")
                 return
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введите дату как `ДД.ММ.ГГГГ` или 'нет'.")
            return
            
    # Получаем все данные из состояния
    user_data = await state.get_data()
    promo_code_text = user_data.get('promo_code_text')
    promo_value = user_data.get('promo_value')
    promo_max_uses = user_data.get('promo_max_uses')

    if not promo_code_text or promo_value is None: # promo_max_uses может быть None
        await message.answer("❌ Ошибка: Не удалось получить все данные для создания промокода. Попробуйте снова.")
        await state.clear()
        # Можно перенаправить на начало добавления или главное меню
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")
        ]])
        await message.answer("Возврат к списку промокодов.", reply_markup=keyboard)
        return

    # Создаем промокод в базе данных
    try:
        # Возвращаем создание сессии
        async with AsyncSessionLocal() as session:
            new_promo = await create_promo_code(
                db=session, # <-- Передаем сессию как аргумент 'db'
                code=promo_code_text,
                value=promo_value,
                max_uses=promo_max_uses,
                expiry_date=expiry_date,
                is_active=True, # По умолчанию активен
                discount_type='days' # Указываем тип скидки
            )
        
        if new_promo:
            expiry_date_str = expiry_date.strftime("%d.%m.%Y") if expiry_date else "бессрочный"
            max_uses_str = str(promo_max_uses) if promo_max_uses is not None else "∞"
            # ИСПРАВЛЕНО ЗДЕСЬ: одинарные \n
            await message.answer(
                f"✅ Промокод `{new_promo.code}` успешно создан!\n\n"
                f"🎁 Бонус: {new_promo.value} дн.\n"
                f"♾️ Лимит: {max_uses_str}\n"
                f"🗓️ До: {expiry_date_str}"
            )
            logger.info(f"Администратор {message.from_user.id} создал промокод: {new_promo.code}")
        else:
            await message.answer("❌ Не удалось создать промокод в базе данных.")

    except Exception as e:
        logger.error(f"Ошибка при создании промокода {promo_code_text} админом {message.from_user.id}: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при создании промокода: {e}")

    finally:
        # Очищаем состояние в любом случае
        await state.clear()
        # Предлагаем вернуться к списку
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")
        ]])
        await message.answer("Процесс добавления завершен.", reply_markup=keyboard)

# Функция для регистрации всех обработчиков админки
def register_admin_handlers(dp):
    dp.include_router(admin_router)
    logger.info("Административные обработчики зарегистрированы") 

# --- Управление рассылками ---

# Обработчик кнопки "Рассылка сообщений"
@admin_router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Устанавливаем формат HTML
    await state.update_data(broadcast_format="HTML")
    await state.set_state(AdminStates.broadcast_text)
    
    # Примеры форматирования
    format_example = """/текст/ - жирный текст
&текст& - курсив
_текст_ - подчеркнутый
~текст~ - зачеркнутый
№текст№ - моноширинный
»текст« - цитата
```
многострочный код
```"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
        
        # Отправляем новое сообщение
        await callback.message.answer(
            f"📝 <b>Введите текст рассылки</b>\n\n"
            f"<b>Формат:</b> Упрощенное форматирование\n\n"
            f"<b>Используйте эти символы для форматирования:</b>\n"
            f"<code>{format_example}</code>\n\n"
            f"💡 <b>Совет:</b> Система автоматически преобразует ваши символы в HTML-форматирование.\n"
            f"Вам не нужно беспокоиться о специальных символах HTML.\n\n"
            f"Отправьте текст для рассылки:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        # Если не можем удалить, просто отправляем новое сообщение
        logger.error(f"Ошибка при удалении сообщения в процессе запуска рассылки: {e}")
        await callback.message.answer(
            f"📝 <b>Введите текст рассылки</b>\n\n"
            f"<b>Формат:</b> Упрощенное форматирование\n\n"
            f"<b>Используйте эти символы для форматирования:</b>\n"
            f"<code>{format_example}</code>\n\n"
            f"💡 <b>Совет:</b> Система автоматически преобразует ваши символы в HTML-форматирование.\n"
            f"Вам не нужно беспокоиться о специальных символах HTML.\n\n"
            f"Отправьте текст для рассылки:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    await callback.answer()

# Функция для преобразования пользовательского синтаксиса в HTML
def convert_custom_to_html(text):
    import re
    
    logger.info(f"Начало преобразования текста длиной {len(text)} символов в HTML")
    
    try:
        # Экранируем основные HTML-теги, чтобы они не воспринимались как разметка
        text = text.replace("<", "&lt;").replace(">", "&gt;")
        logger.info("HTML-теги экранированы")
        
        # Заменяем пользовательские форматы на HTML
        
        # /текст/ -> <b>текст</b> (жирный)
        pattern = r'/([^/]+)/'
        text = re.sub(pattern, r'<b>\1</b>', text)
        logger.info("Обработан жирный текст")
        
        # &текст& -> <i>текст</i> (курсив)
        pattern = r'&([^&]+)&'
        text = re.sub(pattern, r'<i>\1</i>', text)
        logger.info("Обработан курсив")
        
        # _текст_ -> <u>текст</u> (подчеркнутый)
        pattern = r'_([^_]+)_'
        text = re.sub(pattern, r'<u>\1</u>', text)
        logger.info("Обработан подчеркнутый текст")
        
        # ~текст~ -> <s>текст</s> (зачеркнутый)
        pattern = r'~([^~]+)~'
        text = re.sub(pattern, r'<s>\1</s>', text)
        logger.info("Обработан зачеркнутый текст")
        
        # №текст№ -> <code>текст</code> (моноширинный)
        pattern = r'№([^№]+)№'
        text = re.sub(pattern, r'<code>\1</code>', text)
        logger.info("Обработан моноширинный текст")
        
        # »текст« -> <blockquote>текст</blockquote> (цитата)
        pattern = r'»([^«]+)«'
        text = re.sub(pattern, r'<blockquote>\1</blockquote>', text)
        logger.info("Обработаны цитаты")
        
        # Для блоков кода ``` -> <pre>код</pre>
        pattern = r'```(.*?)```'
        text = re.sub(pattern, r'<pre>\1</pre>', text, 0, re.DOTALL)
        logger.info("Обработаны блоки кода")
        
        # Проверка на ограничения длины сообщения Telegram
        if len(text) > 4096:
            logger.warning(f"Текст превышает лимит Telegram (длина: {len(text)})")
            text = text[:4090] + "..."
        
        logger.info("Преобразование HTML завершено успешно")
        return text
    
    except Exception as e:
        logger.error(f"Ошибка при преобразовании текста в HTML: {e}", exc_info=True)
        # Возвращаем исходный текст с экранированными HTML-тегами
        safe_text = text.replace("<", "&lt;").replace(">", "&gt;")
        return f"<b>Ошибка форматирования</b>: {safe_text}"

# Обработчик ввода текста рассылки
@admin_router.message(StateFilter(AdminStates.broadcast_text))
async def admin_broadcast_text_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    logger.info(f"Получен текст для рассылки от администратора {message.from_user.id}")
    
    try:
        # Преобразуем пользовательский синтаксис в HTML
        original_text = message.text
        logger.info("Начинаю преобразование пользовательского синтаксиса в HTML")
        converted_text = convert_custom_to_html(original_text)
        logger.info(f"Преобразование завершено успешно, длина результата: {len(converted_text)}")
        
        # Сохраняем преобразованный текст и формат HTML
        await state.update_data(broadcast_text=converted_text, broadcast_format="HTML")
        logger.info("Данные сохранены в состоянии")
        
        # Клавиатура для выбора медиа
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="📷 Изображение", callback_data="admin_broadcast_add_photo"),
                    InlineKeyboardButton(text="🎥 Видео", callback_data="admin_broadcast_add_video")
                ],
                [
                    InlineKeyboardButton(text="⭕ Видео-кружок", callback_data="admin_broadcast_add_videocircle"),
                    InlineKeyboardButton(text="📄 Только текст", callback_data="admin_broadcast_text_only")
                ],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_text")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        )
        
        # Отображаем предпросмотр текста в формате HTML
        try:
            logger.info("Отправляю предпросмотр сообщения")
            # Отправляем предпросмотр текста
            preview_message = await message.answer(
                "⏳ Генерирую предпросмотр сообщения..."
            )
            
            logger.info("Отправляю предпросмотр отформатированного текста")
            try:
                # Отправляем предпросмотр отформатированного текста
                await preview_message.edit_text(
                    converted_text,
                    parse_mode="HTML"
                )
                logger.info("Предпросмотр отформатированного текста успешно отправлен")
            except Exception as edit_error:
                logger.error(f"Ошибка при редактировании предпросмотра: {edit_error}", exc_info=True)
                
                # При ошибке показываем текст без форматирования
                safe_text = original_text.replace("<", "&lt;").replace(">", "&gt;")
                await preview_message.edit_text(
                    f"⚠️ Ошибка при форматировании текста: {str(edit_error)}\n\n"
                    f"Исходный текст (без форматирования):\n{safe_text[:3000]}",
                    parse_mode="HTML"
                )
                raise edit_error
            
            logger.info("Отправляю сообщение о выборе медиа")
            # Отправляем сообщение о выборе медиа
            await message.answer(
                "👍 Текст сохранен. Теперь выберите тип медиа-вложения или отправьте только текст:",
                reply_markup=keyboard
            )
            logger.info("Сообщение о выборе медиа успешно отправлено")
            
            logger.info("Устанавливаю состояние broadcast_media")
            # Переходим к следующему шагу
            await state.set_state(AdminStates.broadcast_media)
            logger.info("Состояние broadcast_media установлено успешно")
        
        except Exception as preview_error:
            logger.error(f"Ошибка при отправке предпросмотра: {preview_error}", exc_info=True)
            # Обработка ошибок форматирования
            error_msg = f"❌ Ошибка форматирования: {str(preview_error)}\n\n"
            error_msg += "Пожалуйста, проверьте синтаксис и попробуйте снова.\n\n"
            error_msg += "Используйте наш простой синтаксис форматирования:\n"
            error_msg += "/текст/ - для жирного текста\n"
            error_msg += "&текст& - для курсива\n"
            error_msg += "_текст_ - для подчеркнутого\n"
            error_msg += "~текст~ - для зачеркнутого\n"
            error_msg += "№текст№ - для моноширинного\n"
            error_msg += "»текст« - для цитаты\n"
            
            await message.answer(error_msg)
            
    except Exception as e:
        logger.error(f"Общая ошибка в admin_broadcast_text_received: {e}", exc_info=True)
        await message.answer(
            f"❌ Произошла непредвиденная ошибка: {str(e)}\n\nПожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )

# Обработчик кнопки "Назад к тексту"
@admin_router.callback_query(F.data == "admin_broadcast_back_to_text")
async def admin_broadcast_back_to_text(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Возвращаемся к редактированию текста
    await state.set_state(AdminStates.broadcast_text)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    # Примеры форматирования
    format_example = """/текст/ - жирный текст
&текст& - курсив
_текст_ - подчеркнутый
~текст~ - зачеркнутый
№текст№ - моноширинный
»текст« - цитата
```
многострочный код
```"""
    
    await callback.message.edit_text(
        f"📝 <b>Введите текст рассылки</b>\n\n"
        f"<b>Формат:</b> Упрощенное форматирование\n\n"
        f"<b>Используйте эти символы для форматирования:</b>\n"
        f"<code>{format_example}</code>\n\n"
        f"💡 <b>Совет:</b> Система автоматически преобразует ваши символы в корректный формат.\n"
        f"Вам не нужно беспокоиться о специальных символах HTML.\n\n"
        f"Отправьте текст для рассылки:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# Обработчики добавления медиа
@admin_router.callback_query(F.data == "admin_broadcast_add_photo")
async def admin_broadcast_add_photo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.update_data(broadcast_media_type="photo")
    
    await callback.message.edit_text(
        "📷 <b>Отправьте изображение</b> для рассылки.\n\n"
        "Отправьте изображение как фото (не как файл).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_media")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        )
    )
    await callback.answer()

@admin_router.callback_query(F.data == "admin_broadcast_add_video")
async def admin_broadcast_add_video(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.update_data(broadcast_media_type="video")
    
    await callback.message.edit_text(
        "🎥 <b>Отправьте видео</b> для рассылки.\n\n"
        "Отправьте видео (не как файл).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_media")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        )
    )
    await callback.answer()

@admin_router.callback_query(F.data == "admin_broadcast_add_videocircle")
async def admin_broadcast_add_videocircle(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.update_data(broadcast_media_type="videocircle")
    
    await callback.message.edit_text(
        "⭕ <b>Отправьте видео для видео-сообщения</b> (кружок).\n\n"
        "Требования к видео-кружку:\n"
        "• Квадратное видео (1:1)\n"
        "• Длительность до 60 секунд\n"
        "• Размер до 8 МБ",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_media")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ]
        )
    )
    await callback.answer()

@admin_router.callback_query(F.data == "admin_broadcast_back_to_media")
async def admin_broadcast_back_to_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Возвращаемся к выбору медиа
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📷 Изображение", callback_data="admin_broadcast_add_photo"),
                InlineKeyboardButton(text="🎥 Видео", callback_data="admin_broadcast_add_video")
            ],
            [
                InlineKeyboardButton(text="⭕ Видео-кружок", callback_data="admin_broadcast_add_videocircle"),
                InlineKeyboardButton(text="📄 Только текст", callback_data="admin_broadcast_text_only")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_text")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
        ]
    )
    
    await callback.message.edit_text(
        "Выберите тип медиа-вложения или отправьте только текст:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()

# Обработчик для получения медиа-файлов
@admin_router.message(
    StateFilter(AdminStates.broadcast_media),
    F.photo | F.video | F.video_note | F.document
)
async def admin_broadcast_media_received(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Получаем данные из состояния
    user_data = await state.get_data()
    media_type = user_data.get("broadcast_media_type")
    
    file_id = None
    received_type = None
    
    # Проверяем тип полученного медиа
    if message.photo:
        received_type = "photo"
        file_id = message.photo[-1].file_id  # Берем самое большое фото
    elif message.video:
        received_type = "video"
        file_id = message.video.file_id
    elif message.video_note:
        received_type = "videocircle"
        file_id = message.video_note.file_id
    elif message.document:
        # Документы не поддерживаются в этой реализации
        await message.answer(
            "❌ Пожалуйста, отправьте медиа как фото, видео или видео-сообщение (не как файл)."
        )
        return
    
    # Проверяем, соответствует ли тип полученного медиа выбранному типу
    if media_type and received_type != media_type:
        type_mapping = {
            "photo": "изображение (фото)",
            "video": "видео",
            "videocircle": "видео-сообщение (кружок)"
        }
        await message.answer(
            f"❌ Вы выбрали тип '{type_mapping.get(media_type)}', "
            f"но отправили '{type_mapping.get(received_type)}'.\n\n"
            f"Пожалуйста, отправьте {type_mapping.get(media_type)}."
        )
        return
    
    # Сохраняем file_id и тип медиа
    await state.update_data(broadcast_media_file_id=file_id, broadcast_media_type=received_type)
    
    # Переходим к подтверждению
    await show_broadcast_preview(message, state)

# Обработчик для рассылки без медиа
@admin_router.callback_query(F.data == "admin_broadcast_text_only")
async def admin_broadcast_text_only(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Устанавливаем флаг, что рассылка без медиа
    await state.update_data(broadcast_media_type=None, broadcast_media_file_id=None)
    
    # Отвечаем на колбэк
    await callback.answer()
    
    # Показываем предпросмотр и подтверждение
    await show_broadcast_preview(callback.message, state)

# Функция для отображения предпросмотра и запроса подтверждения
async def show_broadcast_preview(message: types.Message, state: FSMContext):
    # Получаем данные рассылки
    user_data = await state.get_data()
    broadcast_text = user_data.get("broadcast_text", "")
    broadcast_format = user_data.get("broadcast_format", "HTML")  # По умолчанию HTML
    media_type = user_data.get("broadcast_media_type")
    file_id = user_data.get("broadcast_media_file_id")
    
    # Устанавливаем состояние подтверждения
    await state.set_state(AdminStates.broadcast_confirm)
    
    # Отображаем предпросмотр
    preview_message = await message.answer("⏳ Подготовка предпросмотра...")
    
    try:
        # Отправляем предпросмотр в зависимости от типа медиа
        if media_type == "photo" and file_id:
            await message.bot.send_photo(
                chat_id=message.chat.id,
                photo=file_id,
                caption=broadcast_text,
                parse_mode=broadcast_format
            )
        elif media_type == "video" and file_id:
            await message.bot.send_video(
                chat_id=message.chat.id,
                video=file_id,
                caption=broadcast_text,
                parse_mode=broadcast_format
            )
        elif media_type == "videocircle" and file_id:
            # Для видео-кружка текст отправляем отдельно
            await message.bot.send_video_note(
                chat_id=message.chat.id,
                video_note=file_id
            )
            if broadcast_text:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text=broadcast_text,
                    parse_mode=broadcast_format
                )
        else:
            # Только текст
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=broadcast_text,
                parse_mode=broadcast_format
            )
        
        # Удаляем сообщение о подготовке предпросмотра
        await preview_message.delete()
        
        # Клавиатура для подтверждения
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data="admin_broadcast_confirm"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")
                ],
                [
                    InlineKeyboardButton(text="🔄 Изменить текст", callback_data="admin_broadcast_back_to_text"),
                    InlineKeyboardButton(text="📎 Изменить медиа", callback_data="admin_broadcast_back_to_media")
                ]
            ]
        )
        
        # Запрашиваем подтверждение на отправку
        async with AsyncSessionLocal() as session:
            total_users = await get_total_users_count(session)
            active_subs = await get_active_subscriptions_count(session)
        
        await message.answer(
            f"📣 <b>Предпросмотр рассылки</b>\n\n"
            f"<b>Тип:</b> {'Только текст' if not media_type else f'{media_type} + текст'}\n"
            f"<b>Формат:</b> {broadcast_format}\n"
            f"<b>Целевая аудитория:</b> {'Все пользователи' if media_type != 'videocircle' else 'Пользователи с активными подписками'}\n\n"
            f"<b>Получатели:</b> {total_users if media_type != 'videocircle' else active_subs} пользователей\n\n"
            f"Подтвердите отправку рассылки:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    except Exception as e:
        # Обработка ошибок при отправке предпросмотра
        logger.error(f"Ошибка при создании предпросмотра: {e}")
        await preview_message.edit_text(
            f"❌ <b>Ошибка:</b> {str(e)}\n\n"
            f"Возможно, проблема с форматированием текста или медиа-файлом. "
            f"Пожалуйста, вернитесь назад и измените сообщение.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🔄 Изменить текст", callback_data="admin_broadcast_back_to_text"),
                        InlineKeyboardButton(text="📎 Изменить медиа", callback_data="admin_broadcast_back_to_media")
                    ],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
                ]
            ),
            parse_mode="HTML"
        )

# Обработчик подтверждения отправки рассылки
@admin_router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_broadcast_confirm_send(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Отвечаем на колбэк
    await callback.answer("🚀 Начинаем рассылку...", show_alert=False)
    
    # Обновляем сообщение, чтобы показать статус
    status_message = await callback.message.edit_text(
        "⏳ <b>Рассылка запущена</b>\n\n"
        "Начинаем отправку сообщений...\n"
        "Статус: 0% (0/0)\n\n"
        "Это может занять некоторое время. Пожалуйста, дождитесь завершения.",
        parse_mode="HTML"
    )
    
    # Получаем данные рассылки
    user_data = await state.get_data()
    broadcast_text = user_data.get("broadcast_text", "")
    broadcast_format = user_data.get("broadcast_format", "HTML")  # Используем HTML
    media_type = user_data.get("broadcast_media_type")
    file_id = user_data.get("broadcast_media_file_id")
    
    # Массивы для хранения результатов
    successful = []
    failed = []
    
    # Получаем список всех пользователей
    async with AsyncSessionLocal() as session:
        if media_type == "videocircle":
            # Для видео-кружков отправляем только пользователям с активной подпиской
            users_data = await get_users_with_active_subscriptions(session)
            users = [user for user, _ in users_data]
        else:
            # Для остальных типов отправляем всем пользователям
            query = select(User)
            result = await session.execute(query)
            users = result.scalars().all()
    
    total_users = len(users)
    
    # Отправляем сообщения
    for i, user in enumerate(users):
        try:
            # Пропускаем пользователей без Telegram ID
            if not user.telegram_id:
                continue
            
            # Отправляем сообщение в зависимости от типа медиа
            if media_type == "photo" and file_id:
                await callback.bot.send_photo(
                    chat_id=user.telegram_id,
                    photo=file_id,
                    caption=broadcast_text,
                    parse_mode=broadcast_format
                )
            elif media_type == "video" and file_id:
                await callback.bot.send_video(
                    chat_id=user.telegram_id,
                    video=file_id,
                    caption=broadcast_text,
                    parse_mode=broadcast_format
                )
            elif media_type == "videocircle" and file_id:
                # Для видео-кружка текст отправляем отдельно
                await callback.bot.send_video_note(
                    chat_id=user.telegram_id,
                    video_note=file_id
                )
                if broadcast_text:
                    await callback.bot.send_message(
                        chat_id=user.telegram_id,
                        text=broadcast_text,
                        parse_mode=broadcast_format
                    )
            else:
                # Только текст
                await callback.bot.send_message(
                    chat_id=user.telegram_id,
                    text=broadcast_text,
                    parse_mode=broadcast_format
                )
            
            # Добавляем в успешные
            successful.append(user.telegram_id)
            
        except Exception as e:
            # Логируем ошибку и добавляем в неудачные
            logger.error(f"Ошибка при отправке сообщения пользователю {user.telegram_id}: {e}")
            failed.append((user.telegram_id, str(e)))
        
        # Обновляем статус каждые 10 пользователей или в конце
        if (i + 1) % 10 == 0 or i == total_users - 1:
            progress = (i + 1) / total_users * 100
            try:
                await status_message.edit_text(
                    f"⏳ <b>Рассылка в процессе</b>\n\n"
                    f"Отправлено: {i + 1}/{total_users} ({progress:.1f}%)\n"
                    f"Успешно: {len(successful)}\n"
                    f"Ошибок: {len(failed)}\n\n"
                    f"Пожалуйста, дождитесь завершения.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении статуса: {e}")
        
        # Делаем паузу, чтобы не превысить лимиты Telegram
        await asyncio.sleep(0.1)
    
    # Формируем итоговый отчет
    success_rate = len(successful) / total_users * 100 if total_users > 0 else 0
    
    report = (
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"<b>Всего получателей:</b> {total_users}\n"
        f"<b>Успешно отправлено:</b> {len(successful)} ({success_rate:.1f}%)\n"
        f"<b>Ошибок:</b> {len(failed)}\n\n"
    )
    
    if failed:
        # Получаем информацию о пользователях для более понятного отображения
        user_info = {}
        all_errors_info = []
        
        async with AsyncSessionLocal() as session:
            for user_id, error in failed:
                user = await get_user_by_telegram_id(session, user_id)
                if user:
                    # Формируем имя для отображения (предпочитаем username)
                    display_name = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
                    if not display_name:
                        display_name = f"ID {user_id}"
                    
                    # Создаем ссылку на пользователя
                    user_link = f"<a href=\"tg://user?id={user_id}\">{display_name}</a>"
                    user_info[user_id] = user_link
                else:
                    user_info[user_id] = f"ID {user_id}"
                
                # Определяем тип ошибки и делаем более понятное описание
                error_description = error
                if "bot was blocked" in error:
                    error_description = "Пользователь заблокировал бота"
                elif "chat not found" in error:
                    error_description = "Чат не найден"
                elif "user is deactivated" in error:
                    error_description = "Аккаунт пользователя деактивирован"
                
                all_errors_info.append((user_id, error_description))
        
        # Сохраняем полный список ошибок в состоянии для пагинации
        await state.set_state(AdminStates.broadcast_error_page)
        report_header = (
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"<b>Всего получателей:</b> {total_users}\n"
            f"<b>Успешно отправлено:</b> {len(successful)} ({success_rate:.1f}%)\n"
            f"<b>Ошибок:</b> {len(failed)}\n\n"
        )
        await state.update_data(
            errors=all_errors_info, 
            user_info=user_info, 
            current_page=0,
            report_header=report_header,
            successful=successful,
            success_rate=success_rate,
            total_users=total_users
        )
        
        # Показываем первую страницу ошибок (10 штук)
        await show_broadcast_errors_page(callback.message, all_errors_info, user_info, 0, state)
    else:
        # Если ошибок нет, просто показываем сообщение об успешном завершении
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Вернуться в меню", callback_data="admin_back")]
            ]
        )
        
        await status_message.edit_text(report, reply_markup=keyboard, parse_mode="HTML")
        
        # Сбрасываем состояние
        await state.clear()

# Функция для отображения страницы с ошибками рассылки
async def show_broadcast_errors_page(message, all_errors, user_info, page, state):
    # Константа для количества ошибок на странице
    ERRORS_PER_PAGE = 10
    
    # Рассчитываем общее количество страниц
    total_errors = len(all_errors)
    total_pages = (total_errors + ERRORS_PER_PAGE - 1) // ERRORS_PER_PAGE
    
    # Формируем отчет для текущей страницы
    start_idx = page * ERRORS_PER_PAGE
    end_idx = min(start_idx + ERRORS_PER_PAGE, total_errors)
    
    # Получаем данные состояния для доступа к полному отчету
    state_data = await state.get_data()
    report = state_data.get("report_header", "")
    
    # Добавляем информацию о текущей странице
    report += f"<b>Ошибки при отправке (стр. {page+1}/{total_pages}):</b>\n"
    
    # Добавляем ошибки для текущей страницы
    for i, (user_id, error) in enumerate(all_errors[start_idx:end_idx]):
        report += f"{start_idx+i+1}. {user_info.get(user_id, f'ID {user_id}')}: {error}\n"
    
    # Создаем клавиатуру с кнопками навигации
    keyboard_buttons = []
    
    # Кнопки навигации
    navigation_buttons = []
    
    # Кнопка "Назад" (если не на первой странице)
    if page > 0:
        navigation_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"broadcast_errors_page:{page-1}")
        )
    
    # Индикатор страницы (неактивная кнопка)
    navigation_buttons.append(
        InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore")
    )
    
    # Кнопка "Вперед" (если не на последней странице)
    if page < total_pages - 1:
        navigation_buttons.append(
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"broadcast_errors_page:{page+1}")
        )
    
    keyboard_buttons.append(navigation_buttons)
    
    # Кнопка возврата в меню администратора
    keyboard_buttons.append([InlineKeyboardButton(text="« Вернуться в меню", callback_data="admin_back")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    # Обновляем сообщение с отчетом
    try:
        await message.edit_text(report, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Игнорируем ошибку, если содержимое сообщения не изменилось
            logger.debug("Содержимое сообщения не изменилось, игнорируем ошибку")
            pass
        else:
            # Если ошибка другая, логируем и пробрасываем дальше
            logger.error(f"Ошибка при обновлении сообщения: {e}")
            raise

# Обработчик для пагинации ошибок рассылки
@admin_router.callback_query(F.data.startswith("broadcast_errors_page:"))
async def process_broadcast_errors_page(callback: CallbackQuery, state: FSMContext):
    """Обработчик для навигации по страницам с ошибками рассылки"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем номер страницы из данных колбэка
    page_data = callback.data.split(":")
    try:
        page = int(page_data[1]) if len(page_data) > 1 else 0
    except (ValueError, IndexError):
        page = 0
        logger.error(f"Ошибка при парсинге номера страницы из {page_data}, устанавливаю page=0")
    
    # Получаем данные из состояния
    user_data = await state.get_data()
    all_errors = user_data.get("errors", [])
    user_info = user_data.get("user_info", {})
    
    # Проверяем границы страниц
    total_pages = (len(all_errors) + 10 - 1) // 10  # 10 ошибок на страницу
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    
    await callback.answer()
    
    # Обновляем текущую страницу в состоянии
    await state.update_data(current_page=page)
    
    # Показываем выбранную страницу с ошибками
    await show_broadcast_errors_page(callback.message, all_errors, user_info, page, state)

# Константа для количества подписок на странице
SUBSCRIPTIONS_PAGE_SIZE = 10

# Новое состояние для пагинации подписок
class AdminSubscriptionStates(StatesGroup):
    viewing_page = State()

@admin_router.callback_query(F.data.startswith("admin_subscription_dates"))
async def process_subscription_dates(callback: CallbackQuery, state: FSMContext):
    """Обработчик для отображения сроков подписок, отсортированных по дате окончания"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    logger.info(f"Вызов process_subscription_dates с callback data: {callback.data}")
    
    # Получаем номер страницы, если он есть в данных колбэка
    page_data = callback.data.split(":")
    logger.info(f"Получены данные callback: {callback.data}, разделенные: {page_data}")
    
    try:
        page = int(page_data[1]) if len(page_data) > 1 else 0
    except (ValueError, IndexError):
        page = 0
        logger.error(f"Ошибка при парсинге номера страницы из {page_data}, устанавливаю page=0")
    
    logger.info(f"Установлена страница: {page}, тип: {type(page)}")
    
    # Проверяем, что страница не отрицательная
    if page < 0:
        page = 0
        logger.warning(f"Исправлена отрицательная страница на 0")
    
    await callback.answer("Загрузка данных о подписках...")
    
    # Сохраняем текущую страницу в состоянии
    await state.set_state(AdminSubscriptionStates.viewing_page)
    await state.update_data(current_page=page)
    
    # Получаем информацию о подписках
    async with AsyncSessionLocal() as session:
        subscriptions_data = await get_sorted_active_subscriptions(session)
        logger.info(f"Получено подписок: {len(subscriptions_data)}")
        
        # Пагинация
        total_items = len(subscriptions_data)
        total_pages = max(1, (total_items + SUBSCRIPTIONS_PAGE_SIZE - 1) // SUBSCRIPTIONS_PAGE_SIZE)
        logger.info(f"Всего страниц: {total_pages}, текущая: {page+1}, типы: {type(total_pages)}, {type(page)}")
        
        # Проверяем, что страница в допустимых пределах
        if page >= total_pages:
            page = total_pages - 1
            logger.warning(f"Страница вне диапазона, исправлено на: {page}")
        
        # Получаем элементы для текущей страницы
        start_idx = page * SUBSCRIPTIONS_PAGE_SIZE
        end_idx = min(start_idx + SUBSCRIPTIONS_PAGE_SIZE, total_items)
        logger.info(f"Индексы элементов: start_idx={start_idx}, end_idx={end_idx}, total_items={total_items}")
        
        # Проверка на пустой диапазон
        if start_idx >= total_items:
            start_idx = 0
            page = 0
            end_idx = min(SUBSCRIPTIONS_PAGE_SIZE, total_items)
            logger.warning(f"Начальный индекс больше общего количества, сброс на страницу 0")
        
        current_items = subscriptions_data[start_idx:end_idx]
        logger.info(f"Отображаемые элементы: с {start_idx+1} по {end_idx} из {total_items}, количество: {len(current_items)}")
        
        # Формируем текст сообщения
        if not current_items:
            message_text = "<b>📅 Активные подписки:</b>\n\nАктивных подписок не найдено."
            logger.warning("Нет элементов для отображения")
        else:
            current_date = datetime.now()
            message_text = "<b>📅 Активные подписки:</b>\n\n"
            
            for i, (user, subscription) in enumerate(current_items, 1):
                # Рассчитываем, сколько дней осталось до окончания подписки
                days_left = (subscription.end_date - current_date).days
                
                # Форматируем имя пользователя
                user_name = user.first_name or ""
                if user.last_name:
                    user_name += f" {user.last_name}"
                if user.username:
                    user_name += f" (@{user.username})"
                if not user_name.strip():
                    user_name = f"ID: {user.telegram_id}"
                
                # Добавляем индикатор скорого истечения для подписок, которые истекают в ближайшие 7 дней
                expiring_soon = "🔴 " if days_left <= 7 else "🟢 "
                
                # Создаем строку с информацией о подписке
                date_formatted = subscription.end_date.strftime("%d.%m.%Y")
                message_text += f"{expiring_soon}{start_idx + i}. <b>{user_name}</b>\n"
                message_text += f"    📅 <b>Дата окончания:</b> {date_formatted}\n"
                message_text += f"    ⏱ <b>Осталось дней:</b> {days_left}\n\n"
        
        # Создаем клавиатуру с пагинацией
        inline_kb = []
        
        # Кнопки пагинации
        pagination_buttons = []
        
        # Кнопка "Предыдущая страница"
        if page > 0:
            prev_page = page - 1
            pagination_buttons.append(
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_subscription_dates:{prev_page}")
            )
            logger.info(f"Добавлена кнопка 'Назад' с callback_data=admin_subscription_dates:{prev_page}")
        
        # Кнопка "Следующая страница"
        if page < total_pages - 1:
            next_page = page + 1
            pagination_buttons.append(
                InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_subscription_dates:{next_page}")
            )
            logger.info(f"Добавлена кнопка 'Вперед' с callback_data=admin_subscription_dates:{next_page}")
        else:
            logger.info(f"Кнопка 'Вперед' не добавлена, т.к. page={page}, total_pages={total_pages}, сравнение: {page < total_pages - 1}")
        
        # Добавляем кнопки пагинации, если они есть
        if pagination_buttons:
            inline_kb.append(pagination_buttons)
            logger.info(f"Добавлены кнопки пагинации: {pagination_buttons}")
        
        # Добавляем информацию о текущей странице
        if total_pages > 1:
            page_info = f"Страница {page+1}/{total_pages}"
            inline_kb.append([InlineKeyboardButton(text=page_info, callback_data="ignore")])
        
        # Кнопка экспорта всех подписок в Excel
        inline_kb.append([InlineKeyboardButton(text="📊 Экспорт в Excel", callback_data="admin_export_subscriptions")])
        
        # Кнопка обновления данных
        inline_kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_subscription_dates:{page}")])
        
        # Кнопка возврата в главное меню
        inline_kb.append([InlineKeyboardButton(text="« Назад", callback_data="admin_back")])
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=inline_kb)
        
        # Отправляем сообщение с результатами
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
        
        await callback.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")

@admin_router.callback_query(F.data == "admin_export_subscriptions")
async def export_subscriptions(callback: CallbackQuery):
    """Экспортирует данные о подписках в Excel файл"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await callback.answer("Подготовка экспорта... Это может занять некоторое время.")
    
    # Получаем данные всех активных подписок
    async with AsyncSessionLocal() as session:
        subscriptions_data = await get_sorted_active_subscriptions(session)
    
    if not subscriptions_data:
        await callback.message.answer("Нет активных подписок для экспорта.")
        return
    
    # Создаем DataFrame для экспорта
    data = []
    current_date = datetime.now()
    
    for user, subscription in subscriptions_data:
        days_left = (subscription.end_date - current_date).days
        
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
    
    # Создаем DataFrame
    df = pd.DataFrame(data)
    
    # Имя файла с текущей датой
    current_time = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"exports/subscriptions_{current_time}.xlsx"
    
    # Проверяем, существует ли директория exports
    os.makedirs("exports", exist_ok=True)
    
    # Сохраняем в Excel
    df.to_excel(filename, index=False)
    
    # Отправляем файл пользователю
    doc = FSInputFile(filename)
    await callback.message.answer_document(
        document=doc,
        caption="📊 Экспорт данных о подписках. Файл содержит информацию о всех активных подписках, отсортированных по дате окончания."
    )

@admin_router.callback_query(F.data == "ignore")
async def process_ignore(callback: CallbackQuery):
    """Обработчик для игнорирования нажатия на информационную кнопку"""
    await callback.answer()  # Просто снимаем индикатор загрузки, ничего не делаем

# Константа для пагинации дней рождения
BIRTHDAYS_PAGE_SIZE = 10

class AdminBirthdayStates(StatesGroup):
    viewing_page = State()

@admin_router.callback_query(F.data.startswith("admin_birthdays"))
async def process_user_birthdays(callback: CallbackQuery, state: FSMContext):
    """Обработчик для отображения списка пользователей с указанными днями рождения"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    logger.info(f"Вызов process_user_birthdays с callback data: {callback.data}")
    
    # Получаем номер страницы, если он есть в данных колбэка
    page_data = callback.data.split(":")
    
    try:
        page = int(page_data[1]) if len(page_data) > 1 else 0
    except (ValueError, IndexError):
        page = 0
        logger.error(f"Ошибка при парсинге номера страницы из {page_data}, устанавливаю page=0")
    
    # Проверяем, что страница не отрицательная
    if page < 0:
        page = 0
    
    await callback.answer("Загрузка данных о днях рождения...")
    
    # Сохраняем текущую страницу в состоянии
    await state.set_state(AdminBirthdayStates.viewing_page)
    await state.update_data(current_page=page)
    
    # Получаем информацию о пользователях с днями рождения
    async with AsyncSessionLocal() as session:
        users_with_birthdays = await get_users_with_birthdays(session)
        logger.info(f"Получено пользователей с днями рождения: {len(users_with_birthdays)}")
        
        # Текущая дата для определения ближайших дней рождения
        today = datetime.now().date()
        current_month_day = today.strftime('%m-%d')
        
        # Сортируем пользователей так, чтобы ближайшие дни рождения были в начале списка
        # Для этого считаем, сколько дней осталось до дня рождения
        users_with_days = []
        for user in users_with_birthdays:
            if not user.birthday:
                continue
                
            # Получаем месяц и день рождения в формате MM-DD
            birthday_month_day = user.birthday.strftime('%m-%d')
            
            # Вычисляем, сколько дней осталось до дня рождения
            # Если день рождения в этом году уже прошел, считаем до следующего года
            if birthday_month_day < current_month_day:
                # День рождения уже прошел в этом году, будет в следующем
                next_birthday = datetime(today.year + 1, user.birthday.month, user.birthday.day).date()
            else:
                # День рождения еще будет в этом году
                next_birthday = datetime(today.year, user.birthday.month, user.birthday.day).date()
                
            days_until_birthday = (next_birthday - today).days
            
            # Получаем информацию о подписке
            subscription = await get_active_subscription(session, user.id)
            has_active_sub = subscription is not None
            
            users_with_days.append((user, days_until_birthday, birthday_month_day, has_active_sub))
        
        # Сортируем по количеству дней до дня рождения (от меньшего к большему)
        users_with_days.sort(key=lambda x: x[1])
        
        # Пагинация
        total_items = len(users_with_days)
        total_pages = max(1, (total_items + BIRTHDAYS_PAGE_SIZE - 1) // BIRTHDAYS_PAGE_SIZE)
        
        # Проверяем, что страница в допустимых пределах
        if page >= total_pages:
            page = total_pages - 1
        
        # Получаем элементы для текущей страницы
        start_idx = page * BIRTHDAYS_PAGE_SIZE
        end_idx = min(start_idx + BIRTHDAYS_PAGE_SIZE, total_items)
        
        # Проверка на пустой диапазон
        if start_idx >= total_items:
            start_idx = 0
            page = 0
            end_idx = min(BIRTHDAYS_PAGE_SIZE, total_items)
        
        current_items = users_with_days[start_idx:end_idx]
        
        # Формируем текст сообщения
        if not current_items:
            message_text = "<b>🎂 Дни рождения пользователей:</b>\n\nПользователей с указанной датой рождения не найдено."
        else:
            message_text = "<b>🎂 Дни рождения пользователей:</b>\n\n"
            
            for i, (user, days_left, birthday_md, has_active_sub) in enumerate(current_items, 1):
                # Форматируем имя пользователя
                user_name = user.first_name or ""
                if user.last_name:
                    user_name += f" {user.last_name}"
                if user.username:
                    user_name += f" (@{user.username})"
                if not user_name.strip():
                    user_name = f"ID: {user.telegram_id}"
                
                # Добавляем индикатор для пользователей с активной подпиской
                subscription_status = "✅ " if has_active_sub else "❌ "
                
                # Форматируем дату рождения
                birthday_formatted = user.birthday.strftime("%d.%m.%Y")
                
                # Создаем строку с информацией о дне рождения
                message_text += f"{subscription_status}{start_idx + i}. <b>{user_name}</b>\n"
                message_text += f"    📅 <b>Дата рождения:</b> {birthday_formatted}\n"
                
                # Добавляем, сколько дней осталось до дня рождения
                if days_left == 0:
                    message_text += f"    🎉 <b>День рождения сегодня!</b>\n\n"
                elif days_left == 1:
                    message_text += f"    ⏱ <b>День рождения завтра!</b>\n\n"
                else:
                    message_text += f"    ⏱ <b>Дней до дня рождения:</b> {days_left}\n\n"
        
        # Создаем клавиатуру с пагинацией
        inline_kb = []
        
        # Кнопки пагинации
        pagination_buttons = []
        
        # Кнопка "Предыдущая страница"
        if page > 0:
            prev_page = page - 1
            pagination_buttons.append(
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_birthdays:{prev_page}")
            )
        
        # Кнопка "Следующая страница"
        if page < total_pages - 1:
            next_page = page + 1
            pagination_buttons.append(
                InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_birthdays:{next_page}")
            )
        
        # Добавляем кнопки пагинации, если они есть
        if pagination_buttons:
            inline_kb.append(pagination_buttons)
        
        # Добавляем информацию о текущей странице
        if total_pages > 1:
            page_info = f"Страница {page+1}/{total_pages}"
            inline_kb.append([InlineKeyboardButton(text=page_info, callback_data="ignore")])
        
        # Кнопка обновления данных
        inline_kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_birthdays:{page}")])
        
        # Кнопка возврата в главное меню
        inline_kb.append([InlineKeyboardButton(text="« Назад", callback_data="admin_back")])
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=inline_kb)
        
        # Отправляем сообщение с результатами
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
        
        await callback.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")

# Обработчики заявок на отмену автопродления

@admin_router.callback_query(F.data.startswith("approve_cancel_renewal_"))
async def approve_cancel_renewal(callback: CallbackQuery):
    """Одобрить заявку и отключить автопродление"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[-1])
    
    async with AsyncSessionLocal() as session:
        request = await get_cancellation_request_by_id(session, request_id)
        if not request:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        
        if request.status not in ['pending', 'contacted']:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        
        # Отключаем автопродление
        success = await disable_user_auto_renewal(session, request.user_id)
        
        if success:
            # Обновляем статус заявки
            await update_cancellation_request_status(
                session, 
                request_id, 
                'approved',
                reviewed_by=callback.from_user.id,
                admin_notes="Одобрено и отключено"
            )
            
            # Уведомляем пользователя
            try:
                from bot import bot
                user = await get_user_by_id(session, request.user_id)
                await bot.send_message(
                    user.telegram_id,
                    "✅ Ваша заявка на отмену автопродления одобрена.\n\n"
                    "Автопродление отключено. Подписка не будет продлеваться автоматически."
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя: {e}")
            
            await callback.answer("✅ Автопродление отключено", show_alert=True)
            # Обновляем детали заявки (показываем обновленный статус)
            await view_cancellation_request_detail(callback)
        else:
            await callback.answer("Ошибка при отключении автопродления", show_alert=True)

@admin_router.callback_query(F.data.startswith("reject_cancel_renewal_"))
async def reject_cancel_renewal(callback: CallbackQuery):
    """Отклонить заявку"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[-1])
    
    async with AsyncSessionLocal() as session:
        request = await get_cancellation_request_by_id(session, request_id)
        if not request:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        
        if request.status not in ['pending', 'contacted']:
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        
        # Обновляем статус
        await update_cancellation_request_status(
            session,
            request_id,
            'rejected',
            reviewed_by=callback.from_user.id,
            admin_notes="Отклонено"
        )
        
        # Уведомляем пользователя
        try:
            from bot import bot
            user = await get_user_by_id(session, request.user_id)
            await bot.send_message(
                user.telegram_id,
                "ℹ️ Ваша заявка на отмену автопродления рассмотрена.\n\n"
                "Если у вас есть вопросы, обратитесь в службу заботы."
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя: {e}")
        
        await callback.answer("❌ Заявка отклонена", show_alert=True)
        # Обновляем детали заявки (показываем обновленный статус)
        await view_cancellation_request_detail(callback)

@admin_router.callback_query(F.data == "admin_cancellation_requests")
async def show_cancellation_requests_menu(callback: CallbackQuery):
    """Показать меню заявок на отмену автопродления"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        stats = await get_cancellation_requests_stats(session)
        
        text = (
            f"🚫 <b>Заявки на отмену автопродления</b>\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"   Всего заявок: {stats['total']}\n"
            f"   ⏳ Ожидают: {stats['pending']}\n"
            f"   💬 Связались: {stats['contacted']}\n"
            f"   ✅ Одобрено: {stats['approved']}\n"
            f"   ❌ Отклонено: {stats['rejected']}\n\n"
            f"Выберите фильтр:"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⏳ Ожидающие ({stats['pending']})", callback_data="admin_cancel_requests_filter:pending")],
            [InlineKeyboardButton(text=f"💬 Связались ({stats['contacted']})", callback_data="admin_cancel_requests_filter:contacted")],
            [InlineKeyboardButton(text="📋 Все заявки", callback_data="admin_cancel_requests_filter:all")],
            [InlineKeyboardButton(text="« Назад в админку", callback_data="admin_back")]
        ])
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()

@admin_router.callback_query(F.data.startswith("admin_cancel_requests_filter:"))
async def show_cancellation_requests_list(callback: CallbackQuery):
    """Показать список заявок с фильтром"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    filter_type = callback.data.split(":")[1]
    
    async with AsyncSessionLocal() as session:
        if filter_type == "all":
            requests = await get_all_cancellation_requests(session, limit=20)
            filter_name = "Все заявки"
        else:
            requests = await get_all_cancellation_requests(session, status=filter_type, limit=20)
            status_names = {
                'pending': 'Ожидающие',
                'contacted': 'Связались',
                'approved': 'Одобренные',
                'rejected': 'Отклоненные'
            }
            filter_name = status_names.get(filter_type, filter_type)
        
        if not requests:
            await callback.answer(f"Нет заявок со статусом '{filter_name}'", show_alert=True)
            return
        
        text = f"📋 <b>{filter_name} ({len(requests)}):</b>\n\n"
        keyboard_buttons = []
        
        status_emojis = {
            'pending': '⏳',
            'contacted': '💬',
            'approved': '✅',
            'rejected': '❌'
        }
        
        for req in requests:
            user = await get_user_by_id(session, req.user_id)
            if not user:
                continue
            
            username = f"@{user.username}" if user.username else f"ID:{user.telegram_id}"
            date = req.created_at.strftime('%d.%m.%Y %H:%M')
            status_emoji = status_emojis.get(req.status, '📄')
            
            # Проверяем активную подписку
            active_sub = await get_active_subscription(session, user.id)
            sub_info = ""
            if active_sub:
                sub_info = f" (до {active_sub.end_date.strftime('%d.%m')})"
            
            text += f"{status_emoji} <b>#{req.id}</b> - {user.first_name} {username}{sub_info}\n"
            text += f"   📅 {date}\n\n"
            
            # Кнопки действий только для pending и contacted
            if req.status in ['pending', 'contacted']:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text=f"#{req.id} {user.first_name}",
                        callback_data=f"view_cancel_request_{req.id}"
                    )
                ])
        
        # Кнопки навигации
        nav_buttons = [
            [InlineKeyboardButton(text="« Назад", callback_data="admin_cancellation_requests")]
        ]
        
        if keyboard_buttons:
            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons + nav_buttons)
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=nav_buttons)
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()

@admin_router.callback_query(F.data.startswith("view_cancel_request_"))
async def view_cancellation_request_detail(callback: CallbackQuery):
    """Показать детали заявки с возможностью действий"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[-1])
    
    async with AsyncSessionLocal() as session:
        request = await get_cancellation_request_by_id(session, request_id)
        if not request:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        
        user = await get_user_by_id(session, request.user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        active_sub = await get_active_subscription(session, user.id)
        
        status_names = {
            'pending': '⏳ Ожидает',
            'contacted': '💬 Связались',
            'approved': '✅ Одобрено',
            'rejected': '❌ Отклонено'
        }
        
        username = f"@{user.username}" if user.username else "нет username"
        
        text = (
            f"🚫 <b>Заявка #{request.id}</b>\n\n"
            f"👤 <b>Пользователь:</b>\n"
            f"   Имя: {user.first_name} {user.last_name or ''}\n"
            f"   Username: {username}\n"
            f"   Telegram ID: <code>{user.telegram_id}</code>\n"
            f"   Телефон: {user.phone or 'не указан'}\n"
            f"   Email: {user.email or 'не указан'}\n\n"
        )
        
        if active_sub:
            text += (
                f"📅 <b>Подписка:</b>\n"
                f"   Действует до: {active_sub.end_date.strftime('%d.%m.%Y')}\n"
                f"   Автопродление: {'✅ Включено' if user.is_recurring_active else '❌ Отключено'}\n\n"
            )
        
        text += (
            f"📊 <b>Статус заявки:</b> {status_names.get(request.status, request.status)}\n"
            f"📅 Создана: {request.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )
        
        if request.contacted_at:
            text += f"💬 Связались: {request.contacted_at.strftime('%d.%m.%Y %H:%M')}\n"
        
        if request.reviewed_at:
            text += f"👤 Рассмотрена: {request.reviewed_at.strftime('%d.%m.%Y %H:%M')}\n"
            if request.admin_notes:
                text += f"📝 Заметки: {request.admin_notes}\n"
        
        keyboard_buttons = []
        
        # Кнопки действий только если заявка не обработана
        if request.status in ['pending', 'contacted']:
            keyboard_buttons.append([
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_cancel_renewal_{request_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_cancel_renewal_{request_id}")
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="« Назад к списку", callback_data="admin_cancellation_requests")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()

# Старый обработчик для обратной совместимости
@admin_router.callback_query(F.data == "admin_pending_cancellations")
async def show_pending_cancellations(callback: CallbackQuery):
    """Показать список ожидающих заявок (старая версия, перенаправляет на новую)"""
    # Перенаправляем на новое меню
    await show_cancellation_requests_menu(callback)

@admin_router.message(Command("contacted_cancel"))
async def cmd_contacted_cancel(message: types.Message):
    """Команда для службы заботы - отметить заявку как 'связались'"""
    # Проверка на админа не обязательна, но можно добавить проверку на службу заботы
    # if message.from_user.username != "momsclubsupport":
    #     return
    
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /contacted_cancel <request_id>")
        return
    
    try:
        request_id = int(parts[1])
    except ValueError:
        await message.answer("Некорректный ID заявки")
        return
    
    async with AsyncSessionLocal() as session:
        request = await get_cancellation_request_by_id(session, request_id)
        if not request:
            await message.answer("❌ Заявка не найдена")
            return
        
        await mark_cancellation_request_contacted(session, request_id)
        await message.answer(
            f"✅ Заявка #{request_id} отмечена как 'связались с пользователем'.\n"
            f"Админы получат уведомление."
        )
        
        # Уведомляем админов
        from bot import bot
        user = await get_user_by_id(session, request.user_id)
        if user:
            user_info = f"{user.first_name} (@{user.username})" if user.username else f"{user.first_name} (ID:{user.telegram_id})"
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"🛟 Служба заботы связалась с пользователем по заявке #{request_id}\n"
                        f"👤 {user_info}"
                    )
                except:
                    pass

def register_admin_handlers(dp):
    dp.include_router(admin_router)
    logger.info("Административные обработчики зарегистрированы") 