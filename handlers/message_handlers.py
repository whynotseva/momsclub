"""
Обработчики для управления сообщениями, шаблонами и рассылкой в админ-панели
"""

import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Router, types, F, Bot
from aiogram.filters import StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, Message
)
from sqlalchemy import select

from database.config import AsyncSessionLocal
from database.crud import (
    create_message_template, get_message_templates, get_message_template_by_id,
    update_message_template, delete_message_template, create_scheduled_message,
    add_scheduled_message_recipient, mark_scheduled_message_as_sent,
    get_all_scheduled_messages, get_scheduled_message_by_id, delete_scheduled_message,
    get_unsent_recipients, update_recipient_status,
    get_user_by_telegram_id, get_user_by_id, get_user_by_username,
    get_users_with_active_subscriptions, get_all_users_with_subscriptions,
    update_group_activity
)
from utils.constants import ADMIN_IDS, CLUB_GROUP_ID
from utils.helpers import safe_edit_message
import re

# Настройка логирования
logger = logging.getLogger(__name__)
message_logger = logging.getLogger("messages")

# Создание маршрутизатора для обработчиков сообщений
message_router = Router()


# Обработчик сообщений из группы - только для учёта активности
# Бот НЕ контролирует общение - участницы могут свободно общаться
# Бот молча обновляет счётчик активности в БД (без сообщений)

@message_router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: types.Message):
    """
    Обработчик сообщений из группы для отслеживания активности пользователей.
    Молча обновляет активность без вмешательства в общение.
    """
    try:
        logger.info(f"📨 Сообщение в чате {message.chat.id} (тип: {message.chat.type}) от {message.from_user.id} (@{message.from_user.username})")
        
        # Проверяем что это нужная группа
        if message.chat.id != CLUB_GROUP_ID:
            logger.info(f"⏭️ Пропущено - другая группа (нужна {CLUB_GROUP_ID}, получена {message.chat.id})")
            return
        
        # Пропускаем сообщения от ботов
        if message.from_user.is_bot:
            logger.info(f"⏭️ Пропущено - это бот")
            return
        
        # Обновляем активность пользователя в БД
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, message.from_user.id)
            if user:
                # Синхронизируем username если изменился
                if user.username != message.from_user.username:
                    user.username = message.from_user.username
                    logger.info(f"🔄 Обновлён username: @{message.from_user.username}")
                
                # Обновляем общую активность
                await update_group_activity(session, user.id)
                
                # Обновляем детальный лог активности по дням
                from database.crud import update_group_activity_log
                await update_group_activity_log(session, user.id)
                
                await session.commit()
                logger.info(f"✅ Обновлена активность пользователя {user.id} (@{user.username}) в группе")
            else:
                logger.warning(f"⚠️ Пользователь {message.from_user.id} (@{message.from_user.username}) не найден в БД")
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении активности в группе: {e}", exc_info=True)


# Состояния для FSM (конечного автомата)
class MessageStates(StatesGroup):
    # Состояния для индивидуальных сообщений
    direct_message_user_id = State()        # Ожидание ввода ID пользователя
    direct_message_text = State()           # Ввод текста сообщения
    direct_message_media = State()          # Прикрепление медиа (опционально)
    direct_message_confirm = State()        # Подтверждение отправки
    
    # Состояния для шаблонов сообщений
    template_management = State()           # Управление шаблонами
    create_template_name = State()          # Ввод названия шаблона
    create_template_text = State()          # Ввод текста шаблона
    create_template_media = State()         # Прикрепление медиа к шаблону
    edit_template = State()                 # Редактирование шаблона
    
    # Состояния для множественной отправки сообщений
    select_recipients = State()             # Выбор получателей
    confirm_multiple_send = State()         # Подтверждение отправки нескольким получателям
    
    # Состояния для планирования сообщений
    schedule_message_date = State()         # Выбор даты отправки
    schedule_message_time = State()         # Выбор времени отправки
    schedule_message_confirm = State()      # Подтверждение планирования

# Функция для преобразования пользовательского синтаксиса в HTML (взята из admin_handlers.py)
def convert_custom_to_html(text):
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

# ------------------ ИНДИВИДУАЛЬНЫЕ СООБЩЕНИЯ ------------------

