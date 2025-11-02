from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import os
from utils.helpers import log_message, escape_markdown_v2, get_payment_method_markup, get_payment_notice, safe_edit_message
from database.config import AsyncSessionLocal
from database.crud import (
    get_or_create_user, 
    get_active_subscription, 
    get_user_by_telegram_id, 
    get_user_by_id,
    has_active_subscription, 
    create_referral_code, 
    get_referrer_info, 
    extend_subscription_days,
    get_payment_by_transaction_id,
    update_payment_status,
    create_subscription,
    update_payment_subscription,
    create_payment_log,
    get_user_by_referral_code,
    update_user_referrer,
    get_payment_by_label,
    is_payment_processed,
    mark_payment_as_processed,
    update_subscription_end_date,
    has_received_referral_bonus,
    mark_referral_bonus_as_received,
    send_referral_bonus_notification,
    send_payment_notification_to_admins,
    add_user_to_club_channel,
    get_payment_by_id,
    get_promo_code_by_code,
    has_user_used_promo_code,
    apply_promo_code_days,
    use_promo_code,
    has_user_paid_before,
    extend_subscription,
    is_first_payment_by_user,
    set_user_birthday,
    disable_user_auto_renewal,
    enable_user_auto_renewal,
    update_user
)
from sqlalchemy import update
from database.models import User
from utils.payment import create_payment_link, check_payment_status
from utils.constants import (
    CLUB_CHANNEL_URL, 
    SUBSCRIPTION_PRICE_FIRST,
    SUBSCRIPTION_PRICE, 
    SUBSCRIPTION_DAYS, 
    SUBSCRIPTION_PRICE_2MONTHS,
    SUBSCRIPTION_DAYS_2MONTHS,
    SUBSCRIPTION_PRICE_3MONTHS,
    SUBSCRIPTION_DAYS_3MONTHS,
    WELCOME_IMAGE_PATH, 
    REFERRAL_BONUS_DAYS,
    WELCOME_TEXT,
    TEMPORARY_PAYMENT_MODE
)
import asyncio
from handlers.admin_handlers import ADMIN_IDS  # Импортируем список администраторов
import logging
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta, date
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.markdown import hlink # Импортируем hlink
from aiogram.fsm.state import State, StatesGroup # <-- Импорт для FSM
from aiogram.filters import StateFilter # <-- Исправленный импорт StateFilter

# --- Состояния FSM для промокода ---
class PromoCodeStates(StatesGroup):
    waiting_for_promo_code = State()

# --- Состояния FSM для даты рождения ---
class BirthdayStates(StatesGroup):
    waiting_for_birthday = State()

# --- Состояния FSM для телефона ---
class PhoneStates(StatesGroup):
    waiting_for_phone = State()

# --- Состояния FSM для email ---
class EmailStates(StatesGroup):
    waiting_for_email = State()

# --- Состояния FSM для данных при оплате ---
class PaymentDataStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_email = State()

# --- Конец состояний FSM ---

# Создаем логгер
logger = logging.getLogger(__name__)
payment_logger = logging.getLogger("payments")

# Создаем роутер для пользовательских команд
user_router = Router()

# Создаем основную клавиатуру с Reply-кнопками
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎀 Личный кабинет"), KeyboardButton(text="✨ Отзывы")],
        [KeyboardButton(text="💕Написать мне")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Обработчик команды /start
@user_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """
    Обработчик команды /start
    """
    # Проверка режима технического обслуживания
    from utils.constants import MAINTENANCE_MODE, MAINTENANCE_MESSAGE
    if MAINTENANCE_MODE:
        await message.answer(MAINTENANCE_MESSAGE, parse_mode="HTML")
        return
    
    # Исправленный вызов log_message с правильными параметрами
    try:
        log_message(message.from_user.id, message.text, "command")
    except:
        # Если возникла ошибка, пропускаем логирование
        pass
    
    # Извлекаем реферальный код из аргументов, если он есть
    ref_code = None
    args = message.text.split()
    if len(args) > 1:
        arg = args[1]
        # Проверяем, начинается ли аргумент с префикса "ref_"
        if arg.startswith("ref_"):
            # Извлекаем сам код, убирая префикс "ref_"
            ref_code = arg[4:]
            logger.info(f"Получен реферальный код: {ref_code}")
        else:
            # Используем аргумент как есть (для совместимости)
            ref_code = arg
            logger.info(f"Получен аргумент без префикса: {ref_code}")
    
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Создаем сессию базы данных
    async with AsyncSessionLocal() as session:
        # Получаем или создаем пользователя
        user = await get_or_create_user(
            session, 
            user_id, 
            username, 
            first_name, 
            last_name
        )
        
        # Сбрасываем флаг отправки напоминания при повторном запуске /start
        # Это позволит снова отправить напоминание через 1 час, если пользователь заново запустил бота
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(reminder_sent=False)
        )
        await session.commit()
        
        # Если пользователь создан и есть реферальный код
        if ref_code:
            # Проверяем, существует ли пользователь с указанным реферальным кодом
            referrer = await get_user_by_referral_code(session, ref_code)
            if referrer:
                # Обновляем информацию о реферере
                await update_user_referrer(session, user.id, referrer.id)
                
                # Отправляем сообщение рефереру
                try:
                    # Получаем имя пользователя для более персонализированного сообщения
                    invited_name = f"{first_name} {last_name or ''}".strip()
                    if username:
                        invited_name += f" (@{username})"
                    
                    referral_message = (
                        f"🎉 <b>Ура! По вашей реферальной ссылке присоединился новый пользователь!</b>\n\n"
                        f"👤 {invited_name}\n\n"
                        f"💫 <b>Что дальше?</b>\n"
                        f"Как только этот пользователь оформит подписку, вы автоматически получите "
                        f"<b>+{REFERRAL_BONUS_DAYS} дней</b> к вашей подписке на Mom's Club!\n\n"
                        f"🤍 Спасибо, что рекомендуете нас друзьям!"
                    )
                    
                    await message.bot.send_message(
                        referrer.telegram_id,
                        referral_message,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения рефереру: {e}")
    
    # Проверяем наличие активной подписки
    async with AsyncSessionLocal() as session:
        has_subscription = await has_active_subscription(session, user_id)
        user = await get_user_by_telegram_id(session, user_id)

    # Если нет активной подписки, показываем приветственное сообщение и кнопку для оплаты
    if not has_subscription:
        # Создаем клавиатуру с кнопкой оплаты
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")]
            ]
        )
        
        # Отправляем приветственное изображение
        if os.path.exists(WELCOME_IMAGE_PATH):
            photo = FSInputFile(WELCOME_IMAGE_PATH)
            await message.answer_photo(
                photo=photo,
                caption=WELCOME_TEXT,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Если изображение не найдено, отправляем только текст и логируем ошибку
            logger.error(f"Приветственное изображение не найдено по пути: {WELCOME_IMAGE_PATH}. Создаем директорию media и пустой файл.")
            
            # Создаем директорию, если она отсутствует
            os.makedirs(os.path.dirname(WELCOME_IMAGE_PATH), exist_ok=True)
            
            # Создаем пустой файл, чтобы предотвратить повторение ошибки
            with open(WELCOME_IMAGE_PATH, 'w') as f:
                f.write("# Это временный файл-заглушка. Пожалуйста, замените его на реальное приветственное изображение")
            
            await message.answer(
                WELCOME_TEXT,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        # Ждем 0.5 секунды перед отправкой второго сообщения
        await asyncio.sleep(0.5)
        
        # Отправляем сообщение с Reply-клавиатурой
        admin_text = """🌸 *Если остались вопросы про клуб* — напиши мне, я с радостью всё объясню и поддержу 🤍\nБуду рада твоему сообщению в Telegram 👉 [@polinadmitrenkoo](https://t.me/polinadmitrenkoo)"""
        await message.answer(
            admin_text,
            reply_markup=main_keyboard,
            parse_mode="MarkdownV2"
        )

        # Если у пользователя уже есть номер, не спрашиваем его
        if user and user.phone:
            return

        # После приветствия и до показа тарифов
        await state.set_state(PhoneStates.waiting_for_phone)
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer(
            "📲 Для оформления подписки Mom's Club нужно указать номер телефона. Мы используем его только для отправки чеков об оплате и связи по вопросам подписки.\n\nПожалуйста, нажми кнопку ниже и отправь свой номер:",
            reply_markup=keyboard
        )
        return
    else:
        # Если у пользователя есть активная подписка, отправляем ссылку на канал с reply-клавиатурой
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🩷 Перейти в закрытый канал", url=CLUB_CHANNEL_URL)]
            ]
        )
        await message.answer(
            "У вас есть активная подписка!\nВы можете перейти в закрытый канал по кнопке ниже или с помощью команды /club",
            reply_markup=keyboard
        )
        
        # Ждем 0.5 секунды перед отправкой второго сообщения
        await asyncio.sleep(0.5)
        
        # Отправляем сообщение с Reply-клавиатурой
        admin_text = """🌸 *Если остались вопросы про клуб* — напиши мне, я с радостью всё объясню и поддержу 🤍
Буду рада твоему сообщению в Telegram 👉 [@polinadmitrenkoo](https://t.me/polinadmitrenkoo)"""
        
        await message.answer(
            admin_text,
            reply_markup=main_keyboard,
            parse_mode="MarkdownV2"
        )


