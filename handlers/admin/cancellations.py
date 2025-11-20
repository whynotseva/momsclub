from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, CallbackQuery
from aiogram.fsm.context import FSMContext
import logging

from database.config import AsyncSessionLocal
from database.crud import (
    get_cancellation_requests_stats,
    get_all_cancellation_requests,
    get_cancellation_request_by_id,
    update_cancellation_request_status,
    disable_user_auto_renewal,
    get_user_by_id,
    get_active_subscription,
    mark_cancellation_request_contacted,
    get_user_by_telegram_id,
)


logger = logging.getLogger(__name__)
from utils.constants import ADMIN_IDS
from utils.admin_permissions import is_admin
from database.crud import get_user_by_telegram_id
from utils.helpers import html_kv, fmt_date, admin_nav_back, success, error

cancellations_router = Router(name="admin_cancellations")


@cancellations_router.callback_query(F.data == "admin_cancellation_requests")
async def show_cancellation_requests_menu(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("Нет доступа", show_alert=True)
            return

    async with AsyncSessionLocal() as session:
        stats = await get_cancellation_requests_stats(session)

        text_lines = [
            "🚫 <b>Заявки на отмену автопродления</b>",
            "",
            "📊 <b>Статистика</b>",
            html_kv("Всего", str(stats['total'])),
            html_kv("⏳ Ожидают", str(stats['pending'])),
            html_kv("☎️ Связались", str(stats['contacted'])),
            html_kv("✅ Одобрены", str(stats['approved'])),
            html_kv("❌ Отклонены", str(stats['rejected'])),
            "",
            "Выберите категорию для просмотра:",
        ]
        text = "\n".join(text_lines)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏳ Ожидающие", callback_data="admin_cancel_requests_filter:pending")],
                [InlineKeyboardButton(text="☎️ Связались", callback_data="admin_cancel_requests_filter:contacted")],
                [InlineKeyboardButton(text="✅ Одобренные", callback_data="admin_cancel_requests_filter:approved")],
                [InlineKeyboardButton(text="❌ Отклоненные", callback_data="admin_cancel_requests_filter:rejected")],
                [InlineKeyboardButton(text="📜 Все", callback_data="admin_cancel_requests_filter:all")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_back")],
            ]
        )

        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()


@cancellations_router.callback_query(F.data.startswith("admin_cancel_requests_filter:"))
async def show_cancellation_requests_list(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
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
                'rejected': 'Отклоненные',
            }
            filter_name = status_names.get(filter_type, filter_type)

        text_lines = [f"🚫 <b>Заявки: {filter_name}</b>"]
        keyboard_rows = []
        for req in requests:
            user = await get_user_by_id(session, req.user_id)
            if not user:
                continue
            username = f"@{user.username}" if user.username else f"ID:{user.telegram_id}"
            date = req.created_at.strftime('%d.%m.%Y %H:%M')
            status_map = {
                'pending': '⏳', 'contacted': '☎️', 'approved': '✅', 'rejected': '❌'
            }
            status_icon = status_map.get(req.status, '❓')
            btn_text = f"{status_icon} {username} • {date}"
            keyboard_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_cancel_request_{req.id}")])

        keyboard_rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_cancellation_requests")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        text = "\n".join(text_lines)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()