@message_router.callback_query(F.data == "admin_direct_message_DISABLED")
async def process_admin_direct_message(callback: CallbackQuery, state: FSMContext):
    """Обработчик для начала процесса отправки индивидуального сообщения пользователю"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(MessageStates.direct_message_user_id)
    
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
            "Введите Telegram ID или Username пользователя, которому хотите отправить сообщение:\n"
            "(ID должен быть числом, username - с символом @)",
            reply_markup=keyboard
        )
    except Exception as e:
        # Если не можем удалить, просто отправляем новое сообщение
        logger.error(f"Ошибка при удалении сообщения: {e}")
        await callback.message.answer(
            "Введите Telegram ID или Username пользователя, которому хотите отправить сообщение:\n"
            "(ID должен быть числом, username - с символом @)",
            reply_markup=keyboard
        )
    
    await callback.answer()

@message_router.callback_query(F.data.startswith("admin_message_to_DISABLED:"))
async def process_admin_message_to(callback: CallbackQuery, state: FSMContext):
    """Обработчик для начала отправки сообщения конкретному пользователю"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID пользователя из callback_data
    telegram_id = int(callback.data.split(":")[1])
    
    # Сохраняем ID пользователя в состоянии
    await state.update_data(direct_message_user_id=telegram_id)
    
    # Запрашиваем текст сообщения
    await state.set_state(MessageStates.direct_message_text)
    
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
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    await safe_edit_message(
        callback,
        f"📝 <b>Введите текст сообщения для пользователя</b>\n\n"
        f"<b>Используйте эти символы для форматирования:</b>\n"
        f"<code>{format_example}</code>\n\n"
        f"Отправьте текст сообщения:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

@message_router.message(StateFilter(MessageStates.direct_message_user_id))
async def process_direct_message_user_id(message: types.Message, state: FSMContext):
    """Обработчик ввода ID пользователя для отправки сообщения"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    search_term = message.text.strip()
    
    async with AsyncSessionLocal() as session:
        user = None
        
        # Определяем, это ID или username
        if search_term.startswith("@"):
            # Поиск по username (убираем @ в начале)
            username = search_term[1:]
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
            # Сохраняем ID пользователя в состоянии
            await state.update_data(direct_message_user_id=user.telegram_id)
            
            # Получаем данные шаблона из состояния
            user_data = await state.get_data()
            template_text = user_data.get("template_text")
            
            # Если используется шаблон, предзаполняем текстом из шаблона
            if template_text:
                # Сохраняем текст как HTML (поскольку так хранится в базе)
                await state.update_data(direct_message_text=template_text, direct_message_format="HTML")
                
                # Формируем информацию о пользователе
                user_info = f"""
<b>👤 Отправка сообщения пользователю:</b>

<b>ID в базе:</b> {user.id}
<b>Telegram ID:</b> {user.telegram_id}
<b>Username:</b> {user.username or "Не указан"}
<b>Имя:</b> {user.first_name or "Не указано"}
<b>Фамилия:</b> {user.last_name or "Не указана"}

<b>Текст из шаблона:</b>
{template_text}
"""
                
                # Запрашиваем медиа или подтверждение отправки
                await state.set_state(MessageStates.direct_message_media)
                
                # Клавиатура для выбора типа медиа
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="Фото", callback_data="direct_message_media:photo"),
                            InlineKeyboardButton(text="Видео", callback_data="direct_message_media:video")
                        ],
                        [
                            InlineKeyboardButton(text="Видео-кружок", callback_data="direct_message_media:videocircle"),
                            InlineKeyboardButton(text="Только текст", callback_data="direct_message_media:text_only")
                        ],
                        [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
                    ]
                )
                
                await message.answer(
                    user_info,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                # Если шаблон не используется, идем стандартным путем
                # Формируем информацию о пользователе
                user_info = f"""
<b>👤 Отправка сообщения пользователю:</b>

<b>ID в базе:</b> {user.id}
<b>Telegram ID:</b> {user.telegram_id}
<b>Username:</b> {user.username or "Не указан"}
<b>Имя:</b> {user.first_name or "Не указано"}
<b>Фамилия:</b> {user.last_name or "Не указана"}
"""
                
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
                
                # Кнопка отмены
                keyboard = InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")
                
                await state.set_state(MessageStates.direct_message_text)
                await message.answer(
                    f"{user_info}\n"
                    f"📝 <b>Введите текст сообщения для пользователя</b>\n\n"
                    f"<b>Используйте эти символы для форматирования:</b>\n"
                    f"<code>{format_example}</code>\n\n"
                    f"Отправьте текст сообщения:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[keyboard]]),
                    parse_mode="HTML"
                )
        else:
            await message.answer(f"❌ Пользователь '{search_term}' не найден.")

@message_router.message(StateFilter(MessageStates.direct_message_text))
async def process_direct_message_text(message: types.Message, state: FSMContext):
    """Обработчик ввода текста сообщения"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Преобразуем пользовательский синтаксис в HTML
    original_text = message.text
    converted_text = convert_custom_to_html(original_text)
    
    # Сохраняем преобразованный текст в состоянии
    await state.update_data(direct_message_text=converted_text, direct_message_format="HTML")
    
    # Отправляем предпросмотр сообщения с форматированием
    preview_message = await message.answer("⏳ Генерирую предпросмотр сообщения...")
    
    try:
        # Отправляем предпросмотр отформатированного текста
        await preview_message.edit_text(
            converted_text,
            parse_mode="HTML"
        )
    except Exception as edit_error:
        logger.error(f"Ошибка при редактировании предпросмотра: {edit_error}", exc_info=True)
        
        # При ошибке показываем текст без форматирования
        safe_text = original_text.replace("<", "&lt;").replace(">", "&gt;")
        await preview_message.edit_text(
            f"⚠️ Ошибка при форматировании текста: {str(edit_error)}\n\n"
            f"Исходный текст (без форматирования):\n{safe_text[:3000]}",
            parse_mode="HTML"
        )
    
    # Запрашиваем, нужно ли добавить медиа
    await state.set_state(MessageStates.direct_message_media)
    
    # Клавиатура для выбора типа медиа
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Фото", callback_data="direct_message_media:photo"),
                InlineKeyboardButton(text="Видео", callback_data="direct_message_media:video")
            ],
            [
                InlineKeyboardButton(text="Видео-кружок", callback_data="direct_message_media:videocircle"),
                InlineKeyboardButton(text="Только текст", callback_data="direct_message_media:text_only")
            ],
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")]
        ]
    )
    
    await message.answer(
        "👍 Текст сохранен. Хотите добавить медиафайл к сообщению?\n"
        "Выберите тип медиа или отправьте только текст:",
        reply_markup=keyboard
    )