# Обработчик для миграционной подписки
@user_router.callback_query(F.data == "migrate_subscribe")
async def process_migrate_subscribe(callback: types.CallbackQuery):
    """
    Обработчик для кнопки миграционной подписки.
    Позволяет пользователям с активной подпиской ЮКассы оформить новую подписку через Prodamus.
    """
    log_message(callback.from_user.id, "migrate_subscribe", "action")
    
    try:
        user_id = callback.from_user.id
        
        # Получаем пользователя
        async with AsyncSessionLocal() as db:
            user = await get_user_by_telegram_id(db, user_id)
            if not user:
                await callback.answer("❌ Ошибка: пользователь не найден", show_alert=True)
                return
        
        # Текст предложения подписки для миграции
        migration_subscription_text = """<b>🔄 Настройка новой системы оплаты</b>

Мы переходим на новую платёжную систему для улучшения сервиса.

<b>Выберите подходящий тариф для продолжения доступа:</b>

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам

<b>Нажми на один из вариантов для продолжения доступа:</b>"""

        # Создаем инлайн-клавиатуру с кнопками разных тарифов
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_1month")],
                [InlineKeyboardButton(text=f"2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data="payment_2months")],
                [InlineKeyboardButton(text=f"3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data="payment_3months")],
                [InlineKeyboardButton(text="🎁 Промокод", callback_data="promo_code")],
                [InlineKeyboardButton(text="💬 Связаться с поддержкой", url="https://t.me/polinadmitrenkoo")]
            ]
        )

        # Редактируем сообщение
        try:
            await callback.message.edit_text(
                migration_subscription_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения миграции: {e}")
            await callback.message.answer(
                migration_subscription_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка в process_migrate_subscribe: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# Модифицируем обработчик нажатия на кнопку подписки, добавляя проверку состояния
@user_router.callback_query(F.data == "subscribe")
async def process_subscribe(callback: types.CallbackQuery):
    log_message(callback.from_user.id, "view_offer", "action")
    
    try:
        # Получаем пользователя из базы данных
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if user:
                # Проверяем наличие активной подписки
                subscription = await get_active_subscription(session, user.id)
                if subscription:
                    # Если есть активная подписка, отправляем новое сообщение вместо редактирования
                    await callback.answer("У вас уже есть доступ к каналу", show_alert=True)
                    
                    # Создаем клавиатуру для перехода в канал
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🔐 Войти в закрытый канал", url=CLUB_CHANNEL_URL)],
                            [InlineKeyboardButton(text="🔍 Мои подписки", callback_data="my_subscriptions")],
                            [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                        ]
                    )
                    
                    # Отправляем новое сообщение вместо редактирования
                    await callback.message.answer(
                        "🎉 У вас уже есть активная подписка!\n\n" +
                        f"Подписка действует до: {subscription.end_date.strftime('%d.%m.%Y')}\n\n" +
                        f"Нажмите на кнопку ниже, чтобы перейти в закрытый канал Mom's Club.",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    return
        
        # Если включен временный режим оплаты
        if TEMPORARY_PAYMENT_MODE:
            message_text = get_payment_notice()
            keyboard = get_payment_method_markup()
            
            try:
                # Удаляем предыдущее сообщение
                await callback.message.delete()
                
                # Отправляем новое сообщение с временным уведомлением
                await callback.message.answer(
                    message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                # В случае ошибки отправляем без удаления
                await callback.message.answer(
                    message_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                logger.error(f"Ошибка при отправке временного уведомления: {e}")
            
            # Убираем часы загрузки на кнопке
            await callback.answer()
            return
        
        # Стандартный режим - оригинальный код
        # Проверяем, первая ли это оплата для определения текста и цены
        from database.crud import get_user_by_telegram_id
        async with AsyncSessionLocal() as session:
            current_user = await get_user_by_telegram_id(session, callback.from_user.id)
            is_first_payment = current_user and not current_user.is_first_payment_done
        session.close()
        
        # Текст предложения подписки
        if is_first_payment:
            subscription_text = """<b>🎉 Специальное предложение для тебя!</b>

<b>Попробуй Mom's Club за 690₽ на первый месяц</b> 💖

Это наш подарок, чтобы ты смогла прочувствовать всю магию клуба:

• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам

💫 Попробуй на месяц и останься с нами! После первый месяц вернется к обычной цене 990₽

<b>Нажми на вариант, чтобы присоединиться!</b>"""
        else:
            subscription_text = """<b>Выберите подходящий вам тариф доступа в Mom's Club:</b>

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам

<b>Нажми на один из вариантов, чтобы присоединиться прямо сейчас!</b>"""

        # Создаем инлайн-клавиатуру с кнопками разных тарифов
        if is_first_payment:
            # Для первой оплаты показываем только 1 месяц
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"🎁 1 месяц — {SUBSCRIPTION_PRICE_FIRST} ₽ (специальная цена)", callback_data="payment_1month")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
        else:
            # Обычные тарифы
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_1month")],
                    [InlineKeyboardButton(text=f"2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data="payment_2months")],
                    [InlineKeyboardButton(text=f"3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data="payment_3months")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
        
        # Локальный баннер для страницы тарифов
        banner_path = os.path.join(os.getcwd(), "media", "аватар.jpg")
        banner_photo = FSInputFile(banner_path)
        
        # Отправляем баннер с подписью и кнопками
        try:
            # Удаляем предыдущее сообщение
            await callback.message.delete()
            
            # Отправляем баннер с текстом и кнопками
            await callback.message.answer_photo(
                photo=banner_photo,
                caption=subscription_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            # Если не можем удалить или отправить баннер, просто отправляем новое сообщение
            await callback.message.answer_photo(
                photo=banner_photo,
                caption=subscription_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            logger.error(f"Ошибка при отправке баннера тарифов: {e}")
    except Exception as e:
        logger.error(f"Ошибка при обработке подписки: {e}")
        await callback.answer("Произошла ошибка. Пожалуйста, попробуйте позже.", show_alert=True)
    
    # Убираем часы загрузки на кнопке
    await callback.answer()


# Обработчик для тарифа 1 месяц
@user_router.callback_query(F.data == "payment_1month")
async def process_payment_1month(callback: types.CallbackQuery, state: FSMContext):
    log_message(callback.from_user.id, "start_payment_1month", "action")
    
    # Проверяем, первая ли это оплата
    from database.crud import get_user_by_telegram_id
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if user and not user.is_first_payment_done:
            # Первая оплата - специальная цена
            price = SUBSCRIPTION_PRICE_FIRST
        else:
            # Обычная цена
            price = SUBSCRIPTION_PRICE
    
    await process_subscription_payment(
        callback, 
        state, 
        price=price, 
        days=SUBSCRIPTION_DAYS, 
        sub_type="momclub_subscription_1month"
    )


# Обработчик для тарифа 3 месяца
@user_router.callback_query(F.data == "payment_3months")
async def process_payment_3months(callback: types.CallbackQuery, state: FSMContext):
    log_message(callback.from_user.id, "start_payment_3months", "action")
    await process_subscription_payment(
        callback, 
        state, 
        price=SUBSCRIPTION_PRICE_3MONTHS, 
        days=SUBSCRIPTION_DAYS_3MONTHS, 
        sub_type="momclub_subscription_3months"
    )


# Обработчик для тарифа 2 месяца
@user_router.callback_query(F.data == "payment_2months")
async def process_payment_2months(callback: types.CallbackQuery, state: FSMContext):
    log_message(callback.from_user.id, "start_payment_2months", "action")
    await process_subscription_payment(
        callback, 
        state, 
        price=SUBSCRIPTION_PRICE_2MONTHS, 
        days=SUBSCRIPTION_DAYS_2MONTHS, 
        sub_type="momclub_subscription_2months"
    )


# Общая функция для обработки платежей всех тарифов
async def process_subscription_payment(callback: types.CallbackQuery, state: FSMContext, price: int, days: int, sub_type: str):
    # Проверка режима технического обслуживания
    from utils.constants import DISABLE_PAYMENTS
    if DISABLE_PAYMENTS:
        await callback.answer(
            "💳 Платежи временно недоступны\n"
            "🔧 Идет обновление системы", 
            show_alert=True
        )
        return
    
    try:
        from database.crud import get_user_by_telegram_id
        
        # Получаем данные о пользователе
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("Пользователь не найден в базе данных", show_alert=True)
                return

            # Проверяем, есть ли у пользователя телефон и email
            if not user.phone or not user.email:
                # Сохраняем данные о платеже в состоянии
                await state.update_data(
                    payment_price=price,
                    payment_days=days,
                    payment_sub_type=sub_type
                )
                
                if not user.phone:
                    # Запрашиваем телефон
                    await state.set_state(PaymentDataStates.waiting_for_phone)
                    await safe_edit_message(
                        callback,
                        "📱 *Для оформления подписки нужен ваш номер телефона*\n\n"
                        "Пожалуйста, введите номер телефона в формате:\n"
                        "`+7 XXX XXX XX XX` или `8 XXX XXX XX XX`\n\n"
                        "💡 Номер телефона нужен для:\n"
                        "• Оформления подписки\n"
                        "• Автоматических продлений\n"
                        "• Связи в случае проблем с оплатой",
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="« Назад", callback_data="subscribe")]
                            ]
                        )
                    )
                elif not user.email:
                    # Запрашиваем email
                    await state.set_state(PaymentDataStates.waiting_for_email) 
                    await safe_edit_message(
                        callback,
                        "📧 *Для оформления подписки нужен ваш email*\n\n"
                        "Пожалуйста, введите ваш email\\-адрес:\n"
                        "`example@mail.ru`\n\n"
                        "💡 Email нужен для:\n"
                        "• Чеков об оплате\n"
                        "• Уведомлений о продлении\n"
                        "• Связи в случае проблем",
                        parse_mode="MarkdownV2",
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="« Назад", callback_data="subscribe")]
                            ]
                        )
                    )
                return
            
            # Если все данные есть, создаем платеж
            await create_payment_for_user(callback, state, user, price, days, sub_type)
    
    except Exception as e:
        logger.error(f"Ошибка при создании платежа: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)


async def create_payment_for_user(callback: types.CallbackQuery, state: FSMContext, user, price: int, days: int, sub_type: str):
    """Создает платеж для пользователя с полными данными"""
    try:
        from database.crud import create_payment_log
        
        async with AsyncSessionLocal() as session:
            payment_url, payment_id, payment_label = create_payment_link(
                amount=price,
                user_id=user.telegram_id,
                description=f"Подписка на Mom's Club на {days} дней (username: @{user.username or 'Unknown'})",
                sub_type=sub_type,
                days=days,
                phone=user.phone,
                email=user.email
            )
            
            if payment_url and payment_id and payment_label:
                # Сохраняем только метку в state для возможной отладки
                await state.update_data(
                    payment_label=payment_label
                )
                
                # Создаем запись о платеже (статус "pending")
                payment_log_entry = await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=None,
                    amount=price,
                    status="pending",
                    payment_method="prodamus",
                    transaction_id=payment_id, # Сохраняем UUID платежа
                    details=f"Подписка на Mom's Club на {days} дней (username: @{user.username or 'Unknown'})",
                    payment_label=payment_label,
                    days=days # Сохраняем количество дней
                )
                
                # Используем ID записи лога платежа для callback_data
                payment_db_id = payment_log_entry.id
                
                # Новая клавиатура БЕЗ кнопки "Я оплатила"
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"💳 Перейти к оплате ({price} ₽)", url=payment_url)],
                        [InlineKeyboardButton(text="« Назад", callback_data="subscribe")]
                    ]
                )
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Отправляем новое сообщение с информацией о платеже
                    await callback.message.answer(
                        f"🔐 <b>Оформление подписки на {days} дней</b>\n\n"
                        f"Сумма к оплате: <b>{price} ₽</b>\n\n"
                        "Для оплаты нажмите на кнопку «Перейти к оплате» ниже.\n"
                        "После успешной оплаты подписка активируется в течении 2-5 минут.\n"
                        "Вы получите уведомление, когда платеж будет обработан.",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения о платеже: {e}")
                    await callback.answer("Произошла ошибка при создании платежа", show_alert=True)
            else:
                await callback.answer("Произошла ошибка при создании ссылки на оплату", show_alert=True)
                
    except Exception as e:
        logger.error(f"Ошибка при создании платежа для пользователя: {e}")
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)


# Обработчик ввода телефона для оплаты
@user_router.message(StateFilter(PaymentDataStates.waiting_for_phone))
async def process_payment_phone_input(message: types.Message, state: FSMContext):
    """Обрабатывает ввод номера телефона для оплаты"""
    import re
    
    phone_text = message.text.strip()
    
    # Проверяем формат телефона
    phone_pattern = r'^(\+7|8|7)[\s\-]?(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})$'
    if not re.match(phone_pattern, phone_text):
        await message.answer(
            "❌ *Неверный формат номера телефона*\n\n"
            "Пожалуйста, введите номер в формате:\n"
            "`+7 XXX XXX XX XX` или `8 XXX XXX XX XX`\n\n"
            "Например: `+7 900 123 45 67`",
            parse_mode="MarkdownV2"
        )
        return
    
    # Нормализуем номер телефона
    phone_digits = re.sub(r'\D', '', phone_text)
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    elif phone_digits.startswith('7') and len(phone_digits) == 10:
        phone_digits = '7' + phone_digits
        
    try:
        from database.crud import get_user_by_telegram_id, update_user
        
        # Сохраняем телефон в базе данных
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, message.from_user.id)
            if user:
                await update_user(session, user.telegram_id, phone=phone_digits)
                
                # Проверяем, нужен ли email
                user = await get_user_by_telegram_id(session, message.from_user.id)  # Обновляем данные
                if not user.email:
                    # Переходим к запросу email
                    await state.set_state(PaymentDataStates.waiting_for_email)
                    await message.answer(
                        "✅ *Телефон сохранен\\!*\n\n"
                        "📧 *Теперь введите ваш email\\-адрес:*\n\n"
                        "Например: `example@mail\\.ru`\n\n"
                        "💡 Email нужен для:\n"
                        "• Чеков об оплате\n"
                        "• Уведомлений о продлении\n"
                        "• Связи в случае проблем",
                        parse_mode="MarkdownV2"
                    )
                else:
                    # Все данные есть, создаем платеж
                    data = await state.get_data()
                    await state.clear()
                    
                    # Создаем фальшивый callback для совместимости
                    fake_callback = types.CallbackQuery(
                        id="fake",
                        from_user=message.from_user,
                        chat_instance="fake",
                        message=message
                    )
                    
                    await create_payment_for_user(
                        fake_callback, 
                        state, 
                        user, 
                        data['payment_price'], 
                        data['payment_days'], 
                        data['payment_sub_type']
                    )
    except Exception as e:
        logger.error(f"Ошибка при сохранении телефона: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


# Обработчик ввода email для оплаты  
@user_router.message(StateFilter(PaymentDataStates.waiting_for_email))
async def process_payment_email_input(message: types.Message, state: FSMContext):
    """Обрабатывает ввод email для оплаты"""
    import re
    
    email_text = message.text.strip()
    
    # Проверяем формат email
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email_text):
        await message.answer(
            "❌ *Неверный формат email*\n\n"
            "Пожалуйста, введите корректный email\\-адрес:\n"
            "`example@mail\\.ru`",
            parse_mode="MarkdownV2"
        )
        return
    
    try:
        from database.crud import get_user_by_telegram_id, update_user
        
        # Сохраняем email в базе данных
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, message.from_user.id)
            if user:
                await update_user(session, user.telegram_id, email=email_text)
                
                # Все данные есть, создаем платеж
                data = await state.get_data()
                await state.clear()
                
                # Создаем фальшивый callback для совместимости
                fake_callback = types.CallbackQuery(
                    id="fake",
                    from_user=message.from_user,
                    chat_instance="fake",
                    message=message
                )
                
                await create_payment_for_user(
                    fake_callback, 
                    state, 
                    user, 
                    data['payment_price'], 
                    data['payment_days'], 
                    data['payment_sub_type']
                )
    except Exception as e:
        logger.error(f"Ошибка при сохранении email: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")


# Остальные обработчики...


