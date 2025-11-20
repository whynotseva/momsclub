from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from utils.constants import ADMIN_IDS
from utils.admin_permissions import can_manage_admins
from database.crud import get_user_by_telegram_id
from utils.helpers import html_kv, success, error
from database.config import AsyncSessionLocal
from sqlalchemy import select, update
from database.models import User, LoyaltyEvent, Subscription
from loyalty.service import effective_discount
from loyalty.levels import calc_tenure_days, level_for_days
from loyalty.benefits import apply_benefit
import logging
from datetime import datetime, timedelta
import os
import asyncio

logger = logging.getLogger(__name__)

loyalty_router = Router()


class AdminLoyaltyStates(StatesGroup):
    loyalty_waiting_user = State()
    loyalty_waiting_user_for_level = State()
    loyalty_waiting_level = State()
    loyalty_waiting_user_for_grant = State()
    loyalty_waiting_benefit = State()
    loyalty_waiting_report_dates = State()


def register_admin_loyalty_handlers(dp):
    dp.include_router(loyalty_router)


@loyalty_router.callback_query(F.data == "admin_loyalty_menu")
async def show_loyalty_menu(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Информация о пользователе", callback_data="admin_loyalty_user_info")],
        [InlineKeyboardButton(text="⭐ Установить уровень", callback_data="admin_loyalty_set_level")],
        [InlineKeyboardButton(text="🎁 Выдать бонус", callback_data="admin_loyalty_grant_benefit")],
        [InlineKeyboardButton(text="📊 Отчёт по лояльности", callback_data="admin_loyalty_report")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
    ])
    try:
        if callback.message.photo:
            await callback.message.edit_caption("💎 <b>Система лояльности</b>\n\nВыберите действие:", reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text("💎 <b>Система лояльности</b>\n\nВыберите действие:", reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer("💎 <b>Система лояльности</b>\n\nВыберите действие:", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@loyalty_router.callback_query(F.data == "admin_loyalty_user_info")
async def loyalty_user_info_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.set_state(AdminLoyaltyStates.loyalty_waiting_user)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_loyalty_menu")]])
    text = (
        "👤 <b>Информация о пользователе</b>\n\nВведите Telegram ID или Username пользователя:\n(ID должен быть числом, username — с символом @)"
    )
    try:
        if callback.message.photo:
            await callback.message.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@loyalty_router.message(StateFilter(AdminLoyaltyStates.loyalty_waiting_user))
async def loyalty_show_user_info(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    search_term = message.text.strip()
    async with AsyncSessionLocal() as session:
        user = None
        if search_term.startswith("@"):
            username = search_term[1:]
            from database.crud import get_user_by_username, get_active_subscription
            user = await get_user_by_username(session, username)
        else:
            try:
                user_id = int(search_term)
                from database.crud import get_user_by_telegram_id, get_active_subscription
                user = await get_user_by_telegram_id(session, user_id)
            except ValueError:
                await message.answer(error("Некорректный формат! Введите числовой ID или username с символом @"))
                return
        if not user:
            await message.answer(error(f"Пользователь не найден: {search_term}"))
            await state.clear()
            return
        from database.crud import get_active_subscription
        active_sub = await get_active_subscription(session, user.id)
        tenure_days = await calc_tenure_days(session, user)
        level = level_for_days(tenure_days)
        discount = effective_discount(user)
        autorenewal_status = "Включено" if getattr(user, "is_recurring_active", False) else "Выключено"
        discount_lines = []
        if user.one_time_discount_percent > 0:
            discount_lines.append(f"💰 Разовая скидка: {user.one_time_discount_percent}%")
        if user.lifetime_discount_percent > 0:
            discount_lines.append(f"💎 Постоянная скидка: {user.lifetime_discount_percent}% ✨ (лояльность)")
        else:
            discount_lines.append(f"💎 Постоянная скидка: {user.lifetime_discount_percent}%")
        discount_info = "\n".join(discount_lines) if discount_lines else "💎 Постоянная скидка: 0%"
        lines = [
            "👤 <b>Информация о пользователе</b>",
            "",
            html_kv("🆔 Telegram ID", f"<code>{user.telegram_id}</code>"),
            html_kv("👤 Имя", f"{user.first_name} {user.last_name or ''}".strip()),
            html_kv("📱 Username", f"@{user.username}" if user.username else "не указан"),
            "",
            "<b>💎 Лояльность</b>",
            html_kv("📅 Стаж", f"{tenure_days} дней"),
            html_kv("⭐ Уровень", f"{user.current_loyalty_level or 'none'} (рассчитанный: {level})"),
            html_kv("🎁 Ожидает бонус", "Да" if user.pending_loyalty_reward else "Нет"),
            discount_info,
            html_kv("🎁 Подарок", "Да" if user.gift_due else "Нет"),
            html_kv("🔄 Автопродление", autorenewal_status),
            html_kv("💵 Эффективная скидка", f"{discount}%"),
        ]
        info_text = "\n".join(lines)
        if active_sub:
            # Проверяем, является ли подписка бесконечной
            LIFETIME_THRESHOLD = datetime(2099, 1, 1)
            if active_sub.end_date >= LIFETIME_THRESHOLD:
                info_text += (f"\n<b>📅 Подписка</b>\n" + html_kv("Статус", "∞ Пожизненная подписка") + "\n")
            else:
                end_date = active_sub.end_date.strftime('%d.%m.%Y')
                info_text += (f"\n<b>📅 Подписка</b>\n" + html_kv("До", end_date) + "\n" + html_kv("Статус", "Активна" if active_sub.is_active else "Неактивна") + "\n")
        else:
            info_text += "\n<b>📅 Подписка</b>\nНет активной подписки\n"
        if user.first_payment_date:
            first_payment = user.first_payment_date.strftime('%d.%m.%Y')
            info_text += f"\n📆 Первая оплата: {first_payment}\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад в меню лояльности", callback_data="admin_loyalty_menu")]])
        await message.answer(info_text, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()


@loyalty_router.callback_query(F.data == "admin_loyalty_set_level")
async def loyalty_set_level_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.set_state(AdminLoyaltyStates.loyalty_waiting_user_for_level)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_loyalty_menu")]])
    text = "⭐ <b>Установить уровень лояльности</b>\n\nВведите Telegram ID пользователя:"
    try:
        if callback.message.photo:
            await callback.message.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@loyalty_router.message(StateFilter(AdminLoyaltyStates.loyalty_waiting_user_for_level))
async def loyalty_set_level_get_user(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Некорректный формат! Введите числовой Telegram ID")
        return
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_telegram_id
        user = await get_user_by_telegram_id(session, user_id)
        if not user:
            await message.answer(f"❌ Пользователь не найден: {user_id}")
            await state.clear()
            return
        await state.update_data(loyalty_user_id=user_id)
        await state.set_state(AdminLoyaltyStates.loyalty_waiting_level)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="none", callback_data="loyalty_level:none"), InlineKeyboardButton(text="silver", callback_data="loyalty_level:silver")],[InlineKeyboardButton(text="gold", callback_data="loyalty_level:gold"), InlineKeyboardButton(text="platinum", callback_data="loyalty_level:platinum")],[InlineKeyboardButton(text="« Отмена", callback_data="admin_loyalty_menu")]])
        await message.answer(
            f"⭐ <b>Установить уровень</b>\n\n" + html_kv("Пользователь", str(user_id)) + "\n" + html_kv("Текущий уровень", user.current_loyalty_level or 'none'),
            reply_markup=keyboard,
            parse_mode="HTML",
        )


