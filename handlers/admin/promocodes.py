from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from utils.constants import ADMIN_IDS
from utils.admin_permissions import can_manage_admins
from database.crud import get_user_by_telegram_id
from utils.helpers import html_kv, fmt_date, success, error, admin_nav_back
from database.config import AsyncSessionLocal
from database.crud import (
    get_all_promo_codes,
    get_total_promo_codes_count,
    get_promo_code_by_code,
    create_promo_code,
    update_promo_code,
    delete_promo_code_by_id,
)
from database.models import PromoCode
from sqlalchemy import select
import math
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

promos_router = Router()

PROMO_PAGE_SIZE = 5


class AdminPromocodeStates(StatesGroup):
    editing = State()
    editing_max_uses = State()
    editing_expiry = State()
    waiting_code = State()
    waiting_value = State()
    waiting_max_uses = State()
    waiting_expiry = State()


def register_admin_promocodes_handlers(dp):
    dp.include_router(promos_router)


async def _build_promo_list_message(page: int = 0):
    offset = page * PROMO_PAGE_SIZE
    async with AsyncSessionLocal() as session:
        promo_codes = await get_all_promo_codes(session, limit=PROMO_PAGE_SIZE, offset=offset)
        total_promos = await get_total_promo_codes_count(session)

    total_pages = max(1, math.ceil(total_promos / PROMO_PAGE_SIZE))
    current_page_display = page + 1

    keyboard_buttons = []
    if not promo_codes and page == 0:
        text = "🎟️ <b>Список промокодов пуст.</b>"
        keyboard_buttons = [
            [InlineKeyboardButton(text="➕ Добавить промокод", callback_data="admin_add_promo")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
        ]
    elif not promo_codes:
        text = f"🎟️ <b>Ошибка:</b> Страница {current_page_display} не найдена."
        keyboard_buttons = [
            [InlineKeyboardButton(text="К началу списка", callback_data="admin_manage_promocodes_page_0")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
        ]
    else:
        text_lines = [f"🎟️ <b>Список промокодов</b>", html_kv("Страница", f"{current_page_display}/{total_pages}"), ""]
        for promo in promo_codes:
            expiry_date = promo.expiry_date.strftime("%d.%m.%Y") if promo.expiry_date else "бессрочный"
            max_uses = promo.max_uses if promo.max_uses is not None else "∞"
            status = "✅ Активен" if promo.is_active else "❌ Неактивен"
            details = [
                html_kv("Код", f"<code>{promo.code}</code>"),
                html_kv("Бонусные дни", str(promo.value)),
                html_kv("Использований", f"{promo.current_uses}/{max_uses}"),
                html_kv("Действует до", expiry_date),
                html_kv("Статус", status),
            ]
            text_lines.append(" • " + " | ".join(details))
            row = []
            row.append(InlineKeyboardButton(text=("❌ Деактив." if promo.is_active else "✅ Актив."), callback_data=f"admin_toggle_promo_{promo.id}"))
            row.append(InlineKeyboardButton(text="✏️ Ред.", callback_data=f"admin_edit_promo_{promo.id}"))
            row.append(InlineKeyboardButton(text="🗑️ Удал.", callback_data=f"admin_delete_promo_{promo.id}"))
            keyboard_buttons.append(row)
        text_lines.append("")
        text_lines.append(html_kv("Всего промокодов", str(total_promos)))
        pagination_row = []
        if page > 0:
            pagination_row.append(InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"admin_manage_promocodes_page_{page-1}"))
        if total_pages > 1:
            pagination_row.append(InlineKeyboardButton(text=f"- {current_page_display}/{total_pages} -", callback_data="noop"))
        if current_page_display < total_pages:
            pagination_row.append(InlineKeyboardButton(text="➡️ След.", callback_data=f"admin_manage_promocodes_page_{page+1}"))
        if pagination_row:
            keyboard_buttons.append(pagination_row)
        keyboard_buttons.extend([
            [InlineKeyboardButton(text="➕ Добавить промокод", callback_data="admin_add_promo")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    return "\n".join(text_lines), keyboard


@promos_router.callback_query(F.data.startswith("admin_manage_promocodes"))
async def admin_manage_promocodes(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_manage_promocodes: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    page = 0
    if "_page_" in callback.data:
        try:
            page = int(callback.data.split("_page_")[-1])
        except Exception:
            page = 0
    await callback.answer(f"Загружаю стр. {page+1}...")
    text, keyboard = await _build_promo_list_message(page)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@promos_router.callback_query(F.data.startswith("admin_delete_promo_"))
async def admin_delete_promo_confirm(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_delete_promo_confirm: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    try:
        promo_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("Ошибка: неверный ID", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(PromoCode).where(PromoCode.id == promo_id))
        promo = q.scalar_one_or_none()
    if not promo:
        await callback.answer("Промокод не найден", show_alert=True)
        callback.data = "admin_manage_promocodes_page_0"
        await admin_manage_promocodes(callback, state)
        return
    text = f"🗑️ Удалить промокод <code>{promo.code}</code>?\n\n⚠️ Действие необратимо."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_delete_exec_{promo_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_manage_promocodes")],
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@promos_router.callback_query(F.data.startswith("admin_delete_exec_"))
async def admin_delete_promo_execute(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_delete_promo_execute: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    try:
        promo_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("Ошибка: неверный ID", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        deleted = await delete_promo_code_by_id(session, promo_id)
    await callback.answer(success("Промокод удален") if deleted else error("Не удалось удалить"), show_alert=not deleted)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")]])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        success("Промокод успешно удален!") if deleted else error("Не удалось удалить промокод."),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@promos_router.callback_query(F.data.startswith("admin_toggle_promo_"))
async def admin_toggle_promo_status(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_toggle_promo_status: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    try:
        promo_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("Ошибка: неверный ID", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(PromoCode).where(PromoCode.id == promo_id))
        current = q.scalar_one_or_none()
        if not current:
            await callback.answer("Промокод не найден", show_alert=True)
            callback.data = "admin_manage_promocodes_page_0"
            await admin_manage_promocodes(callback, state)
            return
        new_status = not current.is_active
        updated = await update_promo_code(session, promo_id, is_active=new_status)
    action = "активирован" if updated and new_status else "деактивирован"
    text = success(f"Статус промокода <code>{updated.code}</code> изменен: {action}") if updated else error(f"Не удалось изменить статус промокода ID {promo_id}.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")]])
    await callback.answer(success(f"Промокод {action}.") if updated else error("Ошибка изменения"), show_alert=not updated)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@promos_router.callback_query(F.data.startswith("admin_edit_promo_"))
async def admin_edit_promo_start(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_edit_promo_start: {callback.data} by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    try:
        promo_id = int(callback.data.split("_")[-1])
    except Exception:
        await callback.answer("Ошибка: неверный ID", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(PromoCode).where(PromoCode.id == promo_id))
        promo = q.scalar_one_or_none()
    if not promo:
        await callback.answer("Промокод не найден", show_alert=True)
        callback.data = "admin_manage_promocodes_page_0"
        await admin_manage_promocodes(callback, state)
        return
    await state.set_state(AdminPromocodeStates.editing)
    await state.update_data(editing_promo_id=promo_id)
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾️ Изменить лимит", callback_data="edit_promo_set_max_uses")],
        [InlineKeyboardButton(text="🗓️ Изменить дату окончания", callback_data="edit_promo_set_expiry")],
        [InlineKeyboardButton(text="« Назад к списку", callback_data="admin_manage_promocodes_page_0")],
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@promos_router.callback_query(F.data == "edit_promo_set_max_uses", StateFilter(AdminPromocodeStates.editing))
async def edit_promo_ask_max_uses(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminPromocodeStates.editing_max_uses)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="edit_promo_cancel_field")]])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "♾️ Введите новый максимальный лимит использований (целое число, `0` или `нет` - безлимит):",
        reply_markup=keyboard,
        parse_mode="MarkdownV2",
    )


@promos_router.message(StateFilter(AdminPromocodeStates.editing_max_uses))
async def edit_promo_process_max_uses(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    max_uses_input = message.text.strip().lower()
    new_max_uses = None
    if max_uses_input not in ["0", "нет", "no", "none", "null"]:
        try:
            new_max_uses = int(max_uses_input)
            if new_max_uses < 0:
                await message.answer("❌ Количество использований не может быть отрицательным.")
                return
        except ValueError:
            await message.answer("❌ Некорректный ввод. Введите целое число или 'нет'.")
            return
    user_data = await state.get_data()
    promo_id = user_data.get("editing_promo_id")
    if not promo_id:
        await message.answer("❌ Ошибка: Не найден ID промокода для обновления.")
        await state.clear()
        return
    async with AsyncSessionLocal() as session:
        updated = await update_promo_code(session, promo_id, max_uses=new_max_uses)
    if updated:
        await message.answer(f"✅ Лимит использований для `{updated.code}` обновлен.")
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Вернуться к редактированию", callback_data=f"admin_edit_promo_{promo_id}")]])
        await message.answer("Вы можете изменить другие параметры или вернуться к списку.", reply_markup=keyboard)
    else:
        await message.answer("❌ Не удалось обновить лимит промокода.")
        await state.set_state(AdminPromocodeStates.editing)


@promos_router.callback_query(F.data == "edit_promo_set_expiry", StateFilter(AdminPromocodeStates.editing))
async def edit_promo_ask_expiry_date(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminPromocodeStates.editing_expiry)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="edit_promo_cancel_field")]])
    example = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"🗓️ Введите новую дату в формате `ДД.ММ.ГГГГ` (например, `{example}`) или напишите `нет`.",
        reply_markup=keyboard,
        parse_mode="MarkdownV2",
    )