# Заменяем прежний обработчик payment на redirect к одномесячной подписке
@user_router.callback_query(F.data == "payment")
async def process_payment(callback: types.CallbackQuery, state: FSMContext):
    # Для обратной совместимости перенаправляем на тариф 1 месяц
    log_message(callback.from_user.id, "redirect_to_1month", "action")
    await process_payment_1month(callback, state)

# Обработчик проверки оплаты
@user_router.callback_query(F.data.startswith("check_payment:"))
async def process_check_payment(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает проверку статуса платежа"""
    payment_logger = logging.getLogger("payment")
    
    # Получаем ID записи из callback_data
    payment_db_id = int(callback.data.split(":")[1])
    payment_logger.info(f"Запрос на проверку платежа с DB ID: {payment_db_id}")
    
    try:
        # Получаем данные о пользователе
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            if not user:
                await callback.answer("Пользователь не найден в базе данных", show_alert=True)
                return
            
            # Ищем запись о платеже в БД по ID
            payment = await get_payment_by_id(session, payment_db_id)
            
            if not payment:
                await callback.answer("Информация о платеже не найдена. Возможно, вы нажали на старую кнопку.", show_alert=True)
                return
            
            # Получаем данные из записи лога платежа
            payment_label = payment.payment_label
            if not payment_label:
                payment_logger.error(f"У записи платежа с ID {payment_db_id} отсутствует метка (payment_label)")
                await callback.answer("Ошибка данных платежа. Свяжитесь с поддержкой.", show_alert=True)
                return
                
            # Используем сумму и дни из лога платежа
            payment_amount = payment.amount
            subscription_days = payment.days

            # Проверяем, если вдруг дни не были сохранены
            if subscription_days is None:
                 payment_logger.warning(f"В записи лога платежа ID {payment_db_id} отсутствует количество дней. Используем стандартное: {SUBSCRIPTION_DAYS}")
                 subscription_days = SUBSCRIPTION_DAYS
            
            # Отправляем сообщение о проверке
            await callback.answer("Проверяем статус платежа...", show_alert=False)
            
            # --- Начало добавленного логирования ---
            payment_logger.info(f"Вызов check_payment_status для метки: {payment_label}")
            transaction_id = payment.transaction_id  # ID платежа ЮКассы
            payment_status, payment_data = check_payment_status(
                transaction_id,
                payment_amount
            )
            payment_logger.info(f"Результат check_payment_status: status='{payment_status}', operation={payment_data}")
            # --- Конец добавленного логирования ---
            
            # Получаем потенциального реферера
            referrer = None
            if user.referrer_id:
                referrer = await get_user_by_id(session, user.referrer_id)

            # Определяем transaction_id (из операции Prodamus или из записи в БД)
            transaction_id = payment.transaction_id
            # Если в ответе есть данные платежа, можем проверить, что ID совпадает
            if payment_data and 'id' in payment_data:
                if transaction_id != payment_data['id']:
                    payment_logger.warning(f"ID платежа в БД ({transaction_id}) отличается от ID в Prodamus ({payment_data['id']})")
            
            # Получаем информацию о текущей подписке (для сообщений об ошибке)
            active_subscription = await get_active_subscription(session, user.id)
            subscription_text = ""
            if active_subscription:
                end_date_formatted = active_subscription.end_date.strftime("%d.%m.%Y")
                subscription_text = f"\n\n✅ Ваша текущая подписка активна до *{escape_markdown_v2(end_date_formatted)}* и продолжает действовать\\."
            
            if payment_status == "success":
                # Проверяем, не обрабатывали ли уже этот платеж
                if payment.is_confirmed or payment.status == "success":
                    # Платеж уже был обработан ранее
                    payment_logger.warning(f"Попытка повторной обработки платежа с меткой {payment_label}")
                    await callback.answer("Этот платеж уже был обработан ранее.", show_alert=True)
                    return

                # Отмечаем факт проверки платежа, чтобы не было дублирующих проверок
                payment.is_confirmed = True
                await session.commit()
                
                # Создаем или продлеваем подписку
                has_sub = await has_active_subscription(session, user.id)
                if has_sub:
                    # Продлеваем существующую подписку
                    subscription = await extend_subscription(
                        session, 
                        user.id, 
                        subscription_days,
                        payment_amount,
                        f"payment_{transaction_id}" # Добавляем уникальный ID транзакции
                    )
                    payment_logger.info(f"Продлена подписка ID {subscription.id} для пользователя {user.id} на {subscription_days} дней")
                else:
                    # Создаем новую подписку
                    subscription = await create_subscription(
                        session, 
                        user.id, 
                        datetime.now() + timedelta(days=subscription_days),
                        payment_amount,
                        f"payment_{transaction_id}" # Добавляем уникальный ID транзакции
                    )
                    payment_logger.info(f"Создана новая подписка ID {subscription.id} для пользователя {user.id}")
                
                payment_logger.info(f"Платеж {payment_label} будет привязан к подписке ID {subscription.id}")
                
                # Помечаем платеж как обработанный (используем метку)
                await mark_payment_as_processed(session, payment_label)
                payment_logger.info(f"Платеж {payment_label} помечен как обработанный")
                
                # Обновляем статус платежа в логе и привязываем подписку
                await update_payment_status(session, payment.id, "success")
                await update_payment_subscription(session, payment.id, subscription.id)
                
                # --- Логика начисления реферального бонуса --- 
                if referrer:
                    # Проверяем, подходит ли пользователь для начисления бонуса рефереру
                    # Бонус начисляется только за первый платеж реферала
                    payment_logger.info(f"Проверка для начисления реферального бонуса. Пользователь {user.id}, реферер {referrer.id}")
                    
                    is_first_payment = await is_first_payment_by_user(session, user.id)
                    bonus_already_received = await has_received_referral_bonus(session, user.id)
                    
                    if is_first_payment:
                        payment_logger.info(f"Первый платеж пользователя {user.id}. Проверяем, был ли уже выдан бонус: {bonus_already_received}")
                        
                        if not bonus_already_received:
                            payment_logger.info(f"Первый платеж пользователя {user.id}. Начисляем бонус {REFERRAL_BONUS_DAYS} дней рефереру {referrer.id}")
                            bonus_days_for_referrer = REFERRAL_BONUS_DAYS
                            # Продлеваем подписку реферера
                            success_bonus = await extend_subscription_days(session, referrer.id, bonus_days_for_referrer, reason=f"referral_bonus_for_{user.id}")
                            if success_bonus:
                                # Отправляем уведомление рефереру
                                await send_referral_bonus_notification(callback.bot, referrer.telegram_id, user.first_name or f"ID: {user.telegram_id}", bonus_days_for_referrer)
                                # Отмечаем, что бонус выдан (предполагается, что extend_subscription_days создает лог)
                                # await mark_referral_bonus_as_received(session, user.id) # Возможно, эта функция избыточна, если extend_subscription_days логирует
                                payment_logger.info(f"Реферальный бонус успешно начислен рефереру {referrer.id}")
                            else:
                                payment_logger.error(f"Не удалось начислить реферальный бонус рефереру {referrer.id}")
                        else:
                            payment_logger.info(f"Реферальный бонус за пользователя {user.id} уже был начислен ранее (проверка has_received_referral_bonus).")
                    else:
                         payment_logger.info(f"Это не первый платеж пользователя {user.id}. Бонус рефереру не начисляется.")
                else:
                    payment_logger.info(f"Пользователь {user.id} не является рефералом.")
                # --- Конец логики реферального бонуса --- 
                
                # Отправляем уведомление администраторам
                await send_payment_notification_to_admins(callback.bot, user, payment, subscription, transaction_id) # Передаем объект бота вместо session

                # Клавиатура с кнопкой для перехода в канал
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🎀 Перейти в Mom's Club", url=CLUB_CHANNEL_URL)],
                        [InlineKeyboardButton(text="🏠 Вернуться в начало", callback_data="back_to_main")]
                    ]
                )
                
                # Форматируем дату окончания подписки для отображения
                end_date_formatted = subscription.end_date.strftime("%d.%m.%Y")
                
                # Формируем сообщение об успехе (Убрал текст про промокод отсюда)
                success_text = (
                    f"🎉 *Поздравляем\\!* Ваш платеж успешно прошел\\.\n\n"
                    f"Подписка активна до: *{escape_markdown_v2(end_date_formatted)}*\n\n"
                    f"Добро пожаловать в клуб\\! Теперь вы можете перейти в закрытый канал и получить доступ ко всем материалам\\."
                )
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Отправляем новое сообщение об успешном платеже
                    await callback.message.answer(
                        success_text,
                        reply_markup=keyboard,
                        parse_mode="MarkdownV2"
                    )
                    
                    # Запрос даты рождения, если она еще не указана
                    user_profile = await get_user_by_id(session, user.id)
                    if user_profile and not user_profile.birthday:
                        await state.set_state(BirthdayStates.waiting_for_birthday)
                        await state.update_data(user_id_db_for_birthday=user.id)
                        await callback.message.answer(
                            text="🎂 Чтобы мы могли поздравить вас с Днем Рождения и сделать приятный сюрприз, укажите, пожалуйста, вашу дату рождения в формате ДД.ММ.ГГГГ (например, 25.08.1990).\n\nЭто необязательно, но нам будет очень приятно! 😊",
                            reply_markup=InlineKeyboardMarkup(
                                inline_keyboard=[
                                    [InlineKeyboardButton(text="❌ Пропустить", callback_data="skip_birthday")]
                                ]
                            )
                        )
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения об успешном платеже: {e}")
                    # Если удаление не удалось, просто отправляем новое сообщение
                    await callback.message.answer(
                        success_text,
                        reply_markup=keyboard,
                        parse_mode="MarkdownV2"
                    )
            else:
                # Если платеж не успешен или не найден
                payment_logger.warning(f"Платеж {payment_label} не найден или неуспешен. Статус: {payment_status}")
                
                # Обновляем статус платежа в логе, если нужно (если статус изменился)
                if payment.status != "failed" and payment_status == "failed":
                    await update_payment_status(session, payment.id, "failed")
                
                # Формируем текст ошибки с информацией о текущей подписке
                error_text = "🔍 *Оплата не найдена*\n\n"
                error_text += "Возможные причины:\n"
                error_text += "• Вы нажали кнопку слишком рано \\- подождите несколько минут после оплаты\n"
                error_text += "• Платеж еще не обработан платежной системой\n"
                error_text += "• Возникла ошибка при проведении платежа\n\n"
                error_text += "Пожалуйста, проверьте статус платежа в приложении банка и попробуйте снова через несколько минут\\."
                
                # Добавляем информацию о текущей подписке, если она есть
                error_text += subscription_text
                
                # Клавиатура с кнопками для повторной проверки или закрытия
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Проверить еще раз", callback_data=callback.data)],
                        [InlineKeyboardButton(text="« Назад", callback_data="subscribe")]
                    ]
                )
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Отправляем новое сообщение о неудачном платеже
                    await callback.message.answer(
                        error_text,
                        reply_markup=keyboard,
                        parse_mode="MarkdownV2"
                    )
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения о неудачном платеже: {e}")
                    # Если удаление не удалось, просто отправляем новое сообщение
                    await callback.message.answer(
                        error_text,
                        reply_markup=keyboard,
                        parse_mode="MarkdownV2"
                    )
                
    except Exception as e:
        payment_logger.error(f"Ошибка при проверке платежа: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при проверке платежа. Пожалуйста, попробуйте позже.", show_alert=True)


# Обработчик команды /help
@user_router.message(Command("help"))
async def cmd_help(message: types.Message):
    """
    Обработчик команды /help
    """
    help_text = """Доступные команды:
/start - Начать работу с ботом
/profile - Личный кабинет
/club - Получить ссылку на закрытый канал
/help - Показать это сообщение помощи"""
    
    await message.answer(help_text)


# Обработчик команды /club
@user_router.message(Command("club"))
async def cmd_club(message: types.Message):
    """
    Обработчик команды /club
    """
    # Исправленный вызов log_message с правильными параметрами
    try:
        log_message(message.from_user.id, message.text, "command")
    except:
        pass
    
    # Проверяем наличие активной подписки
    async with AsyncSessionLocal() as session:
        has_subscription = await has_active_subscription(session, message.from_user.id)
    
    if has_subscription:
        # Если у пользователя есть активная подписка, отправляем ссылку на канал
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🩷 Перейти в закрытый канал", url=CLUB_CHANNEL_URL)]
            ]
        )
        await message.answer(
            "Вот ссылка на наш закрытый канал Mom's Club:",
            reply_markup=keyboard
        )
    else:
        # Если нет активной подписки, предлагаем оформить
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")]
            ]
        )
        await message.answer(
            "У вас нет активной подписки для доступа к закрытому каналу.\nЧтобы получить доступ, оформите подписку:",
            reply_markup=keyboard
        )


# Обработчик кнопки "Мои подписки"
@user_router.callback_query(F.data == "my_subscriptions")
async def process_my_subscriptions(callback: types.CallbackQuery):
    log_message(callback.from_user.id, "view_subscriptions", "action")
    
    # Получаем пользователя из базы данных
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем информацию о подписке
        subscription = await get_active_subscription(session, user.id)
        
        if subscription:
            # Создаем клавиатуру с кнопкой для перехода в канал
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔐 Войти в закрытый канал", url=CLUB_CHANNEL_URL)],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
            
            await safe_edit_message(
                callback,
                f"🔍 <b>Информация о подписке:</b>\n\n" +
                f"📆 Дата начала: {subscription.start_date.strftime('%d.%m.%Y')}\n" +
                f"📆 Действует до: {subscription.end_date.strftime('%d.%m.%Y')}\n\n" +
                f"Статус: ✅ Активна\n\n" +
                f"Используйте кнопку ниже для доступа в закрытый канал Mom's Club:",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Создаем клавиатуру с кнопкой для оформления подписки
            keyboard = InlineKeyboardButton(text="💸 Оформить подписку", callback_data="subscribe")
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [keyboard]
                ]
            )
            
            await safe_edit_message(
                callback,
                "❌ У вас нет активной подписки. Оформите подписку, чтобы получить доступ к закрытому каналу Mom's Club.",
                reply_markup=keyboard
            )

    await callback.answer()


# Обработчик кнопки "Назад"
@user_router.callback_query(F.data == "back_to_main")
async def process_back_to_main(callback: types.CallbackQuery):
    # Создаем инлайн-клавиатуру с кнопками для подписки
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💖 Присоединиться к Mom's Club 💖", callback_data="subscribe")]
        ]
    )
    
    await safe_edit_message(
        callback,
        text=WELCOME_TEXT,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    
    await callback.answer()


# Обработчик кнопки "Продлить подписку"
@user_router.callback_query(F.data.in_(["extend_user_subscription", "renew_subscription"]))
async def process_extend_user_subscription(callback: types.CallbackQuery, state: FSMContext):
    log_message(callback.from_user.id, "extend_user_subscription", "action")
    
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            # Проверяем есть ли пользователь
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            
            # Получаем информацию о текущей подписке
            subscription = await get_active_subscription(session, user.id)
            
            # Если включен временный режим оплаты
            if TEMPORARY_PAYMENT_MODE:
                # Формируем сообщение в зависимости от наличия подписки
                if subscription:
                    # Активная подписка есть - показываем дату окончания
                    end_date_str = subscription.end_date.strftime("%d.%m.%Y")
                    
                    message_text = f"<b>Продление подписки</b>\n\n"
                    message_text += f"У тебя есть активная подписка до <b>{end_date_str}</b>.\n\n"
                    message_text += get_payment_notice()
                else:
                    # Активной подписки нет - предлагаем оформить новую
                    message_text = "<b>Подписка на Mom's Club</b>\n\n"
                    message_text += "У тебя нет активной подписки.\n\n"
                    message_text += get_payment_notice()
                
                # Получаем клавиатуру для временного режима
                logger.info(f"Создаем клавиатуру с префиксом 'extend_' в process_extend_user_subscription")
                keyboard = get_payment_method_markup("extend_")
                logger.info(f"Клавиатура создана: {keyboard}")
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Отправляем новое сообщение
                    await callback.message.answer(
                        message_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    # В случае ошибки отправляем без удаления
                    logger.error(f"Ошибка при отправке временного уведомления в process_extend_user_subscription: {e}")
                    await callback.message.answer(
                        message_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    logger.error(f"Ошибка при отправке временного уведомления: {e}")
                
                # Убираем часы загрузки на кнопке
                await callback.answer()
                return
                
            # Стандартный режим - оригинальный код
            # Если есть активная подписка, сначала показываем экран подтверждения
            if subscription:
                # Вычисляем оставшиеся дни
                days_left = (subscription.end_date - datetime.now()).days
                days_text = f"{days_left} дней"
                if days_left == 1:
                    days_text = "1 день"
                elif days_left == 0:
                    days_text = "последний день"
                
                # Формируем текст подтверждения
                confirmation_text = f"""<b>Подтверждение продления подписки</b>

У вас уже есть активная подписка до: <b>{subscription.end_date.strftime('%d.%m.%Y')}</b>
Осталось: <b>{days_text}</b>

Вы уверены, что хотите продлить подписку?
Дополнительные дни будут добавлены к текущему сроку окончания.
При продлении будет обновлён тариф автоплатежа на выбранный вами."""
                
                # Кнопки подтверждения
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Да, продлить", callback_data="confirm_extension")],
                        [InlineKeyboardButton(text="❌ Нет, вернуться", callback_data="back_to_profile")]
                    ]
                )
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Отправляем запрос на подтверждение
                    await callback.message.answer(
                        confirmation_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logging.error(f"Ошибка при отправке запроса на подтверждение продления: {e}")
                    # Если не можем удалить или отправить, просто отправляем новое сообщение
                    await callback.message.answer(
                        confirmation_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                return

            # Если нет подписки, сразу показываем тарифы (эта часть не должна выполняться с текущей логикой)
            subscription_text = """<b>Выберите подходящий вам тариф доступа в Mom's Club:</b>

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам"""
            
            # Создаем инлайн-клавиатуру с кнопками разных тарифов
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_1month")],
                    [InlineKeyboardButton(text=f"2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data="payment_2months")],
                    [InlineKeyboardButton(text=f"3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data="payment_3months")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )

            # URL баннера для страницы тарифов
            banner_path = os.path.join(os.getcwd(), "media", "аватар.jpg")
            banner_photo = FSInputFile(banner_path)
            
            try:
                # Удаляем текущее сообщение
                await callback.message.delete()
                
                # Отправляем баннер с текстом и кнопками
                await callback.message.answer_photo(
                    photo=banner_photo,
                    caption=subscription_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Ошибка при отправке баннера продления подписки: {e}")
                # Если не можем удалить или отправить баннер, просто отправляем новое сообщение
                await callback.message.answer_photo(
                    photo=banner_photo,
                    caption=subscription_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
    except Exception as e:
        logging.error(f"Ошибка при обработке продления подписки: {e}")
        await callback.answer("Произошла ошибка. Пожалуйста, попробуйте позже.", show_alert=True)
    
    # Убираем часы загрузки на кнопке
    await callback.answer()

# Обработчик подтверждения продления подписки (для нового флоу с обновлением renewal_price и renewal_duration_days)
@user_router.callback_query(F.data == "confirm_extension")
async def process_confirm_extension(callback: types.CallbackQuery, state: FSMContext):
    log_message(callback.from_user.id, "confirm_extension", "action")
    
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            
            # Если у пользователя нет телефона, сначала просим его ввести
            if not user.phone:
                # Переводим в состояние ожидания телефона
                await state.set_state(PhoneStates.waiting_for_phone)
                # Сохраняем, что мы пришли из confirm_extension
                await state.update_data(came_from="confirm_extension")
                
                keyboard = ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения для запроса телефона: {e}")
                
                await callback.message.answer(
                    "📲 Для продления подписки Mom's Club нужно указать номер телефона. Мы используем его только для отправки чеков об оплате и связи по вопросам подписки.\n\nПожалуйста, нажми кнопку ниже и отправь свой номер:",
                    reply_markup=keyboard
                )
                return
            
            # Получаем информацию о текущей подписке (для текста)
            subscription = await get_active_subscription(session, user.id)
            
            # Формируем текст с упоминанием текущей подписки
            if subscription:
                # Вычисляем оставшиеся дни
                days_left = (subscription.end_date - datetime.now()).days
                days_text = f"{days_left} дней"
                if days_left == 1:
                    days_text = "1 день"
                elif days_left == 0:
                    days_text = "последний день"
                
                # Формируем текст с упоминанием текущей подписки
                subscription_text = f"""<b>Продление подписки в Mom's Club</b>

🔍 <b>Информация о текущей подписке:</b>
📆 Действует до: {subscription.end_date.strftime('%d.%m.%Y')}
⏳ Осталось: {days_text}

<b>Выберите тариф для продления:</b>
При продлении указанное количество дней будет добавлено к текущей дате окончания подписки.
Выбранный тариф будет использоваться для будущих автоплатежей.

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам"""
            else:
                # Если нет подписки (не должно происходить), используем стандартный текст
                subscription_text = """<b>Выберите подходящий вам тариф доступа в Mom's Club:</b>

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам"""
            
            # Создаем инлайн-клавиатуру с кнопками разных тарифов
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_extend_1month")],
                    [InlineKeyboardButton(text=f"2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data="payment_extend_2months")],
                    [InlineKeyboardButton(text=f"3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data="payment_extend_3months")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
            
            # URL баннера для страницы тарифов
            banner_path = os.path.join(os.getcwd(), "media", "аватар.jpg")
            banner_photo = FSInputFile(banner_path)
            
            try:
                # Удаляем текущее сообщение
                await callback.message.delete()
                
                # Отправляем баннер с текстом и кнопками
                await callback.message.answer_photo(
                    photo=banner_photo,
                    caption=subscription_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logging.error(f"Ошибка при отправке баннера продления подписки: {e}")
                # Если не можем удалить или отправить баннер, просто отправляем новое сообщение
                await callback.message.answer_photo(
                    photo=banner_photo,
                    caption=subscription_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
    except Exception as e:
        logging.error(f"Ошибка при обработке подтверждения продления: {e}")
        await callback.answer("Произошла ошибка. Пожалуйста, попробуйте позже.", show_alert=True)
    
    # Убираем часы загрузки на кнопке
    await callback.answer()


# Обработчик нажатия кнопки "Личный кабинет"
@user_router.message(lambda message: message.text in ["🎀 Личный кабинет", "Личный кабинет"])
async def process_profile(message: types.Message):
    log_message(message.from_user.id, "profile", "command")
    
    
    from database.crud import get_user_by_telegram_id, get_active_subscription, has_active_subscription
    from datetime import datetime
    
    # Получаем пользователя из базы данных
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        
        if user:
            # --- Construct display name ---
            name_parts = []
            if user.first_name:
                name_parts.append(user.first_name)
            if user.last_name:
                name_parts.append(user.last_name)
            full_name = " ".join(name_parts).strip()

            if user.username:
                # Add username in parentheses if it exists
                display_name_raw = f"{full_name} (@{user.username})".strip() if full_name else f"(@{user.username})"
            else:
                # Otherwise, just use the full name
                display_name_raw = full_name

            # Fallback if all fields are empty
            if not display_name_raw:
                display_name_raw = 'Участник'

            user_name_escaped = escape_markdown_v2(display_name_raw)
            # --- End construct display name ---
            
            # Получаем информацию о подписке
            subscription = await get_active_subscription(session, user.id)
            
            # URL баннера для личного кабинета
            banner_path = os.path.join(os.getcwd(), "media", "личныйкабинет.jpg")
            banner_photo = FSInputFile(banner_path)
            
            if subscription:
                # Форматируем даты для красивого отображения с экранированием
                start_date = escape_markdown_v2(subscription.start_date.strftime("%d.%m.%Y"))
                end_date = escape_markdown_v2(subscription.end_date.strftime("%d.%m.%Y"))
                
                # Рассчитываем оставшиеся дни
                days_left = (subscription.end_date - datetime.now()).days
                days_text = f"{days_left} дней"
                if days_left == 1:
                    days_text = "1 день"
                elif days_left == 0:
                    days_text = "последний день"
                elif days_left < 0:
                    days_text = "истекла"
                
                days_text = escape_markdown_v2(days_text)
                
                # Новый формат текста
                profile_text = f"""🎀 *Добро пожаловать в личный кабинет\\!*

👋 Рады видеть вас, {user_name_escaped}

Выберите нужный пункт в меню ниже — всё под рукой"""
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)],
                        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="manage_subscription")],
                        [InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="referral_program")],
                        [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo_code")],
                        [InlineKeyboardButton(text="📅 Указать дату рождения", callback_data="set_birthday")],
                        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")]
                    ]
                )
                # Отправляем баннер с подписью и кнопками
                await message.answer_photo(
                    photo=banner_photo,
                    caption=profile_text,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
            else:
                # Новый формат текста для случая без подписки
                profile_text = f"""🎀 *Добро пожаловать в личный кабинет\\!*

👋 Рады видеть вас, {user_name_escaped}

❌ *У вас нет активной подписки*

Для доступа к закрытому каналу Mom's Club и реферальной программе оформите подписку\\.
Вы также можете активировать промокод, если он у вас есть"""
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")],
                        [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo_code")],
                        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")]
                    ]
                )
                
                # Отправляем баннер с подписью и кнопками
                await message.answer_photo(
                    photo=banner_photo,
                    caption=profile_text,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
        else:
            # Если по какой-то причине пользователь не найден
            await message.answer(
                "⚠️ Ошибка: информация о пользователе не найдена.\n"
                "Пожалуйста, перезапустите бота командой /start"
            )

# Новый обработчик для кнопки "Отзывы"
@user_router.message(lambda message: message.text in ["✨ Отзывы", "Отзывы"])
async def process_reviews(message: types.Message):
    """
    Обработчик кнопки "Отзывы".
    Отправляет пользователю карусель с отзывами от участников клуба.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил просмотр отзывов")

    # Путь к папке с отзывами
    reviews_folder = os.path.join(os.getcwd(), "media", "reminders")
    
    # Проверяем, существует ли папка
    if not os.path.exists(reviews_folder):
        logger.error(f"Папка с отзывами не найдена: {reviews_folder}")
        await message.answer("Упс! Отзывы временно недоступны. Пожалуйста, попробуйте позже.")
        return
    
    # Пути к фотографиям отзывов
    photo_paths = [
        os.path.join(reviews_folder, "1.jpg"),
        os.path.join(reviews_folder, "2.jpg"),
        os.path.join(reviews_folder, "3.jpg"),
        os.path.join(reviews_folder, "4.jpg"),
        os.path.join(reviews_folder, "5.jpg"),
        os.path.join(reviews_folder, "6.jpg")
    ]
    
    # Проверяем наличие фотографий
    available_photos = [path for path in photo_paths if os.path.exists(path)]
    if not available_photos:
        logger.warning("Не найдены фотографии отзывов")
        await message.answer("Извините, фотографии отзывов не найдены. Мы уже работаем над этим!")
        return
    
    
    # Индекс первого фото и общее количество
    current_index = 0
    total_photos = len(available_photos)
    
    # Создаем клавиатуру с кнопками навигации
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"review_prev_{current_index}"),
                InlineKeyboardButton(text=f"{current_index + 1}/{total_photos}", callback_data="review_info"),
                InlineKeyboardButton(text="Вперед ▶️", callback_data=f"review_next_{current_index}")
            ],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="review_close")]
        ]
    )
    
    # Подпись к фото
    caption = f"<b>🌸 Тут собраны отзывы от участниц Mom's Club</b>\n\n<i>Используй клавиатуру \"Вперед\" и \"Назад\" что бы листать и увидеть отзывы ✨</i>"
    
    try:
        # Отправляем первое фото с кнопками навигации
        with open(available_photos[current_index], 'rb') as photo_file:
            sent_message = await message.answer_photo(
                photo=FSInputFile(available_photos[current_index]),
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
        # Сохраняем ID сообщения и фотографии для нашей карусели
        user_data = {
            "user_id": message.from_user.id,
            "message_id": sent_message.message_id,
            "photo_paths": available_photos,
            "current_index": current_index
        }
        
        # Сохраняем данные для последующего использования в callback-обработчиках
        # Можно использовать кэш или БД, если поддерживается серверная часть
        # В этом примере мы используем временное решение - глобальную переменную
        # В реальном коде лучше использовать Redis или другой механизм хранения состояния
        if not hasattr(process_reviews, "user_carousels"):
            process_reviews.user_carousels = {}
        
        process_reviews.user_carousels[message.from_user.id] = user_data
        
    except Exception as e:
        logger.error(f"Ошибка при отправке отзывов пользователю {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при загрузке отзывов. Пожалуйста, попробуйте позже.")


# Обработчик для кнопки "Вперед" в карусели отзывов
@user_router.callback_query(lambda c: c.data.startswith("review_next_"))
async def process_review_next(callback: types.CallbackQuery):
    try:
        # Получаем данные текущего пользователя и его карусели
        if not hasattr(process_reviews, "user_carousels"):
            await callback.answer("Данные просмотра отзывов не найдены. Начните просмотр заново.")
            return
            
        user_carousels = process_reviews.user_carousels
        user_id = callback.from_user.id
        
        if user_id not in user_carousels:
            await callback.answer("Ваша сессия просмотра отзывов истекла. Начните просмотр заново.")
            return
            
        # Получаем данные карусели пользователя
        carousel_data = user_carousels[user_id]
        current_index = carousel_data["current_index"]
        photo_paths = carousel_data["photo_paths"]
        total_photos = len(photo_paths)
        
        # Вычисляем индекс следующего фото
        next_index = (current_index + 1) % total_photos
        
        # Обновляем индекс в данных
        carousel_data["current_index"] = next_index
        user_carousels[user_id] = carousel_data
        
        # Формируем новую клавиатуру
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="◀️ Назад", callback_data=f"review_prev_{next_index}"),
                    InlineKeyboardButton(text=f"{next_index + 1}/{total_photos}", callback_data="review_info"),
                    InlineKeyboardButton(text="Вперед ▶️", callback_data=f"review_next_{next_index}")
                ],
                [InlineKeyboardButton(text="❌ Закрыть", callback_data="review_close")]
            ]
        )
        
        # Подпись к фото
        caption = f"<b>🌸 Тут собраны отзывы от участниц Mom's Club</b>\n\n<i>Используй клавиатуру \"Вперед\" и \"Назад\" что бы листать и увидеть все отзывы ✨</i>"
        
        # Редактируем сообщение, заменяя фото и обновляя клавиатуру
        await callback.message.edit_media(
            media=types.InputMediaPhoto(
                media=FSInputFile(photo_paths[next_index]),
                caption=caption,
                parse_mode="HTML"
            ),
            reply_markup=keyboard
        )
        
        await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при переходе к следующему отзыву: {e}")
        await callback.answer("Произошла ошибка при смене отзыва")