@message_router.callback_query(F.data.startswith("direct_message_media:"))
async def process_direct_message_media_type(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора типа медиа"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем выбранный тип медиа
    media_type = callback.data.split(":")[1]
    
    # Сохраняем тип медиа в состоянии
    await state.update_data(direct_message_media_type=media_type)
    
    if media_type == "text_only":
        # Если выбран только текст, переходим к подтверждению
        await process_direct_message_confirm(callback, state)
    else:
        # Запрашиваем медиафайл
        await state.set_state(MessageStates.direct_message_media)
        
        # Кнопка отмены
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data="admin_cancel")],
                [InlineKeyboardButton(text="Без медиа", callback_data="direct_message_media:text_only")]
            ]
        )
        
        media_description = {
            "photo": "фотографию",
            "video": "видео",
            "videocircle": "видео для кружка"
        }
        
        await safe_edit_message(
            callback,
            f"Отправьте {media_description.get(media_type, 'медиафайл')}:",
            reply_markup=keyboard
        )
    
    await callback.answer()

@message_router.message(StateFilter(MessageStates.direct_message_media), F.content_type.in_({"photo", "video", "video_note"}))
async def process_direct_message_media_file(message: types.Message, state: FSMContext):
    """Обработчик получения медиафайла"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    media_type = data.get("direct_message_media_type")
    
    # Проверяем соответствие типа файла
    if media_type == "photo" and not message.photo:
        await message.answer("❌ Пожалуйста, отправьте фотографию или выберите другой тип медиа.")
        return
    elif media_type == "video" and not message.video:
        await message.answer("❌ Пожалуйста, отправьте видео или выберите другой тип медиа.")
        return
    elif media_type == "videocircle" and not message.video_note:
        await message.answer("❌ Пожалуйста, отправьте видео-кружок или выберите другой тип медиа.")
        return
    
    # Получаем file_id в зависимости от типа медиа
    if media_type == "photo":
        file_id = message.photo[-1].file_id  # Берем последнюю (самую большую) фотографию
    elif media_type == "video":
        file_id = message.video.file_id
    elif media_type == "videocircle":
        file_id = message.video_note.file_id
    else:
        file_id = None
    
    # Сохраняем file_id в состоянии
    await state.update_data(direct_message_media_file_id=file_id)
    
    # Переходим к подтверждению
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="direct_message_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")
            ]
        ]
    )
    
    # Формируем предпросмотр сообщения
    user_data = await state.get_data()
    user_id = user_data.get("direct_message_user_id")
    message_text = user_data.get("direct_message_text", "")
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, user_id)
        user_display = f"@{user.username}" if user and user.username else f"ID {user_id}"
    
    preview_text = f"""