@cancellations_router.callback_query(F.data.startswith("view_cancel_request_"))
async def view_cancellation_request_detail(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
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

        status_map = {
            'pending': '⏳ Ожидает',
            'contacted': '☎️ Связались',
            'approved': '✅ Одобрено',
            'rejected': '❌ Отклонено',
        }
        status_text = status_map.get(request.status, request.status)

        text_lines = [
            f"<b>📝 Заявка #{request.id}</b>",
            "",
            html_kv("👤 Пользователь", f"@{user.username or 'не указан'} (ID: {user.telegram_id})"),
            html_kv("📅 Создана", request.created_at.strftime('%d.%m.%Y %H:%M')),
            html_kv("📌 Статус", status_text),
            "",
            html_kv("Подписка активна до", active_sub.end_date.strftime('%d.%m.%Y') if active_sub else 'N/A'),
            "",
            "Действия:",
        ]
        text = "\n".join(text_lines)

        keyboard_buttons = []
        if request.status in ("pending", "contacted"):
            keyboard_buttons.append([
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_cancel_renewal_{request_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_cancel_renewal_{request_id}")
            ])
        keyboard_buttons.append([InlineKeyboardButton(text="« Назад к списку", callback_data="admin_cancellation_requests")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()


@cancellations_router.callback_query(F.data.startswith("approve_cancel_renewal_"))
async def approve_cancel_renewal(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("Нет доступа", show_alert=True)
            return

    request_id = int(callback.data.split("_")[-1])
    
    # Получаем данные в первой сессии
    async with AsyncSessionLocal() as session:
        request = await get_cancellation_request_by_id(session, request_id)
        if not request:
            await callback.answer("Заявка не найдена", show_alert=True)
            return

        # Сохраняем данные ДО закрытия сессии
        user_id = request.user_id
        
        # Получаем user отдельно чтобы избежать lazy loading
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        user_telegram_id = user.telegram_id

    # Выполняем операции во второй сессии
    async with AsyncSessionLocal() as session:
        try:
            await disable_user_auto_renewal(session, user_id)
            await update_cancellation_request_status(session, request_id, "approved")
        except Exception as e:
            logger.error(f"Ошибка одобрения заявки: {e}")
            await callback.answer("Ошибка при одобрении", show_alert=True)
            return

    # Отправляем уведомление пользователю
    try:
        from bot import bot
        await bot.send_message(
            user_telegram_id,
            "✅ <b>Ваша заявка на отмену автопродления одобрена!</b>\n\n"
            "🚫 Автопродление отключено.\n\n"
            "📌 Ваша подписка будет действовать до окончания текущего периода.\n"
            "После этого автоматическое списание производиться не будет.\n\n"
            "🤎 Спасибо, что были с нами!",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю: {e}")

    await callback.answer(success("Заявка одобрена, автопродление отключено"), show_alert=True)
    await view_cancellation_request_detail(callback)


@cancellations_router.callback_query(F.data.startswith("reject_cancel_renewal_"))
async def reject_cancel_renewal(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not is_admin(user):
            await callback.answer("Нет доступа", show_alert=True)
            return

    request_id = int(callback.data.split("_")[-1])
    
    # Получаем данные в первой сессии
    async with AsyncSessionLocal() as session:
        request = await get_cancellation_request_by_id(session, request_id)
        if not request:
            await callback.answer("Заявка не найдена", show_alert=True)
            return

        # Сохраняем данные ДО закрытия сессии
        user_id = request.user_id
        
        # Получаем user отдельно чтобы избежать lazy loading
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        user_telegram_id = user.telegram_id

    # Выполняем операции во второй сессии
    async with AsyncSessionLocal() as session:
        try:
            await update_cancellation_request_status(session, request_id, "rejected")
        except Exception as e:
            logger.error(f"Ошибка отклонения заявки: {e}")
            await callback.answer(error("Ошибка при отклонении"), show_alert=True)
            return

    # Отправляем уведомление пользователю
    try:
        from bot import bot
        await bot.send_message(
            user_telegram_id,
            "❌ <b>Ваша заявка на отмену автопродления отклонена</b>\n\n"
            "🔄 Автопродление остается активным.\n\n"
            "💬 Если у вас есть вопросы, обратитесь в службу поддержки.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю: {e}")

    await callback.answer(error("Заявка отклонена"), show_alert=True)
    await view_cancellation_request_detail(callback)


@cancellations_router.callback_query(F.data == "admin_pending_cancellations")
async def legacy_pending_cancellations(callback: CallbackQuery):
    # Перенаправление со старого колбэка
    await show_cancellation_requests_menu(callback)


@cancellations_router.message(Command("contacted_cancel"), F.chat.type == "private")
async def cmd_contacted_cancel(message: types.Message):
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
        try:
            await mark_cancellation_request_contacted(session, request_id)
            await message.answer(f"✅ Заявка #{request_id} отмечена как 'связались'")
        except Exception as e:
            logger.error(f"Ошибка отметки contacted: {e}")
            await message.answer("❌ Не удалось отметить заявку")


def register_admin_cancellations_handlers(dp):
    dp.include_router(cancellations_router)
    logger.info("[cancellations] Админ-обработчики заявок на отмену автопродления зарегистрированы")