# Обработчик для кнопки "Назад" в карусели отзывов
@user_router.callback_query(lambda c: c.data.startswith("review_prev_"))
async def process_review_prev(callback: types.CallbackQuery):
    try:
        # Получаем данные текущего пользователя и его карусели
        if not hasattr(process_reviews, "user_carousels"):
            await callback.answer("Данные просмотра отзывов не найдены. Начните просмотр заново.")
            return
            
        user_carousels = process_reviews.user_carousels
        user_id = callback.from_user.id
        
        if user_id not in user_carousels:
            await callback.answer("Ваша сессия просмотра отзывов истекла. Начните просмотр заново.")
            return
            
        # Получаем данные карусели пользователя
        carousel_data = user_carousels[user_id]
        current_index = carousel_data["current_index"]
        photo_paths = carousel_data["photo_paths"]
        total_photos = len(photo_paths)
        
        # Вычисляем индекс предыдущего фото
        prev_index = (current_index - 1) % total_photos
        
        # Обновляем индекс в данных
        carousel_data["current_index"] = prev_index
        user_carousels[user_id] = carousel_data
        
        # Формируем новую клавиатуру
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="◀️ Назад", callback_data=f"review_prev_{prev_index}"),
                    InlineKeyboardButton(text=f"{prev_index + 1}/{total_photos}", callback_data="review_info"),
                    InlineKeyboardButton(text="Вперед ▶️", callback_data=f"review_next_{prev_index}")
                ],
                [InlineKeyboardButton(text="❌ Закрыть", callback_data="review_close")]
            ]
        )
        
        # Подпись к фото
        caption = f"<b>🌸 Тут собраны отзывы от участниц Mom's Club</b>\n\n<i>Используй клавиатуру \"Вперед\" и \"Назад\" что бы листать и увидеть все отзывы ✨</i>"
        
        # Редактируем сообщение, заменяя фото и обновляя клавиатуру
        await callback.message.edit_media(
            media=types.InputMediaPhoto(
                media=FSInputFile(photo_paths[prev_index]),
                caption=caption,
                parse_mode="HTML"
            ),
            reply_markup=keyboard
        )
        
        await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при переходе к предыдущему отзыву: {e}")
        await callback.answer("Произошла ошибка при смене отзыва")