<b>Предпросмотр сообщения:</b>

<b>Получатель:</b> {user_display}
<b>Тип медиа:</b> {media_type}

<b>Текст сообщения:</b>
{message_text}

Медиафайл успешно прикреплен.
"""
    
    await message.answer(preview_text, reply_markup=keyboard, parse_mode="HTML")
    
    # Переходим к состоянию подтверждения
    await state.set_state(MessageStates.direct_message_confirm)

async def process_direct_message_confirm(callback: CallbackQuery, state: FSMContext):
    """Обработчик подтверждения отправки сообщения"""
    # Получаем все данные из состояния
    user_data = await state.get_data()
    user_id = user_data.get("direct_message_user_id")
    message_text = user_data.get("direct_message_text", "")
    media_type = user_data.get("direct_message_media_type", "text_only")
    file_id = user_data.get("direct_message_media_file_id")
    
    # Получаем информацию о пользователе для предпросмотра
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, user_id)
        user_display = f"@{user.username}" if user and user.username else f"ID {user_id}"
    
    # Подготавливаем предпросмотр текста
    preview_text = f"""
<b>Предпросмотр сообщения:</b>

<b>Получатель:</b> {user_display}
<b>Тип медиа:</b> {media_type if media_type != "text_only" else "Только текст"}

<b>Текст сообщения:</b>
{message_text}
"""
    
    # Клавиатура для подтверждения отправки
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="direct_message_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")
            ]
        ]
    )
    
    # Отправляем предпросмотр и запрос подтверждения
    await safe_edit_message(
        callback,
        preview_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(MessageStates.direct_message_confirm)

@message_router.callback_query(F.data == "direct_message_confirm")
async def send_direct_message(callback: CallbackQuery, state: FSMContext):
    """Отправка индивидуального сообщения пользователю"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Отвечаем на колбэк
    await callback.answer("Отправляем сообщение...", show_alert=False)
    
    # Получаем все данные из состояния
    user_data = await state.get_data()
    user_id = user_data.get("direct_message_user_id")
    message_text = user_data.get("direct_message_text", "")
    media_type = user_data.get("direct_message_media_type", "text_only")
    file_id = user_data.get("direct_message_media_file_id")
    
    # Всегда используем HTML-формат (т.к. преобразовали текст)
    parse_mode = "HTML"
    
    try:
        # Отправляем сообщение в зависимости от типа медиа
        if media_type == "photo" and file_id:
            await callback.bot.send_photo(
                chat_id=user_id,
                photo=file_id,
                caption=message_text,
                parse_mode=parse_mode
            )
        elif media_type == "video" and file_id:
            await callback.bot.send_video(
                chat_id=user_id,
                video=file_id,
                caption=message_text,
                parse_mode=parse_mode
            )
        elif media_type == "videocircle" and file_id:
            # Для видео-кружка текст отправляем отдельно
            await callback.bot.send_video_note(
                chat_id=user_id,
                video_note=file_id
            )
            if message_text:
                await callback.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode=parse_mode
                )
        else:
            # Только текст
            await callback.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode=parse_mode
            )
        
        # Сообщаем об успешной отправке
        await safe_edit_message(
            callback,
            f"✅ Сообщение успешно отправлено пользователю ID {user_id}!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад к админ-панели", callback_data="admin_back")]
                ]
            )
        )
        
    except Exception as e:
        # Если произошла ошибка при отправке
        error_message = str(e)
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        
        # Упрощаем сообщение об ошибке
        if "bot was blocked" in error_message:
            error_description = "Пользователь заблокировал бота"
        elif "chat not found" in error_message:
            error_description = "Чат с пользователем не найден"
        elif "user is deactivated" in error_message:
            error_description = "Аккаунт пользователя деактивирован"
        else:
            error_description = error_message
        
        await safe_edit_message(
            callback,
            f"❌ Не удалось отправить сообщение пользователю ID {user_id}.\n\n"
            f"Причина: {error_description}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад к админ-панели", callback_data="admin_back")]
                ]
            )
        )
    
    # Сбрасываем состояние
    await state.clear()