@loyalty_router.callback_query(F.data.startswith("admin_loyalty_set_level_from_user:"))
async def loyalty_set_level_from_user(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Изменить уровень' из меню пользователя"""
    logger.info(f"[loyalty] Обработчик loyalty_set_level_from_user вызван, callback_data: {callback.data}")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    try:
        telegram_id = int(callback.data.split(":")[1])
        logger.info(f"[loyalty] Извлечен telegram_id: {telegram_id}")
    except (ValueError, IndexError) as e:
        logger.error(f"[loyalty] Ошибка при парсинге callback_data: {e}, data: {callback.data}")
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_telegram_id
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            logger.error(f"[loyalty] Пользователь не найден: {telegram_id}")
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        logger.info(f"[loyalty] Пользователь найден: {user.id}, текущий уровень: {user.current_loyalty_level}")
        await state.update_data(loyalty_user_id=telegram_id, from_user_menu=True)
        await state.set_state(AdminLoyaltyStates.loyalty_waiting_level)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="none", callback_data="loyalty_level:none"), 
             InlineKeyboardButton(text="silver", callback_data="loyalty_level:silver")],
            [InlineKeyboardButton(text="gold", callback_data="loyalty_level:gold"), 
             InlineKeyboardButton(text="platinum", callback_data="loyalty_level:platinum")],
            [InlineKeyboardButton(text="« Назад", callback_data=f"admin_user_info:{telegram_id}")]
        ])
        try:
            logger.info(f"[loyalty] Пытаюсь отредактировать сообщение")
            await callback.message.edit_text(
                f"⭐ <b>Установить уровень</b>\n\n" + 
                html_kv("Пользователь", str(telegram_id)) + "\n" + 
                html_kv("Текущий уровень", user.current_loyalty_level or 'none'),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            logger.info(f"[loyalty] Сообщение успешно отредактировано")
        except Exception as e:
            logger.error(f"[loyalty] Ошибка при редактировании сообщения: {e}, пытаюсь отправить новое")
            await callback.message.answer(
                f"⭐ <b>Установить уровень</b>\n\n" + 
                html_kv("Пользователь", str(telegram_id)) + "\n" + 
                html_kv("Текущий уровень", user.current_loyalty_level or 'none'),
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            logger.info(f"[loyalty] Новое сообщение отправлено")
    await callback.answer()
    logger.info(f"[loyalty] Обработчик loyalty_set_level_from_user завершен")


@loyalty_router.callback_query(F.data.startswith("admin_loyalty_grant_from_user:"))
async def loyalty_grant_from_user(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Выдать бонус' из меню пользователя"""
    logger.info(f"[loyalty] Обработчик loyalty_grant_from_user вызван, callback_data: {callback.data}")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    try:
        telegram_id = int(callback.data.split(":")[1])
        logger.info(f"[loyalty] Извлечен telegram_id: {telegram_id}")
    except (ValueError, IndexError) as e:
        logger.error(f"[loyalty] Ошибка при парсинге callback_data: {e}, data: {callback.data}")
        await callback.answer("❌ Ошибка: неверный формат данных", show_alert=True)
        return
    
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_telegram_id
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            logger.error(f"[loyalty] Пользователь не найден: {telegram_id}")
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
        
        logger.info(f"[loyalty] Пользователь найден: {user.id}")
        await state.update_data(loyalty_grant_user_id=telegram_id, from_user_menu=True)
        await state.set_state(AdminLoyaltyStates.loyalty_waiting_benefit)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="5% скидка", callback_data="loyalty_benefit:discount_5"), 
             InlineKeyboardButton(text="10% скидка", callback_data="loyalty_benefit:discount_10")],
            [InlineKeyboardButton(text="15% навсегда", callback_data="loyalty_benefit:discount_15_forever"), 
             InlineKeyboardButton(text="7 дней", callback_data="loyalty_benefit:days_7")],
            [InlineKeyboardButton(text="14 дней", callback_data="loyalty_benefit:days_14"), 
             InlineKeyboardButton(text="30 дней+подарок", callback_data="loyalty_benefit:days_30_gift")],
            [InlineKeyboardButton(text="« Назад", callback_data=f"admin_user_info:{telegram_id}")]
        ])
        try:
            logger.info(f"[loyalty] Пытаюсь отредактировать сообщение")
            await callback.message.edit_text(
                "🎁 <b>Выдать бонус</b>\n\n" + html_kv("Пользователь", str(telegram_id)),
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            logger.info(f"[loyalty] Сообщение успешно отредактировано")
        except Exception as e:
            logger.error(f"[loyalty] Ошибка при редактировании сообщения: {e}, пытаюсь отправить новое")
            await callback.message.answer(
                "🎁 <b>Выдать бонус</b>\n\n" + html_kv("Пользователь", str(telegram_id)),
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            logger.info(f"[loyalty] Новое сообщение отправлено")
    await callback.answer()
    logger.info(f"[loyalty] Обработчик loyalty_grant_from_user завершен")


@loyalty_router.callback_query(F.data.startswith("loyalty_level:"))
async def loyalty_set_level_apply(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    level = callback.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get("loyalty_user_id")
    if not user_id:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        await state.clear()
        return
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_telegram_id
        user = await get_user_by_telegram_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            await state.clear()
            return
        await session.execute(update(User).where(User.id == user.id).values(current_loyalty_level=level))
        await session.commit()
    await callback.answer(success(f"Уровень установлен: {level}"))
    # Проверяем, откуда пришел запрос - из меню лояльности или из меню пользователя
    from_user_menu = data.get("from_user_menu", False)
    
    if from_user_menu:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад к пользователю", callback_data=f"admin_user_info:{user_id}")]])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад в меню лояльности", callback_data="admin_loyalty_menu")]])
    
    try:
        await callback.message.edit_text(success(f"Уровень лояльности установлен: <b>{level}</b> для пользователя {user_id}"), reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(success(f"Уровень лояльности установлен: <b>{level}</b> для пользователя {user_id}"), reply_markup=keyboard, parse_mode="HTML")
    await state.clear()


@loyalty_router.callback_query(F.data == "admin_loyalty_grant_benefit")
async def loyalty_grant_benefit_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.set_state(AdminLoyaltyStates.loyalty_waiting_user_for_grant)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_loyalty_menu")]])
    text = "🎁 <b>Выдать бонус</b>\n\nВведите Telegram ID пользователя:"
    try:
        if callback.message.photo:
            await callback.message.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@loyalty_router.message(StateFilter(AdminLoyaltyStates.loyalty_waiting_user_for_grant))
async def loyalty_grant_benefit_get_user(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Некорректный формат! Введите числовой Telegram ID")
        return
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_telegram_id
        user = await get_user_by_telegram_id(session, user_id)
        if not user:
            await message.answer(f"❌ Пользователь не найден: {user_id}")
            await state.clear()
            return
        await state.update_data(loyalty_grant_user_id=user_id)
        await state.set_state(AdminLoyaltyStates.loyalty_waiting_benefit)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="5% скидка", callback_data="loyalty_benefit:discount_5"), InlineKeyboardButton(text="10% скидка", callback_data="loyalty_benefit:discount_10")],[InlineKeyboardButton(text="15% навсегда", callback_data="loyalty_benefit:discount_15_forever"), InlineKeyboardButton(text="7 дней", callback_data="loyalty_benefit:days_7")],[InlineKeyboardButton(text="14 дней", callback_data="loyalty_benefit:days_14"), InlineKeyboardButton(text="30 дней+подарок", callback_data="loyalty_benefit:days_30_gift")],[InlineKeyboardButton(text="« Отмена", callback_data="admin_loyalty_menu")]])
        await message.answer("🎁 <b>Выдать бонус</b>\n\n" + html_kv("Пользователь", str(user_id)), reply_markup=keyboard, parse_mode="HTML")