# Обработчик для кнопки "Закрыть" в карусели отзывов
@user_router.callback_query(lambda c: c.data == "review_close")
async def process_review_close(callback: types.CallbackQuery):
    try:
        # Удаляем сообщение с каруселью
        await callback.message.delete()
        
        # Если нужно, очищаем данные карусели пользователя
        if hasattr(process_reviews, "user_carousels"):
            user_id = callback.from_user.id
            if user_id in process_reviews.user_carousels:
                del process_reviews.user_carousels[user_id]
        
        await callback.answer("Просмотр отзывов завершен")
        
    except Exception as e:
        logger.error(f"Ошибка при закрытии просмотра отзывов: {e}")
        await callback.answer("Произошла ошибка")


# Обработчик для кнопки с информацией о текущем отзыве
@user_router.callback_query(lambda c: c.data == "review_info")
async def process_review_info(callback: types.CallbackQuery):
    await callback.answer("Это индикатор текущей позиции в галерее отзывов")


# Обработчик кнопки "💕Написать мне"
@user_router.message(lambda message: message.text == "💕Написать мне")
async def process_write_to_me(message: types.Message):
    """
    Обработчик кнопки "Написать мне".
    Отправляет сообщение с информацией и кнопкой для связи с Полиной.
    """
    # Создаем кнопку для перехода в Telegram
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💌 Написать Полине", url="https://t.me/polinadmitrenkoo")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_write_me")]
        ]
    )
    
    # Текст с форматированием
    text = (
        "<b>🌸 Если остались вопросы про клуб</b> — напиши мне, я с радостью всё "
        "объясню и поддержу 🤍\n\n"
        "<i>Буду рада твоему сообщению в Telegram</i>"
    )
    
    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# Обработчик кнопки закрытия сообщения "Написать мне"
@user_router.callback_query(lambda c: c.data == "close_write_me")
async def close_write_me_message(callback: types.CallbackQuery):
    """Закрывает сообщение с контактами Полины"""
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при закрытии сообщения 'Написать мне': {e}")
    
    await callback.answer()

# Обработчик возврата в профиль
@user_router.callback_query(lambda c: c.data == "back_to_profile")
async def process_back_to_profile(callback_query: types.CallbackQuery):
    log_message(callback_query.from_user.id, "back_to_profile", "callback")
    
    
    from database.crud import get_user_by_telegram_id, get_active_subscription, has_active_subscription
    from datetime import datetime
    
    # Получаем пользователя из базы данных
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback_query.from_user.id)
        
        if user:
            # --- Construct display name ---
            name_parts = []
            if user.first_name:
                name_parts.append(user.first_name)
            if user.last_name:
                name_parts.append(user.last_name)
            full_name = " ".join(name_parts).strip()

            if user.username:
                # Add username in parentheses if it exists
                display_name_raw = f"{full_name} (@{user.username})".strip() if full_name else f"(@{user.username})"
            else:
                # Otherwise, just use the full name
                display_name_raw = full_name

            # Fallback if all fields are empty
            if not display_name_raw:
                display_name_raw = 'Участник'

            user_name_escaped = escape_markdown_v2(display_name_raw)
            # --- End construct display name ---
            
            # Получаем информацию о подписке
            subscription = await get_active_subscription(session, user.id)
            
            # URL баннера для личного кабинета
            banner_path = os.path.join(os.getcwd(), "media", "личныйкабинет.jpg")
            banner_photo = FSInputFile(banner_path)
            
            if subscription:
                # Форматируем даты для красивого отображения с экранированием
                start_date = escape_markdown_v2(subscription.start_date.strftime("%d.%m.%Y"))
                end_date = escape_markdown_v2(subscription.end_date.strftime("%d.%m.%Y"))
                
                # Рассчитываем оставшиеся дни
                days_left = (subscription.end_date - datetime.now()).days
                days_text = f"{days_left} дней"
                if days_left == 1:
                    days_text = "1 день"
                elif days_left == 0:
                    days_text = "последний день"
                elif days_left < 0:
                    days_text = "истекла"
                
                days_text = escape_markdown_v2(days_text)
                
                # Новый формат текста
                profile_text = f"""🎀 *Добро пожаловать в личный кабинет\\!*

👋 Рады видеть вас, {user_name_escaped}

Выберите нужный пункт в меню ниже — всё под рукой"""
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)],
                        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="manage_subscription")],
                        [InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="referral_program")],
                        [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo_code")],
                        [InlineKeyboardButton(text="📅 Указать дату рождения", callback_data="set_birthday")],
                        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")]
                    ]
                )
                
                # Отправляем баннер с подписью и кнопками
                await callback_query.message.answer_photo(
                    photo=banner_photo,
                    caption=profile_text,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
                
                # Удаляем предыдущее сообщение
                await callback_query.message.delete()
                # Отвечаем на callback_query, чтобы убрать часы загрузки
                await callback_query.answer()
            else:
                # Новый формат текста для случая без подписки
                profile_text = f"""🎀 *Добро пожаловать в личный кабинет\\!*

👋 Рады видеть вас, {user_name_escaped}

❌ *У вас нет активной подписки*

Для доступа к закрытому каналу Mom's Club и реферальной программе оформите подписку\\.
Вы также можете активировать промокод, если он у вас есть"""
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")],
                        [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="enter_promo_code")],
                        [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")]
                    ]
                )
                
                # Отправляем баннер с подписью и кнопками
                await callback_query.message.answer_photo(
                    photo=banner_photo,
                    caption=profile_text,
                    reply_markup=keyboard,
                    parse_mode="MarkdownV2"
                )
                
                # Удаляем предыдущее сообщение
                await callback_query.message.delete()
                # Отвечаем на callback_query, чтобы убрать часы загрузки
                await callback_query.answer()
        else:
            # Если по какой-то причине пользователь не найден
            await callback_query.message.answer(
                "⚠️ Ошибка: информация о пользователе не найдена.\n"
                "Пожалуйста, перезапустите бота командой /start"
            )
            await callback_query.answer()