# ------------------ ШАБЛОНЫ СООБЩЕНИЙ ------------------

@message_router.callback_query(F.data == "admin_message_templates_DISABLED")
async def process_message_templates(callback: CallbackQuery, state: FSMContext):
    """Обработчик для управления шаблонами сообщений"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(MessageStates.template_management)
    
    # Получаем список шаблонов
    async with AsyncSessionLocal() as session:
        templates = await get_message_templates(session)
    
    # Формируем клавиатуру с шаблонами
    keyboard_buttons = []
    
    # Добавляем кнопку создания нового шаблона
    keyboard_buttons.append([InlineKeyboardButton(text="➕ Создать новый шаблон", callback_data="create_template")])
    
    # Добавляем кнопки для существующих шаблонов
    for template in templates:
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"{template.name}", callback_data=f"template:{template.id}")
        ])
    
    # Добавляем кнопку возврата
    keyboard_buttons.append([InlineKeyboardButton(text="« Назад", callback_data="admin_back")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    # Текст сообщения
    message_text = "<b>📝 Управление шаблонами сообщений</b>\n\n"
    
    if templates:
        message_text += "Выберите шаблон для просмотра или редактирования:"
    else:
        message_text += "У вас пока нет сохраненных шаблонов. Создайте новый шаблон:"
    
    # Удаляем предыдущее сообщение и отправляем новое вместо edit_text
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    # Отправляем новое сообщение
    await callback.message.answer(
        message_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

@message_router.callback_query(F.data == "create_template")
async def process_create_template(callback: CallbackQuery, state: FSMContext):
    """Обработчик для создания нового шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    await state.set_state(MessageStates.create_template_name)
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_message_templates")]
        ]
    )
    
    # Удаляем предыдущее сообщение и отправляем новое вместо edit_text
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    # Отправляем новое сообщение с запросом названия шаблона
    await callback.message.answer(
        "<b>📝 Создание нового шаблона</b>\n\n"
        "Введите название шаблона:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

@message_router.message(StateFilter(MessageStates.create_template_name))
async def process_template_name(message: types.Message, state: FSMContext):
    """Обработчик ввода названия шаблона"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Сохраняем название шаблона
    template_name = message.text.strip()
    
    if not template_name:
        await message.answer("❌ Название шаблона не может быть пустым. Пожалуйста, введите название:")
        return
    
    await state.update_data(template_name=template_name)
    
    # Запрашиваем текст шаблона
    await state.set_state(MessageStates.create_template_text)
    
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
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_message_templates")]
        ]
    )
    
    await message.answer(
        f"<b>Создание шаблона:</b> {template_name}\n\n"
        f"<b>Используйте эти символы для форматирования:</b>\n"
        f"<code>{format_example}</code>\n\n"
        f"Введите текст шаблона:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@message_router.message(StateFilter(MessageStates.create_template_text))
async def process_template_text(message: types.Message, state: FSMContext):
    """Обработчик ввода текста шаблона"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Преобразуем пользовательский синтаксис в HTML
    original_text = message.text
    converted_text = convert_custom_to_html(original_text)
    
    if not original_text:
        await message.answer("❌ Текст шаблона не может быть пустым. Пожалуйста, введите текст:")
        return
    
    # Отправляем предпросмотр сообщения с форматированием
    preview_message = await message.answer("⏳ Генерирую предпросмотр шаблона...")
    
    try:
        # Отправляем предпросмотр отформатированного текста
        await preview_message.edit_text(
            converted_text,
            parse_mode="HTML"
        )
    except Exception as edit_error:
        logger.error(f"Ошибка при редактировании предпросмотра шаблона: {edit_error}", exc_info=True)
        
        # При ошибке показываем текст без форматирования
        safe_text = original_text.replace("<", "&lt;").replace(">", "&gt;")
        await preview_message.edit_text(
            f"⚠️ Ошибка при форматировании текста: {str(edit_error)}\n\n"
            f"Исходный текст (без форматирования):\n{safe_text[:3000]}",
            parse_mode="HTML"
        )
    
    # Получаем данные из состояния
    user_data = await state.get_data()
    template_name = user_data.get("template_name", "")
    
    # Сохраняем шаблон в базе данных с форматом HTML
    async with AsyncSessionLocal() as session:
        new_template = await create_message_template(
            db=session,
            name=template_name,
            text=converted_text,
            format="HTML",
            created_by=message.from_user.id
        )
    
    # Сообщаем об успешном создании шаблона
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« К списку шаблонов", callback_data="admin_message_templates")]
        ]
    )
    
    await message.answer(
        f"✅ Шаблон <b>{template_name}</b> успешно создан!\n\n"
        f"<b>Текст:</b>\n{converted_text}",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    # Сбрасываем состояние
    await state.clear()

@message_router.callback_query(F.data.startswith("template:"))
async def process_view_template(callback: CallbackQuery, state: FSMContext):
    """Обработчик для просмотра шаблона сообщения"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Получаем информацию о шаблоне
    async with AsyncSessionLocal() as session:
        template = await get_message_template_by_id(session, template_id)
        
        if not template:
            await callback.answer("Шаблон не найден", show_alert=True)
            # Возвращаемся к списку шаблонов
            return await process_message_templates(callback, state)
        
        # Формируем текст с информацией о шаблоне
        template_info = f"""
<b>📝 Шаблон:</b> {template.name}

<b>ID:</b> {template.id}
<b>Формат:</b> {template.format}
<b>Создан:</b> {template.created_at.strftime('%d.%m.%Y %H:%M')}

<b>Текст шаблона:</b>
{template.text}
"""
        
        # Клавиатура с действиями для шаблона
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_template:{template.id}"),
                    InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_template:{template.id}")
                ],
                [
                    InlineKeyboardButton(text="📨 Использовать для отправки", callback_data=f"use_template:{template.id}")
                ],
                [InlineKeyboardButton(text="« Назад к списку", callback_data="admin_message_templates")]
            ]
        )
        
        # Удаляем предыдущее сообщение и отправляем новое
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
        
        await callback.message.answer(
            template_info,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await callback.answer()

@message_router.callback_query(F.data.startswith("edit_template:"))
async def process_edit_template(callback: CallbackQuery, state: FSMContext):
    """Обработчик для редактирования шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Получаем информацию о шаблоне
    async with AsyncSessionLocal() as session:
        template = await get_message_template_by_id(session, template_id)
        
        if not template:
            await callback.answer("Шаблон не найден", show_alert=True)
            return
    
    # Сохраняем ID шаблона и текущие данные в состоянии для дальнейшего редактирования
    await state.update_data(
        editing_template_id=template_id,
        editing_template_name=template.name,
        editing_template_text=template.text,
        editing_template_format=template.format
    )
    
    # Показываем меню редактирования
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"edit_template_name:{template_id}"),
                InlineKeyboardButton(text="📝 Изменить текст", callback_data=f"edit_template_text:{template_id}")
            ],
            [
                InlineKeyboardButton(text="🔤 Изменить формат", callback_data=f"edit_template_format:{template_id}")
            ],
            [InlineKeyboardButton(text="« Назад", callback_data=f"template:{template_id}")]
        ]
    )
    
    # Удаляем предыдущее сообщение и отправляем новое
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    await callback.message.answer(
        f"<b>✏️ Редактирование шаблона:</b> {template.name}\n\n"
        f"<b>ID:</b> {template.id}\n"
        f"<b>Текущий формат:</b> {template.format}\n\n"
        f"Выберите, что вы хотите изменить:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

@message_router.callback_query(F.data.startswith("edit_template_name:"))
async def process_edit_template_name_start(callback: CallbackQuery, state: FSMContext):
    """Обработчик начала редактирования названия шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Устанавливаем состояние для ожидания нового названия
    await state.set_state(MessageStates.edit_template)
    
    # Получаем текущие данные шаблона
    data = await state.get_data()
    current_name = data.get("editing_template_name", "")
    
    # Клавиатура отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data=f"edit_template:{template_id}")]
        ]
    )
    
    # Удаляем предыдущее сообщение и отправляем новое
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    await callback.message.answer(
        f"<b>✏️ Редактирование названия шаблона</b>\n\n"
        f"<b>Текущее название:</b> {current_name}\n\n"
        f"Введите новое название шаблона:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    # Устанавливаем специальное состояние для обработки ввода названия
    await state.update_data(edit_field="name")
    await callback.answer()

@message_router.callback_query(F.data.startswith("edit_template_text:"))
async def process_edit_template_text_start(callback: CallbackQuery, state: FSMContext):
    """Обработчик начала редактирования текста шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Устанавливаем состояние для ожидания нового текста
    await state.set_state(MessageStates.edit_template)
    
    # Получаем текущие данные шаблона
    data = await state.get_data()
    current_text = data.get("editing_template_text", "")
    
    # Клавиатура отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data=f"edit_template:{template_id}")]
        ]
    )
    
    # Удаляем предыдущее сообщение и отправляем новое
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    await callback.message.answer(
        f"<b>📝 Редактирование текста шаблона</b>\n\n"
        f"<b>Текущий текст:</b>\n{current_text}\n\n"
        f"Введите новый текст шаблона:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    # Устанавливаем специальное состояние для обработки ввода текста
    await state.update_data(edit_field="text")
    await callback.answer()

@message_router.callback_query(F.data.startswith("edit_template_format:"))
async def process_edit_template_format_start(callback: CallbackQuery, state: FSMContext):
    """Обработчик начала редактирования формата шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Устанавливаем состояние для выбора нового формата
    await state.set_state(MessageStates.edit_template)
    
    # Получаем текущие данные шаблона
    data = await state.get_data()
    current_format = data.get("editing_template_format", "HTML")
    
    # Клавиатура с форматами
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="HTML", callback_data=f"set_template_format:{template_id}:HTML"),
                InlineKeyboardButton(text="MarkdownV2", callback_data=f"set_template_format:{template_id}:MarkdownV2"),
                InlineKeyboardButton(text="Обычный текст", callback_data=f"set_template_format:{template_id}:Plain")
            ],
            [InlineKeyboardButton(text="« Отмена", callback_data=f"edit_template:{template_id}")]
        ]
    )
    
    # Удаляем предыдущее сообщение и отправляем новое
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    await callback.message.answer(
        f"<b>🔤 Редактирование формата шаблона</b>\n\n"
        f"<b>Текущий формат:</b> {current_format}\n\n"
        f"Выберите новый формат сообщения:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

@message_router.callback_query(F.data.startswith("set_template_format:"))
async def process_set_template_format(callback: CallbackQuery, state: FSMContext):
    """Обработчик выбора нового формата шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона и новый формат
    parts = callback.data.split(":")
    template_id = int(parts[1])
    new_format = parts[2]
    
    # Обновляем шаблон в базе данных
    async with AsyncSessionLocal() as session:
        updated_template = await update_message_template(
            session, 
            template_id, 
            format=new_format
        )
        
        if not updated_template:
            await callback.answer("Шаблон не найден или не удалось обновить", show_alert=True)
            return
    
    # Сообщаем об успешном обновлении
    await callback.answer(f"Формат шаблона изменен на {new_format}", show_alert=True)
    
    # Показываем обновленную информацию о шаблоне
    async with AsyncSessionLocal() as session:
        template = await get_message_template_by_id(session, template_id)
        
        if not template:
            await callback.answer("Шаблон не найден", show_alert=True)
            return
        
        # Формируем текст с информацией о шаблоне
        template_info = f"""
<b>📝 Шаблон:</b> {template.name}

<b>ID:</b> {template.id}
<b>Формат:</b> {template.format}
<b>Создан:</b> {template.created_at.strftime('%d.%m.%Y %H:%M')}

<b>Текст шаблона:</b>
{template.text}
"""
        
        # Клавиатура с действиями для шаблона
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_template:{template.id}"),
                    InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_template:{template.id}")
                ],
                [
                    InlineKeyboardButton(text="📨 Использовать для отправки", callback_data=f"use_template:{template.id}")
                ],
                [InlineKeyboardButton(text="« Назад к списку", callback_data="admin_message_templates")]
            ]
        )
        
        # Удаляем предыдущее сообщение и отправляем новое
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")
        
        await callback.message.answer(
            template_info,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@message_router.message(StateFilter(MessageStates.edit_template))
async def process_edit_template_input(message: types.Message, state: FSMContext):
    """Обработчик ввода нового значения для редактирования шаблона"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    template_id = data.get("editing_template_id")
    edit_field = data.get("edit_field")
    
    if not template_id or not edit_field:
        await message.answer("❌ Произошла ошибка. Пожалуйста, начните редактирование заново.")
        await state.clear()
        return
    
    # Обновляем соответствующее поле в базе данных
    async with AsyncSessionLocal() as session:
        if edit_field == "name":
            new_name = message.text.strip()
            if not new_name:
                await message.answer("❌ Название шаблона не может быть пустым. Пожалуйста, введите название:")
                return
            
            updated_template = await update_message_template(
                session, 
                template_id, 
                name=new_name
            )
            
            if updated_template:
                await message.answer(f"✅ Название шаблона успешно изменено на <b>{new_name}</b>", parse_mode="HTML")
            else:
                await message.answer("❌ Не удалось обновить название шаблона")
            
        elif edit_field == "text":
            new_text = message.text
            if not new_text:
                await message.answer("❌ Текст шаблона не может быть пустым. Пожалуйста, введите текст:")
                return
            
            updated_template = await update_message_template(
                session, 
                template_id, 
                text=new_text
            )
            
            if updated_template:
                await message.answer(f"✅ Текст шаблона успешно обновлен")
            else:
                await message.answer("❌ Не удалось обновить текст шаблона")
    
    # После обновления показываем обновленную информацию о шаблоне
    async with AsyncSessionLocal() as session:
        template = await get_message_template_by_id(session, template_id)
        
        if not template:
            await message.answer("❌ Шаблон не найден. Возможно, он был удален.")
            await state.clear()
            return
        
        # Формируем текст с информацией о шаблоне
        template_info = f"""
<b>📝 Шаблон:</b> {template.name}

<b>ID:</b> {template.id}
<b>Формат:</b> {template.format}
<b>Создан:</b> {template.created_at.strftime('%d.%m.%Y %H:%M')}

<b>Текст шаблона:</b>
{template.text}
"""
        
        # Клавиатура с действиями для шаблона
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_template:{template.id}"),
                    InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_template:{template.id}")
                ],
                [
                    InlineKeyboardButton(text="📨 Использовать для отправки", callback_data=f"use_template:{template.id}")
                ],
                [InlineKeyboardButton(text="« Назад к списку", callback_data="admin_message_templates")]
            ]
        )
        
        await message.answer(
            template_info,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    # Сбрасываем состояние
    await state.clear()

@message_router.callback_query(F.data.startswith("delete_template:"))
async def process_delete_template(callback: CallbackQuery, state: FSMContext):
    """Обработчик для удаления шаблона"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Получаем информацию о шаблоне
    async with AsyncSessionLocal() as session:
        template = await get_message_template_by_id(session, template_id)
        
        if not template:
            await callback.answer("Шаблон не найден", show_alert=True)
            # Возвращаемся к списку шаблонов
            return await process_message_templates(callback, state)
        
        # Удаляем шаблон
        success = await delete_message_template(session, template_id)
        
        if success:
            # Сообщаем об успешном удалении
            try:
                await callback.message.delete()
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения: {e}")
            
            await callback.message.answer(
                f"✅ Шаблон <b>{template.name}</b> успешно удален!",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="« К списку шаблонов", callback_data="admin_message_templates")]
                    ]
                ),
                parse_mode="HTML"
            )
        else:
            await callback.answer("Произошла ошибка при удалении шаблона", show_alert=True)
    
    await callback.answer()