@loyalty_router.callback_query(F.data.startswith("loyalty_benefit:"))
async def loyalty_grant_benefit_apply(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    code = callback.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get("loyalty_grant_user_id")
    if not user_id:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        await state.clear()
        return
    async with AsyncSessionLocal() as session:
        from database.crud import get_user_by_telegram_id
        user = await get_user_by_telegram_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            await state.clear()
            return
        level = user.current_loyalty_level or 'silver'
        success = await apply_benefit(session, user, level, code)
    if success:
        await callback.answer(f"✅ Бонус {code} успешно применён")
    else:
        await callback.answer("❌ Не удалось применить бонус", show_alert=True)
        result_text = f"❌ Не удалось применить бонус {code} пользователю {user_id}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад в меню лояльности", callback_data="admin_loyalty_menu")]])
        try:
            await callback.message.edit_text(result_text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()
        return
    result_text = f"✅ Бонус <b>{code}</b> успешно применён пользователю {user_id}"
    # Проверяем, откуда пришел запрос - из меню лояльности или из меню пользователя
    from_user_menu = data.get("from_user_menu", False)
    
    if from_user_menu:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад к пользователю", callback_data=f"admin_user_info:{user_id}")]])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад в меню лояльности", callback_data="admin_loyalty_menu")]])
    
    try:
        await callback.message.edit_text(result_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(result_text, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()


@loyalty_router.callback_query(F.data == "admin_loyalty_report")
async def loyalty_report_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.set_state(AdminLoyaltyStates.loyalty_waiting_report_dates)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_loyalty_menu")]])
    text = (
        "📊 <b>Отчёт по лояльности</b>\n\n"
        "Введите диапазон дат в формате:\n<code>YYYY-MM-DD..YYYY-MM-DD</code>\n\n"
        "Пример: <code>2025-01-01..2025-11-30</code>"
    )
    try:
        if callback.message.photo:
            await callback.message.edit_caption(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@loyalty_router.message(StateFilter(AdminLoyaltyStates.loyalty_waiting_report_dates))
async def loyalty_report_generate(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    date_range = message.text.strip()
    if ".." not in date_range:
        await message.answer("❌ Неверный формат диапазона дат. Используйте: YYYY-MM-DD..YYYY-MM-DD")
        return
    try:
        start_str, end_str = date_range.split("..")
        start_date = datetime.strptime(start_str.strip(), "%Y-%m-%d")
        end_date = datetime.strptime(end_str.strip(), "%Y-%m-%d")
    except ValueError as e:
        await message.answer(f"❌ Ошибка формата даты: {e}")
        return
    async with AsyncSessionLocal() as session:
        query = (
            select(LoyaltyEvent, User)
            .join(User, LoyaltyEvent.user_id == User.id)
            .where(LoyaltyEvent.created_at >= start_date)
            .where(LoyaltyEvent.created_at <= end_date + timedelta(days=1))
            .order_by(LoyaltyEvent.created_at.desc())
        )
        result = await session.execute(query)
        events = result.all()
        if not events:
            await message.answer(f"❌ Нет данных за период {start_str} - {end_str}")
            await state.clear()
            return
        import csv, io, tempfile
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['user_id','telegram_id','username','level','chosen_benefit','tenure_days','active_until','discount_one_time','discount_lifetime','gift_due','dt'])
        from database.crud import get_active_subscription
        for event, user in events:
            active_sub = await get_active_subscription(session, user.id)
            tenure_days = await calc_tenure_days(session, user)
            chosen_benefit = None
            if event.payload:
                try:
                    import json
                    payload = json.loads(event.payload)
                    chosen_benefit = payload.get('benefit')
                except:
                    pass
            active_until = active_sub.end_date.strftime('%Y-%m-%d') if active_sub else 'N/A'
            writer.writerow([user.id,user.telegram_id,user.username or '',event.level or user.current_loyalty_level or 'none',chosen_benefit or '',tenure_days,active_until,user.one_time_discount_percent,user.lifetime_discount_percent,'Да' if user.gift_due else 'Нет',event.created_at.strftime('%Y-%m-%d %H:%M:%S')])
        csv_content = output.getvalue()
        output.close()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as f:
            f.write(csv_content)
            temp_path = f.name
        await message.answer_document(FSInputFile(temp_path), caption=f"📊 Отчёт по лояльности за период {start_str} - {end_str} ({len(events)} записей)")
        try:
            await asyncio.sleep(1)
            os.unlink(temp_path)
        except:
            pass
        await state.clear()