# Обработчик кнопки "Закрыть"
@user_router.callback_query(F.data == "close_message")
async def process_close_message(callback: types.CallbackQuery):
    # Удаляем сообщение, в котором была нажата кнопка
    await callback.message.delete()
    # Отвечаем на коллбэк, чтобы убрать часы загрузки
    await callback.answer()


# Добавляем команду для доступа к профилю
@user_router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    # Перенаправляем на обработчик кнопки профиля
    await process_profile(message)


# Обработчик нажатия кнопки "Реферальная программа"
@user_router.callback_query(F.data == "referral_program")
async def process_referral_program(callback: types.CallbackQuery):
    log_message(callback.from_user.id, "referral_program", "action")
    
    
    from database.crud import get_user_by_telegram_id, has_active_subscription, create_referral_code
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Проверяем, есть ли активная подписка
        has_subscription = await has_active_subscription(session, user.id)
        
        # Удаляем текущее сообщение с баннером
        try:
            await callback.message.delete()
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения в process_referral_program: {e}")
        
        if not has_subscription:
            # Если нет активной подписки, отправляем уведомление
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💸 Оформить подписку", callback_data="subscribe")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
            
            # Отправляем новое сообщение вместо редактирования
            await callback.message.answer(
                "🤝 <b>Реферальная программа</b>\n\n"
                "⚠️ Для участия в реферальной программе необходимо иметь активную подписку.\n\n"
                "Оформите подписку, чтобы получить доступ к реферальной программе и " 
                "зарабатывать дополнительные дни подписки, приглашая друзей.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return
        
        # Генерируем или получаем реферальный код
        referral_code = await create_referral_code(session, user.id)
        
        if not referral_code:
            await callback.answer("Ошибка при создании реферального кода", show_alert=True)
            return
        
        # Формируем реферальную ссылку
        bot_username = (await callback.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start=ref_{referral_code}"
        
        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")]
            ]
        )
        
        # Отправляем новое сообщение вместо редактирования
        await callback.message.answer(
            "🤝 <b>Реферальная программа</b>\n\n"
            "Приглашайте друзей и получайте бонусные дни подписки!\n\n"
            "📱 <b>Как это работает:</b>\n"
            "1️⃣ Отправьте свою реферальную ссылку друзьям\n"
            "2️⃣ Когда друг перейдет по ссылке и оформит подписку\n"
            "3️⃣ Вы и ваш друг получите <b>+7 дней</b> к вашим подпискам 🎁\n\n"
            f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{referral_link}</code>\n\n"
            "Скопируйте эту ссылку и поделитесь с друзьями! 💌",
            reply_markup=keyboard,
            parse_mode="HTML"
        )


# Обработчик копирования реферальной ссылки
@user_router.callback_query(F.data.startswith("copy_link:"))
async def process_copy_link(callback: types.CallbackQuery):
    # Извлекаем ссылку из callback data
    link = callback.data.split(":", 1)[1]
    
    await callback.answer("Ссылка скопирована! Отправьте её друзьям.", show_alert=True)


# --- Обработчики промокодов ---

# Обработчик кнопки "Ввести промокод"
@user_router.callback_query(F.data == "enter_promo_code")
async def enter_promo_code(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
        ]
    )
    await callback.message.answer("✨ Пожалуйста, введите ваш промокод или нажмите «Назад» для отмены:", reply_markup=keyboard)
    await state.set_state(PromoCodeStates.waiting_for_promo_code)
    await callback.answer()

# Обработчик ввода промокода
@user_router.message(StateFilter(PromoCodeStates.waiting_for_promo_code))
async def process_promo_code_input(message: types.Message, state: FSMContext):
    promo_code_text = message.text.strip().upper()
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} ввел промокод: {promo_code_text}")

    async with AsyncSessionLocal() as session:
        db_user = await get_user_by_telegram_id(session, user_id)
        if not db_user:
            await message.answer("⚠️ Произошла ошибка. Не удалось найти информацию о вас в базе данных.")
            await state.clear()
            return

        # 1. Ищем промокод
        promo_code = await get_promo_code_by_code(session, promo_code_text)

        # 2. Проверяем, найден ли и активен
        if not promo_code or not promo_code.is_active:
            await message.answer("❌ Промокод не найден или неактивен. Проверьте правильность ввода.")
            await state.clear()
            return

        # 3. Проверяем срок действия
        if promo_code.expiry_date and promo_code.expiry_date < datetime.now():
            await message.answer("❌ Срок действия этого промокода истек.")
            await state.clear()
            return

        # 4. Проверяем лимит использований
        if promo_code.max_uses is not None and promo_code.current_uses >= promo_code.max_uses:
            await message.answer("❌ К сожалению, лимит использования этого промокода исчерпан.")
            await state.clear()
            return

        # 5. Проверяем, использовал ли уже юзер
        already_used = await has_user_used_promo_code(session, db_user.id, promo_code.id)
        if already_used:
            await message.answer("❌ Вы уже использовали этот промокод ранее.")
            await state.clear()
            return

        # --- Все проверки пройдены, применяем промокод --- 
        try:
            if promo_code.discount_type == 'days':
                bonus_days = promo_code.value
                
                # Применяем дни (создает или продлевает подписку)
                subscription = await apply_promo_code_days(session, db_user.id, bonus_days)
                
                if not subscription:
                    # Это не должно произойти, но на всякий случай
                    logger.error(f"Ошибка: apply_promo_code_days вернул None для user {db_user.id} и промокода {promo_code_text}")
                    await message.answer("⚠️ Произошла ошибка при применении промокода.")
                    await state.clear()
                    return

                # Отмечаем использование промокода
                await use_promo_code(session, db_user.id, promo_code.id)
                
                # Формируем сообщение об успехе
                end_date_formatted = subscription.end_date.strftime("%d.%m.%Y")
                success_text = (
                    f"🎉 Промокод *{escape_markdown_v2(promo_code.code)}* успешно активирован\\!\n\n"
                    f"🎁 Вам добавлено *{bonus_days} дней* подписки\\.\n"
                    f"Теперь ваша подписка активна до *{escape_markdown_v2(end_date_formatted)}*\\.\n\n"
                    f"Добро пожаловать в клуб\\!"
                )
                
                # Добавляем кнопку перехода в канал, если есть активная подписка
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)],
                    [InlineKeyboardButton(text="🎀 В личный кабинет", callback_data="back_to_profile")]
                ])

                await message.answer(success_text, reply_markup=keyboard, parse_mode="MarkdownV2")
                await state.clear()
                logger.info(f"Промокод {promo_code_text} успешно применен для пользователя {user_id}")

                # >>> НАЧАЛО БЛОКА УВЕДОМЛЕНИЯ АДМИНОВ <<<
                try:
                    # Получаем полное имя пользователя
                    user_fullname = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
                    if not user_fullname:
                        user_fullname = f"ID: {user_id}"
                        
                    admin_notification_text = (
                        f"🎁 <b>Использован промокод!</b>\n\n"
                        f"👤 Пользователь: {user_fullname} (@{message.from_user.username or 'нет username'})\n"
                        f"🎫 Промокод: Код: {promo_code.code}, Тип: {promo_code.discount_type}, Значение: {promo_code.value}\n"
                        f"📆 Новый срок действия: до {end_date_formatted}\n\n"
                        f"✅ Подписка успешно обновлена/создана!"
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await message.bot.send_message(admin_id, admin_notification_text, parse_mode="HTML")
                        except Exception as admin_send_err:
                            logger.error(f"Не удалось отправить уведомление админу {admin_id} о промокоде {promo_code.code}: {admin_send_err}")
                except Exception as notify_err:
                    logger.error(f"Ошибка при формировании/отправке уведомления админам о промокоде {promo_code.code}: {notify_err}")
                # >>> КОНЕЦ БЛОКА УВЕДОМЛЕНИЯ АДМИНОВ <<<

            else:
                # Если в будущем появятся другие типы скидок
                await message.answer("❌ Неподдерживаемый тип промокода.")
                logger.warning(f"Попытка использовать промокод {promo_code_text} с неподдерживаемым типом {promo_code.discount_type}")
                await state.clear()

        except Exception as e:
            # Безопасно логируем ошибку, даже если promo_code_text не определен
            log_message_text = "Неизвестный промокод"
            if 'promo_code_text' in locals():
                log_message_text = promo_code_text
            logger.error(f"Ошибка при применении промокода '{log_message_text}' для пользователя {user_id}: {e}", exc_info=True)
            await message.answer("⚠️ Произошла серьезная ошибка при применении промокода. Свяжитесь с поддержкой.")
            await state.clear()

# Обработчик отмены ввода промокода
@user_router.callback_query(F.data == "back_to_profile", StateFilter(PromoCodeStates.waiting_for_promo_code))
async def cancel_promo_code_input(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Ввод промокода отменен")
    await process_back_to_profile(callback)

# --- Конец обработчиков промокодов ---

# --- Обработчик кнопки "Управление подпиской" ---

@user_router.callback_query(F.data == "manage_subscription")
async def process_manage_subscription(callback: types.CallbackQuery):
    logger.info(f"[MANAGE_SUB] User {callback.from_user.id} called manage_subscription.")
    log_message(callback.from_user.id, "manage_subscription", "action")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            logger.warning(f"[MANAGE_SUB] User {callback.from_user.id} not found in DB.")
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        active_sub = await get_active_subscription(session, user.id)
        if not active_sub:
            logger.info(f"[MANAGE_SUB] User {callback.from_user.id} has no active subscription. Redirecting to profile.")
            await callback.answer("Активная подписка не найдена. Возврат в профиль...", show_alert=False)
            await process_back_to_profile(callback)
            return

        end_date_str = active_sub.end_date.strftime("%d.%m.%Y")
        # Автопродление активно, если is_recurring_active=True
        is_autorenewal_active = user.is_recurring_active
        autorenewal_status_text = "Включено ✅" if is_autorenewal_active else "Отключено ❌"

        # Экранируем динамические части
        escaped_end_date = escape_markdown_v2(end_date_str)
        escaped_autorenewal_status = escape_markdown_v2(autorenewal_status_text)
        escaped_start_date = escape_markdown_v2(active_sub.start_date.strftime("%d.%m.%Y"))

        # Формируем блок информации о подписке
        profile_info_text = f"🗓 Подписка оформлена: *{escaped_start_date}*\n"
        profile_info_text += f"📆 Действует до: *{escaped_end_date}*\n"

        days_left_for_profile = (active_sub.end_date - datetime.now()).days
        if days_left_for_profile == 1:
            days_text_for_profile = "1 день"
        elif days_left_for_profile == 0:
            days_text_for_profile = "последний день"
        elif days_left_for_profile < 0:
            days_text_for_profile = "истекла"
        else:
            days_text_for_profile = f"{days_left_for_profile} дней"
        profile_info_text += f"⏳ Осталось: *{escape_markdown_v2(days_text_for_profile)}*\n"
        profile_info_text += f"🔐 Статус подписки: *Активна* ✅\n\n"

        manage_text = f"⚙️ *Управление подпиской Mom's Club*\n\n"
        manage_text += profile_info_text
        manage_text += f"🔄 Статус автопродления: *{escaped_autorenewal_status}*\n\n"

        if not is_autorenewal_active:
            # Показываем информацию о возможности включения
            info_text = "ℹ️ Вы можете включить автопродление для автоматического продления подписки."
            manage_text += escape_markdown_v2(info_text) + "\n\n"
        else:
            info_text = "✅ Ваша подписка будет автоматически продлеваться."
            manage_text += escape_markdown_v2(info_text) + "\n\n"

        inline_keyboard_buttons = []
        
        # Основная кнопка переключения автопродления
        if is_autorenewal_active:
            inline_keyboard_buttons.append([InlineKeyboardButton(text="🚫 Отключить автопродление", callback_data="disable_autorenewal")])
        else:
            # Для Prodamus всегда показываем кнопку включения
            # Карта может быть сохранена в профиле Prodamus
            inline_keyboard_buttons.append([InlineKeyboardButton(text="✅ Включить автопродление", callback_data="enable_autorenewal")])
        
        # Только кнопка "Назад в профиль" - убираем ручное продление
        inline_keyboard_buttons.append([InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard_buttons)

        try:
            await callback.message.answer(
                manage_text,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            logger.info(f"[MANAGE_SUB] New message sent for user {callback.from_user.id}.")
            try:
                await callback.message.delete()
                logger.info(f"[MANAGE_SUB] Original message (possibly with photo) deleted for user {callback.from_user.id}.")
            except Exception as e_delete:
                logger.warning(f"[MANAGE_SUB] Could not delete original message for user {callback.from_user.id}: {e_delete}")
        except Exception as e:
            logger.error(f"[MANAGE_SUB] Error sending new message for user {callback.from_user.id}: {e}", exc_info=True)
            try:
                error_escaped_text = escape_markdown_v2("Произошла ошибка при отображении информации о подписке. Попробуйте позже.")
                await callback.message.answer(error_escaped_text, parse_mode="MarkdownV2")
                await callback.message.delete()
                logger.info(f"[MANAGE_SUB] Deleted original message after sending fallback error for user {callback.from_user.id}.")
            except Exception as e_fallback:
                logger.error(f"[MANAGE_SUB] Error sending fallback error message or deleting original message for user {callback.from_user.id}: {e_fallback}", exc_info=True)

    try:
        await callback.answer()
        logger.info(f"[MANAGE_SUB] Final callback.answer() sent for user {callback.from_user.id}.")
    except Exception as e:
        logger.error(f"[MANAGE_SUB] Error on final callback.answer() for user {callback.from_user.id}: {e}", exc_info=True)

    # Обработчик кнопки "Отключить автопродление"
@user_router.callback_query(F.data == "disable_autorenewal")
async def process_disable_autorenewal(callback: types.CallbackQuery): # Убран bot_param
    logger.info(f"[DISABLE_AUTORENEWAL] User {callback.from_user.id} called disable_autorenewal.")
    log_message(callback.from_user.id, "disable_autorenewal", "action")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            logger.warning(f"[DISABLE_AUTORENEWAL] User {callback.from_user.id} not found in DB.")
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        logger.info(f"[DISABLE_AUTORENEWAL] Found user ID {user.id}, is_recurring_active={user.is_recurring_active}, yookassa_payment_method_id={user.yookassa_payment_method_id}")

        # Вызываем функцию для отключения автопродления
        logger.info(f"[DISABLE_AUTORENEWAL] Calling disable_user_auto_renewal for user {user.id}")
        success = await disable_user_auto_renewal(session, user.id)
        logger.info(f"[DISABLE_AUTORENEWAL] disable_user_auto_renewal returned: {success}")

        if success:
            logger.info(f"[DISABLE_AUTORENEWAL] Autorenewal disabled for user {user.id} in DB.")
            await callback.answer("Автопродление успешно отключено.", show_alert=False) # Краткое уведомление
            # Обновляем сообщение с информацией об управлении подпиской
            await process_manage_subscription(callback) 
        else:
            logger.error(f"[DISABLE_AUTORENEWAL] Failed to disable autorenewal for user {user.id} in DB.")
            await callback.answer("Не удалось отключить автопродление. Попробуйте позже.", show_alert=True)
            # Можно также обновить сообщение, чтобы показать актуальный (неизменившийся) статус
            await process_manage_subscription(callback)

@user_router.callback_query(F.data == "enable_autorenewal")
async def process_enable_autorenewal(callback: types.CallbackQuery):
    """Обработчик кнопки 'Включить автопродление'"""
    logger.info(f"[ENABLE_AUTORENEWAL] User {callback.from_user.id} called enable_autorenewal.")
    log_message(callback.from_user.id, "enable_autorenewal", "action")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            logger.warning(f"[ENABLE_AUTORENEWAL] User {callback.from_user.id} not found in DB.")
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        # Вызываем функцию для включения автопродления
        success = await enable_user_auto_renewal(session, user.id)

        if success:
            logger.info(f"[ENABLE_AUTORENEWAL] Autorenewal enabled for user {user.id} in DB.")
            await callback.answer("Автопродление успешно включено.", show_alert=False)
            # Обновляем сообщение с информацией об управлении подпиской
            await process_manage_subscription(callback)
        else:
            logger.error(f"[ENABLE_AUTORENEWAL] Failed to enable autorenewal for user {user.id} in DB.")
            await callback.answer("Не удалось включить автопродление. Возможно, у вас нет сохраненной карты в системе.", show_alert=True)
            # Можно также обновить сообщение, чтобы показать актуальный (неизменившийся) статус
            await process_manage_subscription(callback)

# --- Конец обработчиков управления подпиской ---

# --- Функционал ввода даты рождения ---
@user_router.callback_query(F.data == "set_birthday")
async def process_set_birthday(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Указать дату рождения'"""
    log_message(callback.from_user.id, "set_birthday", "action")
    
    # Получаем пользователя из базы данных
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Проверяем, уже указана ли дата рождения
        if user.birthday:
            birthday_formatted = user.birthday.strftime("%d.%m.%Y")
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Изменить дату рождения", callback_data="change_birthday")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
            await callback.message.answer(
                f"📅 Ваша дата рождения: {birthday_formatted}\n\n"
                f"Вы можете изменить её, нажав на соответствующую кнопку.",
                reply_markup=keyboard
            )
        else:
            # Устанавливаем состояние ввода даты рождения
            await state.set_state(BirthdayStates.waiting_for_birthday)
            await state.update_data(user_id_db_for_birthday=user.id)
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Пропустить", callback_data="skip_birthday")],
                    [InlineKeyboardButton(text="« Отмена", callback_data="cancel_birthday")]
                ]
            )
            await callback.message.answer(
                "🎂 Пожалуйста, введите вашу дату рождения в формате ДД.ММ.ГГГГ (например, 25.08.1990).\n\n"
                "В день вашего рождения мы поздравим вас и начислим 7 дней к вашей подписке!",
                reply_markup=keyboard
            )
    
    await callback.answer()

@user_router.callback_query(F.data == "change_birthday")
async def process_change_birthday(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Изменить дату рождения'"""
    log_message(callback.from_user.id, "change_birthday", "action")
    
    # Получаем пользователя из базы данных
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
    
    # Устанавливаем состояние ввода даты рождения
    await state.set_state(BirthdayStates.waiting_for_birthday)
    await state.update_data(user_id_db_for_birthday=user.id)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="cancel_birthday")]
        ]
    )
    await callback.message.answer(
        "🎂 Пожалуйста, введите вашу новую дату рождения в формате ДД.ММ.ГГГГ (например, 25.08.1990).",
        reply_markup=keyboard
    )
    
    await callback.answer()