@message_router.callback_query(F.data.startswith("use_template:"))
async def process_use_template(callback: CallbackQuery, state: FSMContext):
    """Обработчик для использования шаблона для отправки"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем ID шаблона
    template_id = int(callback.data.split(":")[1])
    
    # Получаем шаблон из базы данных
    async with AsyncSessionLocal() as session:
        template = await get_message_template_by_id(session, template_id)
        
        if not template:
            await callback.answer("Шаблон не найден", show_alert=True)
            return await process_message_templates(callback, state)
    
    # Сохраняем данные шаблона в состоянии для использования в дальнейшем
    await state.update_data(
        template_id=template_id,
        template_text=template.text,
        template_name=template.name
    )
    
    # Запрашиваем ID пользователя для отправки
    await state.set_state(MessageStates.direct_message_user_id)
    
    # Кнопка отмены
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="admin_message_templates")]
        ]
    )
    
    # Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    # Отправляем новое сообщение с запросом ID пользователя
    await callback.message.answer(
        f"<b>📨 Использование шаблона для отправки</b>\n\n"
        f"<b>Шаблон:</b> {template.name}\n\n"
        f"Введите Telegram ID или Username пользователя, которому хотите отправить сообщение:\n"
        f"(ID должен быть числом, username - с символом @)",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()

# Функция для регистрации обработчиков
def register_message_handlers(dp):
    """Регистрирует обработчики сообщений"""
    dp.include_router(message_router)