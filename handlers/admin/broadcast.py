from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from utils.constants import ADMIN_IDS
from utils.admin_permissions import can_manage_admins
from database.crud import get_user_by_telegram_id
from database.config import AsyncSessionLocal
from database.crud import (
    get_total_users_count,
    get_active_subscriptions_count,
    get_users_with_active_subscriptions,
    get_user_by_telegram_id,
)
from database.models import User
from sqlalchemy import select
import logging
import asyncio

logger = logging.getLogger(__name__)

broadcast_router = Router()


class BroadcastStates(StatesGroup):
    broadcast_text = State()
    broadcast_media = State()
    broadcast_confirm = State()
    broadcast_error_page = State()


def register_admin_broadcast_handlers(dp):
    dp.include_router(broadcast_router)


@broadcast_router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return

    await state.update_data(broadcast_format="HTML")
    await state.set_state(BroadcastStates.broadcast_text)

    format_example = "/текст/ - жирный\n&текст& - курсив\n_текст_ - подчеркнутый\n~текст~ - зачеркнутый\n№текст№ - моноширинный\n»текст« - цитата\n```\nмногострочный код\n```"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]])

    try:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "📝 <b>Введите текст рассылки</b>\n\n"
            "<b>Формат:</b> Упрощенное форматирование\n\n"
            f"<b>Используйте эти символы для форматирования:</b>\n<code>{format_example}</code>\n\n"
            "💡 <b>Совет:</b> Система автоматически преобразует ваши символы в HTML-форматирование.\n"
            "Вам не нужно беспокоиться о специальных символах HTML.\n\n"
            "Отправьте текст для рассылки:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске рассылки: {e}")
        await callback.message.answer("Отправьте текст для рассылки:", reply_markup=keyboard)
    await callback.answer()


def convert_custom_to_html(text: str) -> str:
    import re
    try:
        text = text.replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r"/([^/]+)/", r"<b>\\1</b>", text)
        text = re.sub(r"&([^&]+)&", r"<i>\\1</i>", text)
        text = re.sub(r"_([^_]+)_", r"<u>\\1</u>", text)
        text = re.sub(r"~([^~]+)~", r"<s>\\1</s>", text)
        text = re.sub(r"№([^№]+)№", r"<code>\\1</code>", text)
        text = re.sub(r"»([^«]+)«", r"<blockquote>\\1</blockquote>", text)
        text = re.sub(r"```(.*?)```", r"<pre>\\1</pre>", text, 0, re.DOTALL)
        if len(text) > 4096:
            text = text[:4090] + "..."
        return text
    except Exception as e:
        logger.error(f"Ошибка форматирования: {e}")
        safe = text.replace("<", "&lt;").replace(">", "&gt;")
        return f"<b>Ошибка форматирования</b>: {safe}"


@broadcast_router.message(StateFilter(BroadcastStates.broadcast_text))
async def admin_broadcast_text_received(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    try:
        original = message.text
        converted = convert_custom_to_html(original)
        await state.update_data(broadcast_text=converted, broadcast_format="HTML")

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📷 Изображение", callback_data="admin_broadcast_add_photo"), InlineKeyboardButton(text="🎥 Видео", callback_data="admin_broadcast_add_video")],
                [InlineKeyboardButton(text="⭕ Видео-кружок", callback_data="admin_broadcast_add_videocircle"), InlineKeyboardButton(text="📄 Только текст", callback_data="admin_broadcast_text_only")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_text")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")],
            ]
        )

        preview = await message.answer("⏳ Генерирую предпросмотр сообщения...")
        try:
            await preview.edit_text(converted, parse_mode="HTML")
        except Exception as edit_error:
            safe = original.replace("<", "&lt;").replace(">", "&gt;")
            await preview.edit_text(
                f"⚠️ Ошибка форматирования: {str(edit_error)}\n\nИсходный текст:\n{safe[:3000]}",
                parse_mode="HTML",
            )
        await message.answer("👍 Текст сохранен. Теперь выберите тип медиа-вложения или отправьте только текст:", reply_markup=keyboard)
        await state.set_state(BroadcastStates.broadcast_media)
    except Exception as e:
        logger.error(f"Ошибка в admin_broadcast_text_received: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте снова.")