@user_router.callback_query(F.data == "cancel_birthday")
async def process_cancel_birthday(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Отмена' при вводе даты рождения"""
    log_message(callback.from_user.id, "cancel_birthday", "action")
    
    # Сбрасываем состояние
    current_state = await state.get_state()
    if current_state == BirthdayStates.waiting_for_birthday:
        await state.clear()
    
    # Возвращаемся в профиль
    await process_back_to_profile(callback)

@user_router.callback_query(F.data == "skip_birthday")
async def process_skip_birthday(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Пропустить' при вводе даты рождения"""
    log_message(callback.from_user.id, "skip_birthday", "action")
    
    # Сбрасываем состояние
    current_state = await state.get_state()
    if current_state == BirthdayStates.waiting_for_birthday:
        await state.clear()
    
    # Отвечаем пользователю
    await callback.message.answer(
        "Вы решили не указывать дату рождения. Вы всегда можете сделать это позже в личном кабинете.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Вернуться в личный кабинет", callback_data="back_to_profile")]
            ]
        )
    )
    await callback.answer()

@user_router.message(StateFilter(BirthdayStates.waiting_for_birthday))
async def process_birthday_input(message: types.Message, state: FSMContext):
    """Обработчик ввода даты рождения"""
    log_message(message.from_user.id, "birthday_input", "action")
    
    # Получаем введенную дату
    birthday_text = message.text.strip()
    
    # Проверяем формат даты
    try:
        birthday_date = datetime.strptime(birthday_text, "%d.%m.%Y").date()
        
        # Проверяем, что дата в прошлом
        if birthday_date >= datetime.now().date():
            await message.answer(
                "⚠️ Дата рождения должна быть в прошлом. Пожалуйста, введите корректную дату в формате ДД.ММ.ГГГГ."
            )
            return
        
        # Получаем ID пользователя из состояния
        data = await state.get_data()
        user_id_db = data.get("user_id_db_for_birthday")
        
        if not user_id_db:
            await message.answer("⚠️ Произошла ошибка. Пожалуйста, вернитесь в личный кабинет и попробуйте снова.")
            await state.clear()
            return
        
        # Сохраняем дату рождения в базе данных
        async with AsyncSessionLocal() as session:
            result = await set_user_birthday(session, user_id_db, birthday_date)
            
            if result:
                # Успешно сохранили
                await message.answer(
                    f"🎉 Спасибо! Ваша дата рождения ({birthday_text}) успешно сохранена.\n\n"
                    f"В день вашего рождения мы поздравим вас и начислим 7 дней к вашей подписке!",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 Вернуться в личный кабинет", callback_data="back_to_profile")]
                        ]
                    )
                )
            else:
                # Ошибка при сохранении
                await message.answer(
                    "⚠️ Произошла ошибка при сохранении даты рождения. Пожалуйста, попробуйте позже.",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 Вернуться в личный кабинет", callback_data="back_to_profile")]
                        ]
                    )
                )
        
        # Сбрасываем состояние
        await state.clear()
        
    except ValueError:
        # Неверный формат даты
        await message.answer(
            "⚠️ Неверный формат даты. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ (например, 25.08.1990)."
        )

# --- Конец функционала ввода даты рождения ---

    # Обработчик для тарифа 1 месяц с обновлением автопродления
@user_router.callback_query(F.data == "payment_extend_1month")
async def process_payment_extend_1month(callback: types.CallbackQuery, state: FSMContext):
        log_message(callback.from_user.id, "start_payment_extend_1month", "action")
        await process_subscription_extend_payment(
            callback, 
            state, 
            price=SUBSCRIPTION_PRICE, 
            days=SUBSCRIPTION_DAYS, 
            sub_type="momclub_subscription_1month",
            renewal_price=SUBSCRIPTION_PRICE,
            renewal_duration_days=SUBSCRIPTION_DAYS
        )


    # Обработчик для тарифа 3 месяца с обновлением автопродления
@user_router.callback_query(F.data == "payment_extend_3months")
async def process_payment_extend_3months(callback: types.CallbackQuery, state: FSMContext):
        log_message(callback.from_user.id, "start_payment_extend_3months", "action")
        await process_subscription_extend_payment(
            callback, 
            state, 
            price=SUBSCRIPTION_PRICE_3MONTHS, 
            days=SUBSCRIPTION_DAYS_3MONTHS, 
            sub_type="momclub_subscription_3months",
            renewal_price=SUBSCRIPTION_PRICE_3MONTHS,
            renewal_duration_days=SUBSCRIPTION_DAYS_3MONTHS
        )


    # Обработчик для тарифа 2 месяца с обновлением автопродления
@user_router.callback_query(F.data == "payment_extend_2months")
async def process_payment_extend_2months(callback: types.CallbackQuery, state: FSMContext):
        log_message(callback.from_user.id, "start_payment_extend_2months", "action")
        await process_subscription_extend_payment(
            callback, 
            state, 
            price=SUBSCRIPTION_PRICE_2MONTHS, 
            days=SUBSCRIPTION_DAYS_2MONTHS, 
            sub_type="momclub_subscription_2months",
            renewal_price=SUBSCRIPTION_PRICE_2MONTHS,
            renewal_duration_days=SUBSCRIPTION_DAYS_2MONTHS
        )


    # Общая функция для обработки платежей с обновлением параметров автопродления
