from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from utils.constants import ADMIN_IDS
from utils.admin_permissions import is_admin
from database.crud import get_user_by_telegram_id
from utils.helpers import html_kv
from database.config import AsyncSessionLocal
from database.crud import get_users_with_birthdays, get_active_subscription
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

birthdays_router = Router()


class AdminBirthdayStates(StatesGroup):
    viewing_page = State()


def register_admin_birthdays_handlers(dp):
    dp.include_router(birthdays_router)


@birthdays_router.callback_query(F.data.startswith("admin_birthdays"))
async def process_user_birthdays(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    logger.info(f"[birthdays] admin_birthdays {callback.data}")
    parts = callback.data.split(":")
    try:
        page = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        page = 0

    if page < 0:
        page = 0

    await callback.answer("Загрузка данных о днях рождения...")
    await state.set_state(AdminBirthdayStates.viewing_page)
    await state.update_data(current_page=page)

    async with AsyncSessionLocal() as session:
        users_with_birthdays = await get_users_with_birthdays(session)
        today = datetime.now().date()
        current_month_day = today.strftime('%m-%d')

        users_with_days = []
        for user in users_with_birthdays:
            if not getattr(user, 'birthday', None):
                continue
            birthday_md = user.birthday.strftime('%m-%d')
            if birthday_md < current_month_day:
                next_birthday = datetime(today.year + 1, user.birthday.month, user.birthday.day).date()
            else:
                next_birthday = datetime(today.year, user.birthday.month, user.birthday.day).date()
            days_until = (next_birthday - today).days
            active_sub = await get_active_subscription(session, user.id)
            users_with_days.append((user, days_until, birthday_md, bool(active_sub)))

        users_with_days.sort(key=lambda x: x[1])

        PAGE_SIZE = 10
        total_items = len(users_with_days)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
        if page >= total_pages:
            page = total_pages - 1
        start = page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total_items)
        current_items = users_with_days[start:end]

        if not current_items:
            text = "<b>🎂 Дни рождения пользователей:</b>\n\nПользователей с указанной датой рождения не найдено."
        else:
            lines = ["<b>🎂 Дни рождения пользователей</b>", ""]
            for i, (user, days_left, birthday_md, has_active_sub) in enumerate(current_items, 1):
                name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                if user.username:
                    name = f"{name} (@{user.username})".strip()
                if not name:
                    name = f"ID: {user.telegram_id}"
                status = "✅ " if has_active_sub else "❌ "
                bdate = user.birthday.strftime("%d.%m.%Y")
                lines.append(f"{status}{start + i}. <b>{name}</b>")
                lines.append(html_kv("📅 Дата рождения", bdate))
                if days_left == 0:
                    lines.append("    🎉 <b>День рождения сегодня!</b>\n")
                elif days_left == 1:
                    lines.append("    ⏱ <b>День рождения завтра!</b>\n")
                else:
                    lines.append(f"    ⏱ <b>Дней до дня рождения:</b> {days_left}\n")
            text = "\n".join(lines)

        kb_rows = []
        pag_row = []
        if page > 0:
            pag_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_birthdays:{page-1}"))
        if page < total_pages - 1:
            pag_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_birthdays:{page+1}"))
        if pag_row:
            kb_rows.append(pag_row)
        if total_pages > 1:
            kb_rows.append([InlineKeyboardButton(text=f"Страница {page+1}/{total_pages}", callback_data="ignore")])
        kb_rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_birthdays:{page}")])
        kb_rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_back")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")