@broadcast_router.callback_query(F.data == "admin_broadcast_back_to_text")
async def admin_broadcast_back_to_text(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.set_state(BroadcastStates.broadcast_text)
    format_example = "/текст/ - жирный\n&текст& - курсив\n_текст_ - подчеркнутый\n~текст~ - зачеркнутый\n№текст№ - моноширинный\n»текст« - цитата\n```\nмногострочный код\n```"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]])
    await callback.message.edit_text(
        "📝 <b>Введите текст рассылки</b>\n\n"
        "<b>Формат:</b> Упрощенное форматирование\n\n"
        f"<b>Используйте эти символы для форматирования:</b>\n<code>{format_example}</code>\n\n"
        "💡 <b>Совет:</b> Система автоматически преобразует ваши символы в корректный формат.\n"
        "Отправьте текст для рассылки:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@broadcast_router.callback_query(F.data == "admin_broadcast_add_photo")
async def admin_broadcast_add_photo(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.update_data(broadcast_media_type="photo")
    await callback.message.edit_text(
        "📷 <b>Отправьте изображение</b> для рассылки.\n\nОтправьте изображение как фото (не как файл).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_media")],[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]]),
    )
    await callback.answer()


@broadcast_router.callback_query(F.data == "admin_broadcast_add_video")
async def admin_broadcast_add_video(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.update_data(broadcast_media_type="video")
    await callback.message.edit_text(
        "🎥 <b>Отправьте видео</b> для рассылки.\n\nОтправьте видео (не как файл).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_media")],[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]]),
    )
    await callback.answer()


@broadcast_router.callback_query(F.data == "admin_broadcast_add_videocircle")
async def admin_broadcast_add_videocircle(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.update_data(broadcast_media_type="videocircle")
    await callback.message.edit_text(
        "⭕ <b>Отправьте видео для видео-сообщения</b> (кружок).\n\n"
        "Требования: квадратное видео, до 60 секунд, до 8 МБ.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_media")],[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]]),
    )
    await callback.answer()