async def process_subscription_extend_payment(callback: types.CallbackQuery, state: FSMContext, price: int, days: int, sub_type: str, renewal_price: int, renewal_duration_days: int):
        # Проверка режима технического обслуживания
        from utils.constants import DISABLE_PAYMENTS
        if DISABLE_PAYMENTS:
            await callback.answer(
                "💳 Платежи временно недоступны\n"
                "🔧 Идет обновление системы", 
                show_alert=True
            )
            return
        
        try:
            
            from database.crud import get_user_by_telegram_id, create_payment_log, has_active_subscription, update_subscription_renewal_params, get_active_subscription
            
            # Получаем данные о пользователе
            async with AsyncSessionLocal() as session:
                user = await get_user_by_telegram_id(session, callback.from_user.id)
                
                if not user:
                    await callback.answer("Пользователь не найден в базе данных", show_alert=True)
                    return

                # Если у пользователя нет телефона, сначала просим его ввести
                if not user.phone:
                    # Переводим в состояние ожидания телефона
                    await state.set_state(PhoneStates.waiting_for_phone)
                    # Сохраняем данные о тарифе и откуда пришли для возврата после ввода телефона
                    await state.update_data(
                        came_from="payment_extend", 
                        price=price, 
                        days=days, 
                        sub_type=sub_type,
                        renewal_price=renewal_price,
                        renewal_duration_days=renewal_duration_days
                    )
                    
                    keyboard = ReplyKeyboardMarkup(
                        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
                        resize_keyboard=True,
                        one_time_keyboard=True
                    )
                    
                    try:
                        # Удаляем текущее сообщение
                        await callback.message.delete()
                    except Exception as e:
                        logger.error(f"Ошибка при удалении сообщения для запроса телефона: {e}")
                    
                    await callback.message.answer(
                        "📲 Для продления подписки Mom's Club нужно указать номер телефона. Мы используем его только для отправки чеков об оплате и связи по вопросам подписки.\n\nПожалуйста, нажми кнопку ниже и отправь свой номер:",
                        reply_markup=keyboard
                    )
                    return

                # Проверяем наличие активной подписки и обновляем параметры автопродления
                active_subscription = await get_active_subscription(session, user.id)
                if active_subscription:
                    # Обновляем параметры для автопродления, даже до совершения платежа
                    # Это делается на случай, если пользователь не завершит платеж, но параметры автопродления уже будут обновлены
                    await update_subscription_renewal_params(
                        session, 
                        active_subscription.id, 
                        renewal_price=renewal_price,
                        renewal_duration_days=renewal_duration_days
                    )
                    logger.info(f"Обновлены параметры автопродления для подписки ID={active_subscription.id}: цена={renewal_price}, дни={renewal_duration_days}")

                # Создаем платеж как обычно
                payment_url, payment_id, payment_label = create_payment_link(
                    amount=price,
                    user_id=user.telegram_id,
                    description=f"Продление подписки на Mom's Club на {days} дней (username: @{user.username})",
                    sub_type=sub_type,
                    days=days,
                    phone=user.phone
                )
                
                if not payment_url or not payment_id:
                    await callback.answer("Ошибка создания платежа. Попробуйте позже.", show_alert=True)
                    return
                
                # Создаем запись о платеже
                await create_payment_log(
                    session,
                    user_id=user.id,
                    amount=price,
                    status="pending",
                    payment_method="prodamus",
                    transaction_id=payment_id,
                    details=f"Продление подписки на {days} дней (c обновлением параметров автопродления)",
                    payment_label=payment_label,
                    days=days
                )
                
                # Создаем кнопку оплаты
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💸 Оплатить подписку", url=payment_url)],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ])
                
                # Отправляем сообщение с информацией о продлении и кнопкой оплаты
                renewal_text = f"""<b>🎉 Продление подписки на Mom's Club</b>

<b>Выбранный тариф:</b> {days} дней за {price} ₽

<b>После оплаты:</b>
• Ваша подписка будет продлена
• Параметры автопродления будут обновлены

<i>Для продолжения нажмите кнопку "Оплатить подписку" ниже</i>"""
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    # Отправляем новое сообщение с информацией о платеже
                    await callback.message.answer(
                        renewal_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения о продлении: {e}")
                    # Если не удалось удалить предыдущее сообщение, просто отправляем новое
                    await callback.message.answer(
                        renewal_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    
        except Exception as e:
            logging.error(f"Ошибка в process_subscription_extend_payment: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при обработке платежа. Попробуйте позже.", show_alert=True)
        
        # Убираем часы загрузки на кнопке
        await callback.answer()

@user_router.message(StateFilter(PhoneStates.waiting_for_phone))
async def process_phone(message: types.Message, state: FSMContext):
    phone = None
    if message.contact and message.contact.phone_number:
        phone = message.contact.phone_number
    else:
        # Можно добавить парсинг текста, если пользователь ввёл номер вручную
        phone = message.text.strip()
    if not phone or len(phone) < 10:
        await message.answer("Пожалуйста, отправьте корректный номер телефона через кнопку ниже.")
        return
    
    # Сохраняем телефон в БД
    async with AsyncSessionLocal() as session:
        await update_user(session, message.from_user.id, phone=phone)
    
    # Проверяем, откуда пришел пользователь
    user_data = await state.get_data()
    came_from = user_data.get("came_from")
    
    if came_from == "payment_extend":
        # Если пришли со страницы выбора тарифа для продления, возвращаемся к оплате с сохраненными параметрами
        try:
            
            from database.crud import get_user_by_telegram_id
            
            # Получаем сохраненные данные о тарифе
            price = user_data.get("price")
            days = user_data.get("days")
            sub_type = user_data.get("sub_type")
            renewal_price = user_data.get("renewal_price")
            renewal_duration_days = user_data.get("renewal_duration_days")
            
            # Очищаем состояние перед продолжением
            await state.clear()
            
            # Создаем объект callback для передачи в функцию payment
            # Нам нужен только пользователь для идентификации
            async with AsyncSessionLocal() as session:
                user = await get_user_by_telegram_id(session, message.from_user.id)
                
                if not user:
                    await message.answer("Пользователь не найден в базе данных. Пожалуйста, начните процесс заново.")
                    return

                # Информируем пользователя, что продолжаем оформление платежа
                await message.answer("Спасибо! Ваш номер сохранён. Продолжаем оформление продления подписки...")
                
                # Создаем новое сообщение с информацией о тарифе и кнопкой оплаты
                # Получаем информацию о пользователе и подписке
                active_subscription = await get_active_subscription(session, user.id)
                
                # Создаем платеж как обычно
                payment_url, payment_id, payment_label = create_payment_link(
                    amount=price,
                    user_id=user.telegram_id,
                    description=f"Продление подписки на Mom's Club на {days} дней",
                    sub_type=sub_type,
                    days=days,
                    phone=user.phone
                )
                
                if not payment_url or not payment_id:
                    await message.answer("Ошибка создания платежа. Пожалуйста, попробуйте позже.")
                    return
                
                # Создаем запись о платеже
                await create_payment_log(
                    session,
                    user_id=user.id,
                    amount=price,
                    status="pending",
                    payment_method="prodamus",
                    transaction_id=payment_id,
                    details=f"Продление подписки на {days} дней (после ввода номера телефона)",
                    payment_label=payment_label,
                    days=days
                )
                
                # Создаем кнопку оплаты
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💸 Оплатить подписку", url=payment_url)],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ])
                
                # Отправляем сообщение с информацией о продлении и кнопкой оплаты
                renewal_text = f"""<b>🎉 Продление подписки на Mom's Club</b>

<b>Выбранный тариф:</b> {days} дней за {price} ₽

<b>После оплаты:</b>
• Ваша подписка будет продлена
• Параметры автопродления будут обновлены

<i>Для продолжения нажмите кнопку "Оплатить подписку" ниже</i>"""
                
                # Отправляем новое сообщение с информацией о платеже
                await message.answer(
                    renewal_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        except Exception as e:
            logging.error(f"Ошибка при возврате к оплате после ввода телефона: {e}", exc_info=True)
            await message.answer("Произошла ошибка. Пожалуйста, вернитесь в личный кабинет и попробуйте снова.", reply_markup=main_keyboard)
    elif came_from == "confirm_extension":
        # Если пришли со страницы продления, возвращаем обратно
        await state.clear()
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 Продолжить продление подписки", callback_data="extend_user_subscription")]
            ]
        )
        await message.answer("Спасибо! Ваш номер сохранён. Теперь вы можете продолжить продление подписки.", reply_markup=keyboard)
    else:
        # Стандартное сообщение
        await state.clear()
        await message.answer("Спасибо! Ваш номер сохранён. Теперь вы можете выбрать тариф и оплатить подписку.", reply_markup=main_keyboard)

# Добавляю обработчики для кнопок с префиксом "renew_" (в конце файла перед def register_user_handlers(dp)):
@user_router.callback_query(F.data == "renew_payment_1month")
async def process_renew_payment_1month(callback: types.CallbackQuery, state: FSMContext):
        """Обработчик оплаты 1 месяца при продлении"""
        if TEMPORARY_PAYMENT_MODE:
            # В режиме временной оплаты этот обработчик не должен срабатывать
            await callback.answer("Функция временно недоступна", show_alert=True)
            return
        await process_subscription_payment(callback, state, SUBSCRIPTION_PRICE, SUBSCRIPTION_DAYS, "1month")

@user_router.callback_query(F.data == "renew_payment_3months")
async def process_renew_payment_3months(callback: types.CallbackQuery, state: FSMContext):
        """Обработчик оплаты 3 месяцев при продлении"""
        if TEMPORARY_PAYMENT_MODE:
            # В режиме временной оплаты этот обработчик не должен срабатывать
            await callback.answer("Функция временно недоступна", show_alert=True)
            return
        await process_subscription_payment(callback, state, SUBSCRIPTION_PRICE_3MONTHS, SUBSCRIPTION_DAYS_3MONTHS, "3months")

@user_router.callback_query(F.data == "renew_payment_2months")
async def process_renew_payment_2months(callback: types.CallbackQuery, state: FSMContext):
        """Обработчик оплаты 2 месяцев при продлении"""
        if TEMPORARY_PAYMENT_MODE:
            # В режиме временной оплаты этот обработчик не должен срабатывать
            await callback.answer("Функция временно недоступна", show_alert=True)
            return
        await process_subscription_payment(callback, state, SUBSCRIPTION_PRICE_2MONTHS, SUBSCRIPTION_DAYS_2MONTHS, "2months")

    # Обработчик для кнопки "Назад" с префиксом renew_
@user_router.callback_query(F.data.startswith("renew_"))
async def process_renew_back_to_profile(callback: types.CallbackQuery):
        """Обработчик для всех кнопок с префиксом renew_"""
        try:
            logger.info(f"Вызван обработчик process_renew_back_to_profile для callback_data: {callback.data}")
            
            # В зависимости от типа callback_data делаем разное действие
            if callback.data == "renew_back_to_profile":
                # Возвращаемся в профиль
                try:
                    await callback.message.delete()
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения: {e}")
                    
                # Возвращаемся напрямую в профиль
                await process_back_to_profile(callback)
                return
            
            # Для всех других renew_ callback_data (на всякий случай)
            if TEMPORARY_PAYMENT_MODE:
                # Уведомляем пользователя, что функция временно недоступна
                await callback.answer("Функция временно недоступна, используйте ручную оплату", show_alert=True)
                return
                
        except Exception as e:
            logger.error(f"Ошибка при обработке renew callback: {e}", exc_info=True)
            await callback.answer("Произошла ошибка. Пожалуйста, напишите /start для перехода в главное меню.")

    # Добавляем прямую обработку для кнопки Назад - самый последний обработчик в файле
@user_router.callback_query(lambda c: c.data == "« Назад")
async def process_generic_back_button(callback: types.CallbackQuery):
        """Обработчик для текста кнопки '« Назад'"""
        try:
            logger.info(f"Вызван запасной обработчик кнопки Назад: {callback.data}")
            await process_back_to_profile(callback)
        except Exception as e:
            logger.error(f"Ошибка в запасном обработчике кнопки Назад: {e}", exc_info=True)
            await callback.answer("Произошла ошибка, попробуйте /start")

    # Заменяем существующий обработчик для всех callback_data с back_to_profile
@user_router.callback_query(lambda c: "back_to_profile" in c.data)
async def process_any_back_to_profile(callback: types.CallbackQuery):
        """Универсальный обработчик для всех кнопок возврата в профиль"""
        try:
            logger.info(f"Вызван универсальный обработчик возврата в профиль. callback_data={callback.data}")
            # Всегда перенаправляем на основной обработчик профиля
            await process_back_to_profile(callback)
        except Exception as e:
            logger.error(f"Ошибка в универсальном обработчике back_to_profile: {e}", exc_info=True)
            # В случае ошибки пытаемся хотя бы вернуться на главную
            await callback.answer("Произошла ошибка. Пожалуйста, напишите /start для перехода в главное меню.")

# Функция для регистрации всех обработчиков
def register_user_handlers(dp):
    dp.include_router(user_router)

# Обработчик для кнопки с информацией о текущем отзыве
@user_router.callback_query(lambda c: c.data == "review_info")
async def process_review_info(callback: types.CallbackQuery):
    await callback.answer("Это индикатор текущей позиции в галерее отзывов")