@promos_router.message(StateFilter(AdminPromocodeStates.editing_expiry))
async def edit_promo_process_expiry_date(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    expiry_input = message.text.strip().lower()
    new_expiry = None
    if expiry_input not in ["нет", "no", "none", "null"]:
        try:
            new_expiry = datetime.strptime(expiry_input, "%d.%m.%Y").replace(hour=23, minute=59, second=59)
            if new_expiry < datetime.now():
                await message.answer("❌ Дата истечения не может быть в прошлом.")
                return
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введите `ДД.ММ.ГГГГ` или 'нет'.")
            return
    user_data = await state.get_data()
    promo_id = user_data.get("editing_promo_id")
    if not promo_id:
        await message.answer("❌ Ошибка: Не найден ID промокода для обновления.")
        await state.clear()
        return
    async with AsyncSessionLocal() as session:
        updated = await update_promo_code(session, promo_id, expiry_date=new_expiry)
    if updated:
        await message.answer(f"✅ Дата окончания для `{updated.code}` обновлена.")
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Вернуться к редактированию", callback_data=f"admin_edit_promo_{promo_id}")]])
        await message.answer("Вы можете изменить другие параметры или вернуться к списку.", reply_markup=keyboard)
    else:
        await message.answer("❌ Не удалось обновить дату промокода.")
        await state.set_state(AdminPromocodeStates.editing)


@promos_router.callback_query(F.data == "edit_promo_cancel_field")
async def edit_promo_cancel_field(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] edit_promo_cancel_field by {callback.from_user.id}")
    if callback.from_user.id not in ADMIN_IDS:
        return
    user_data = await state.get_data()
    promo_id = user_data.get("editing_promo_id")
    if not promo_id:
        await callback.answer("Ошибка: Не найден ID промокода.", show_alert=True)
        await state.clear()
        callback.data = "admin_manage_promocodes_page_0"
        await admin_manage_promocodes(callback, state)
        return
    await callback.answer("Изменение отменено.")
    await admin_edit_promo_start(callback, state)


@promos_router.callback_query(F.data == "admin_add_promo")
async def admin_add_promo_start(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_add_promo_start by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    await state.set_state(AdminPromocodeStates.waiting_code)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")]])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("🆕 Введите текст нового промокода (3-50 символов, только буквы и цифры):", reply_markup=keyboard)


@promos_router.callback_query(F.data == "admin_promo_cancel")
async def admin_promo_cancel(callback: CallbackQuery, state: FSMContext):
    logger.info(f"[promos] admin_promo_cancel by {callback.from_user.id}")
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа", show_alert=True)
            return
    await state.clear()
    await callback.answer("Действие отменено.")
    callback.data = "admin_manage_promocodes_page_0"
    await admin_manage_promocodes(callback, state)


@promos_router.message(StateFilter(AdminPromocodeStates.waiting_code))
async def admin_promo_code_received(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    promo_code_text = message.text.strip().upper()
    if not promo_code_text or len(promo_code_text) < 3 or len(promo_code_text) > 50:
        await message.answer("❌ Некорректный код. Длина 3–50 символов. Попробуйте еще раз:")
        return
    async with AsyncSessionLocal() as session:
        existing = await get_promo_code_by_code(session, promo_code_text)
        if existing:
            await message.answer(f"❌ Промокод `{promo_code_text}` уже существует. Придумайте другой:")
            return
    await state.update_data(promo_code_text=promo_code_text)
    await state.set_state(AdminPromocodeStates.waiting_value)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")]])
    await message.answer(
        f"✅ Код: `{promo_code_text}`\n🔢 Теперь введите количество бонусных дней (целое число, например, `7`):",
        reply_markup=keyboard,
        parse_mode="MarkdownV2",
    )


@promos_router.message(StateFilter(AdminPromocodeStates.waiting_value))
async def admin_promo_value_received(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    try:
        days = int(message.text.strip())
        if days <= 0:
            await message.answer("❌ Количество дней должно быть положительным.")
            return
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое число.")
        return
    await state.update_data(promo_value=days)
    await state.set_state(AdminPromocodeStates.waiting_max_uses)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")]])
    await message.answer(
        "✅ Дней: `{}`\n♾️ Теперь введите максимальное количество использований (целое число, `0` или `нет` - безлимит):".format(days),
        reply_markup=keyboard,
        parse_mode="MarkdownV2",
    )


@promos_router.message(StateFilter(AdminPromocodeStates.waiting_max_uses))
async def admin_promo_max_uses_received(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    max_uses_input = message.text.strip().lower()
    max_uses = None
    if max_uses_input not in ["0", "нет", "no", "none", "null"]:
        try:
            max_uses = int(max_uses_input)
            if max_uses < 0:
                await message.answer("❌ Количество использований не может быть отрицательным.")
                return
        except ValueError:
            await message.answer("❌ Некорректный ввод. Введите целое число или 'нет'.")
            return
    await state.update_data(promo_max_uses=max_uses)
    await state.set_state(AdminPromocodeStates.waiting_expiry)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_cancel")]])
    example = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")
    await message.answer(
        f"✅ Лимит: `{max_uses if max_uses is not None else '∞'}`\n🗓️ Теперь введите дату истечения в формате `ДД.ММ.ГГГГ` (например, `{example}`) или напишите `нет`.",
        reply_markup=keyboard,
        parse_mode="MarkdownV2",
    )


@promos_router.message(StateFilter(AdminPromocodeStates.waiting_expiry))
async def admin_promo_expiry_date_received(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    expiry_input = message.text.strip().lower()
    expiry_date = None
    if expiry_input not in ["нет", "no", "none", "null"]:
        try:
            expiry_date = datetime.strptime(expiry_input, "%d.%m.%Y").replace(hour=23, minute=59, second=59)
            if expiry_date < datetime.now():
                await message.answer("❌ Дата истечения не может быть в прошлом.")
                return
        except ValueError:
            await message.answer("❌ Неверный формат даты. Введите `ДД.ММ.ГГГГ` или 'нет'.")
            return
    data = await state.get_data()
    code = data.get("promo_code_text")
    value = data.get("promo_value")
    max_uses = data.get("promo_max_uses")
    if not code or value is None:
        await message.answer("❌ Не удалось получить данные для создания промокода. Попробуйте снова.")
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")]])
        await message.answer("Возврат к списку промокодов.", reply_markup=keyboard)
        return
    try:
        async with AsyncSessionLocal() as session:
            new_promo = await create_promo_code(session, code=code, value=value, max_uses=max_uses, expiry_date=expiry_date, is_active=True, discount_type='days')
        if new_promo:
            expiry_str = expiry_date.strftime("%d.%m.%Y") if expiry_date else "бессрочный"
            max_uses_str = str(max_uses) if max_uses is not None else "∞"
            await message.answer(
                f"✅ Промокод `{new_promo.code}` успешно создан!\n\n🎁 Бонус: {new_promo.value} дн.\n♾️ Лимит: {max_uses_str}\n🗓️ До: {expiry_str}"
            )
            logger.info(f"Администратор {message.from_user.id} создал промокод: {new_promo.code}")
        else:
            await message.answer("❌ Не удалось создать промокод в базе данных.")
    except Exception as e:
        logger.error(f"Ошибка при создании промокода {code} админом {message.from_user.id}: {e}", exc_info=True)
        await message.answer(f"❌ Произошла ошибка при создании промокода: {e}")
    finally:
        await state.clear()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎟️ К списку промокодов", callback_data="admin_manage_promocodes_page_0")]])
        await message.answer("Процесс добавления завершен.", reply_markup=keyboard)