@broadcast_router.callback_query(F.data == "admin_broadcast_back_to_media")
async def admin_broadcast_back_to_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📷 Изображение", callback_data="admin_broadcast_add_photo"), InlineKeyboardButton(text="🎥 Видео", callback_data="admin_broadcast_add_video")],
            [InlineKeyboardButton(text="⭕ Видео-кружок", callback_data="admin_broadcast_add_videocircle"), InlineKeyboardButton(text="📄 Только текст", callback_data="admin_broadcast_text_only")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_broadcast_back_to_text")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")],
        ]
    )
    await callback.message.edit_text("Выберите тип медиа-вложения или отправьте только текст:", reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@broadcast_router.message(StateFilter(BroadcastStates.broadcast_media), F.photo | F.video | F.video_note | F.document)
async def admin_broadcast_media_received(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not can_manage_admins(user):
            return
    user_data = await state.get_data()
    media_type = user_data.get("broadcast_media_type")
    file_id = None
    received_type = None
    if message.photo:
        received_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        received_type = "video"
        file_id = message.video.file_id
    elif message.video_note:
        received_type = "videocircle"
        file_id = message.video_note.file_id
    elif message.document:
        await message.answer("❌ Пожалуйста, отправьте медиа как фото, видео или кружок (не как файл).")
        return
    if media_type and received_type != media_type:
        type_mapping = {"photo": "изображение (фото)", "video": "видео", "videocircle": "видео-сообщение (кружок)"}
        await message.answer(
            f"❌ Вы выбрали тип '{type_mapping.get(media_type)}', но отправили '{type_mapping.get(received_type)}'.\n\nПожалуйста, отправьте {type_mapping.get(media_type)}."
        )
        return
    await state.update_data(broadcast_media_file_id=file_id, broadcast_media_type=received_type)
    await show_broadcast_preview(message, state)


@broadcast_router.callback_query(F.data == "admin_broadcast_text_only")
async def admin_broadcast_text_only(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа", show_alert=True)
        return
    await state.update_data(broadcast_media_type=None, broadcast_media_file_id=None)
    await callback.answer()
    await show_broadcast_preview(callback.message, state)


async def show_broadcast_preview(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    broadcast_text = user_data.get("broadcast_text", "")
    broadcast_format = user_data.get("broadcast_format", "HTML")
    media_type = user_data.get("broadcast_media_type")
    file_id = user_data.get("broadcast_media_file_id")
    await state.set_state(BroadcastStates.broadcast_confirm)
    preview_message = await message.answer("⏳ Подготовка предпросмотра...")
    try:
        if media_type == "photo" and file_id:
            await message.bot.send_photo(chat_id=message.chat.id, photo=file_id, caption=broadcast_text, parse_mode=broadcast_format)
        elif media_type == "video" and file_id:
            await message.bot.send_video(chat_id=message.chat.id, video=file_id, caption=broadcast_text, parse_mode=broadcast_format)
        elif media_type == "videocircle" and file_id:
            await message.bot.send_video_note(chat_id=message.chat.id, video_note=file_id)
            if broadcast_text:
                await message.bot.send_message(chat_id=message.chat.id, text=broadcast_text, parse_mode=broadcast_format)
        else:
            await message.bot.send_message(chat_id=message.chat.id, text=broadcast_text, parse_mode=broadcast_format)
        await preview_message.delete()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data="admin_broadcast_confirm"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")],[InlineKeyboardButton(text="🔄 Изменить текст", callback_data="admin_broadcast_back_to_text"), InlineKeyboardButton(text="📎 Изменить медиа", callback_data="admin_broadcast_back_to_media")]])
        async with AsyncSessionLocal() as session:
            total_users = await get_total_users_count(session)
            active_subs = await get_active_subscriptions_count(session)
        await message.answer(
            "📣 <b>Предпросмотр рассылки</b>\n\n"
            f"<b>Тип:</b> {'Только текст' if not media_type else f'{media_type} + текст'}\n"
            f"<b>Формат:</b> {broadcast_format}\n"
            f"<b>Целевая аудитория:</b> {'Все пользователи' if media_type != 'videocircle' else 'Пользователи с активными подписками'}\n\n"
            f"<b>Получатели:</b> {total_users if media_type != 'videocircle' else active_subs} пользователей\n\n"
            "Подтвердите отправку рассылки:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"Ошибка при создании предпросмотра: {e}")
        await preview_message.edit_text(
            f"❌ <b>Ошибка:</b> {str(e)}\n\nВернитесь назад и измените сообщение.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Изменить текст", callback_data="admin_broadcast_back_to_text"), InlineKeyboardButton(text="📎 Изменить медиа", callback_data="admin_broadcast_back_to_media")],[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]]),
            parse_mode="HTML",
        )


@broadcast_router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_broadcast_confirm_send(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    await callback.answer("🚀 Начинаем рассылку...")
    status_message = await callback.message.edit_text(
        "⏳ <b>Рассылка запущена</b>\n\nНачинаем отправку сообщений...\nСтатус: 0% (0/0)\n\nЭто может занять некоторое время. Пожалуйста, дождитесь завершения.",
        parse_mode="HTML",
    )
    user_data = await state.get_data()
    broadcast_text = user_data.get("broadcast_text", "")
    broadcast_format = user_data.get("broadcast_format", "HTML")
    media_type = user_data.get("broadcast_media_type")
    file_id = user_data.get("broadcast_media_file_id")
    successful, failed = [], []
    async with AsyncSessionLocal() as session:
        if media_type == "videocircle":
            users_data = await get_users_with_active_subscriptions(session)
            users = [u for u, _ in users_data]
        else:
            result = await session.execute(select(User))
            users = result.scalars().all()
    total_users = len(users)
    for i, user in enumerate(users):
        try:
            if not user.telegram_id:
                continue
            if media_type == "photo" and file_id:
                await callback.bot.send_photo(chat_id=user.telegram_id, photo=file_id, caption=broadcast_text, parse_mode=broadcast_format)
            elif media_type == "video" and file_id:
                await callback.bot.send_video(chat_id=user.telegram_id, video=file_id, caption=broadcast_text, parse_mode=broadcast_format)
            elif media_type == "videocircle" and file_id:
                await callback.bot.send_video_note(chat_id=user.telegram_id, video_note=file_id)
                if broadcast_text:
                    await callback.bot.send_message(chat_id=user.telegram_id, text=broadcast_text, parse_mode=broadcast_format)
            else:
                await callback.bot.send_message(chat_id=user.telegram_id, text=broadcast_text, parse_mode=broadcast_format)
            successful.append(user.telegram_id)
        except Exception as e:
            logger.error(f"Ошибка при отправке пользователю {user.telegram_id}: {e}")
            failed.append((user.telegram_id, str(e)))
        if (i + 1) % 10 == 0 or i == total_users - 1:
            progress = (i + 1) / total_users * 100 if total_users else 100
            try:
                await status_message.edit_text(
                    f"⏳ <b>Рассылка в процессе</b>\n\nОтправлено: {i + 1}/{total_users} ({progress:.1f}%)\nУспешно: {len(successful)}\nОшибок: {len(failed)}\n\nПожалуйста, дождитесь завершения.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Ошибка при обновлении статуса: {e}")
        await asyncio.sleep(0.1)
    success_rate = len(successful) / total_users * 100 if total_users > 0 else 0
    report_header = (
        "✅ <b>Рассылка завершена</b>\n\n"
        f"<b>Всего получателей:</b> {total_users}\n"
        f"<b>Успешно отправлено:</b> {len(successful)} ({success_rate:.1f}%)\n"
        f"<b>Ошибок:</b> {len(failed)}\n\n"
    )
    if failed:
        user_info = {}
        all_errors_info = []
        async with AsyncSessionLocal() as session:
            for user_id, error in failed:
                user = await get_user_by_telegram_id(session, user_id)
                if user:
                    display_name = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip() or f"ID {user_id}"
                    user_link = f"<a href=\"tg://user?id={user_id}\">{display_name}</a>"
                    user_info[user_id] = user_link
                else:
                    user_info[user_id] = f"ID {user_id}"
                if "bot was blocked" in error:
                    error = "Пользователь заблокировал бота"
                elif "chat not found" in error:
                    error = "Чат не найден"
                elif "user is deactivated" in error:
                    error = "Аккаунт пользователя деактивирован"
                all_errors_info.append((user_id, error))
        await state.set_state(BroadcastStates.broadcast_error_page)
        await state.update_data(errors=all_errors_info, user_info=user_info, current_page=0, report_header=report_header, successful=successful, success_rate=success_rate, total_users=total_users)
        await show_broadcast_errors_page(callback.message, all_errors_info, user_info, 0, state)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Вернуться в меню", callback_data="admin_back")]])
        await status_message.edit_text(report_header, reply_markup=keyboard, parse_mode="HTML")
        await state.clear()


async def show_broadcast_errors_page(message: types.Message, all_errors, user_info, page: int, state: FSMContext):
    ERRORS_PER_PAGE = 10
    total_errors = len(all_errors)
    total_pages = (total_errors + ERRORS_PER_PAGE - 1) // ERRORS_PER_PAGE
    start_idx = page * ERRORS_PER_PAGE
    end_idx = min(start_idx + ERRORS_PER_PAGE, total_errors)
    state_data = await state.get_data()
    report = state_data.get("report_header", "")
    report += f"<b>Ошибки при отправке (стр. {page+1}/{total_pages}):</b>\n"
    for i, (user_id, error) in enumerate(all_errors[start_idx:end_idx]):
        report += f"{start_idx+i+1}. {user_info.get(user_id, f'ID {user_id}')}: {error}\n"
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"broadcast_errors_page:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"broadcast_errors_page:{page+1}"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="« Вернуться в меню", callback_data="admin_back")]])
    try:
        await message.edit_text(report, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка при обновлении сообщения: {e}")
            raise


@broadcast_router.callback_query(F.data.startswith("broadcast_errors_page:"))
async def process_broadcast_errors_page(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not can_manage_admins(user):
            await callback.answer("У вас нет доступа к этой функции", show_alert=True)
            return
    page_data = callback.data.split(":")
    try:
        page = int(page_data[1]) if len(page_data) > 1 else 0
    except (ValueError, IndexError):
        page = 0
    await callback.answer()
    user_data = await state.get_data()
    all_errors = user_data.get("errors", [])
    user_info = user_data.get("user_info", {})
    total_pages = (len(all_errors) + 10 - 1) // 10
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    await state.update_data(current_page=page)
    await show_broadcast_errors_page(callback.message, all_errors, user_info, page, state)