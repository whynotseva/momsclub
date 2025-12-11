from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import os
from utils.helpers import (
    log_message, escape_markdown_v2, get_payment_method_markup, get_payment_notice, 
    safe_edit_message, format_user_error_message, 
    format_subscription_end_date, format_subscription_days_left, is_lifetime_subscription
)
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
    send_loyalty_benefit_notification_to_admins,
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
    update_user,
    create_autorenewal_cancellation_request,
    send_cancellation_request_notifications,
    get_user_payment_history,
    get_user_badges
)
from sqlalchemy import update
from sqlalchemy import select
from database.models import User, PaymentLog
from utils.payment import create_payment_link, check_payment_status
from loyalty.service import effective_discount, price_with_discount, apply_benefit_from_callback
from loyalty import calc_tenure_days, level_for_days
from loyalty.levels import get_loyalty_progress
from utils.constants import (
    CLUB_CHANNEL_URL, 
    SUBSCRIPTION_PRICE_FIRST,
    SUBSCRIPTION_PRICE,
    BADGE_NAMES_AND_DESCRIPTIONS, 
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
from utils.constants import ADMIN_IDS  # Импортируем список администраторов
import logging
from collections import defaultdict
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

# --- Состояния FSM для данных при оплате ---
class PaymentDataStates(StatesGroup):
    waiting_for_phone = State()

# --- Состояния FSM для отмены автопродления ---
class CancelRenewalStates(StatesGroup):
    waiting_for_custom_reason = State()

# --- Состояния FSM для вывода средств ---
class WithdrawalStates(StatesGroup):
    waiting_card_number = State()
    waiting_phone_number = State()
    waiting_confirmation = State()

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
        [KeyboardButton(text="❓ Частые вопросы"), KeyboardButton(text="🤎 Служба поддержки")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Обработчик команды /start
@user_router.message(Command("start"), F.chat.type == "private")
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
    
    # Извлекаем аргументы из команды /start
    ref_code = None
    show_payment_menu = False
    args = message.text.split()
    if len(args) > 1:
        arg = args[1]
        # Проверяем специальные команды
        if arg == "renew" or arg == "subscribe":
            # Deep link для продления/оформления подписки из библиотеки
            show_payment_menu = True
            logger.info(f"Получен deep link для оплаты: {arg}")
        elif arg.startswith("ref_"):
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

    # Если deep link для оплаты — сразу показываем меню тарифов
    if show_payment_menu:
        # Проверяем, есть ли активная подписка и право на бонус
        async with AsyncSessionLocal() as session:
            subscription = await get_active_subscription(session, user_id)
            bonus_text = ""
            if subscription:
                from datetime import datetime
                days_left = (subscription.end_date - datetime.now()).days
                if days_left >= 7:
                    bonus_text = f"\n\n🎁 <b>Акция!</b> Продли сейчас и получи <b>+3 дня бонусом</b>!\nОсталось {days_left} дней — успей воспользоваться 💫"
        
        tariff_text = f"""<b>💳 Продление подписки Mom's Club</b>

Выбери удобный тариф:{bonus_text}

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• комьюнити из потрясающих мам

<b>Нажми на тариф для оплаты:</b>"""

        # Используем extend_ callbacks если есть подписка (чтобы дни суммировались)
        if subscription:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"📦 1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_extend_1month")],
                    [InlineKeyboardButton(text=f"📦 2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽ 💰", callback_data="payment_extend_2months")],
                    [InlineKeyboardButton(text=f"📦 3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽ 💰", callback_data="payment_extend_3months")],
                    [InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data="promo_code")],
                ]
            )
        else:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_1month")],
                    [InlineKeyboardButton(text=f"2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data="payment_2months")],
                    [InlineKeyboardButton(text=f"3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data="payment_3months")],
                    [InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data="promo_code")],
                ]
            )
        await message.answer(tariff_text, reply_markup=keyboard, parse_mode="HTML")
        return

    # Если нет активной подписки, показываем приветственное сообщение и кнопку для оплаты
    if not has_subscription:
        # Создаем клавиатуру с кнопкой оплаты
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")]
            ]
        )
        
        # Отправляем приветственное изображение с текстом как подпись и кнопкой одним сообщением
        if os.path.exists(WELCOME_IMAGE_PATH):
            photo = FSInputFile(WELCOME_IMAGE_PATH)
            await message.answer_photo(
                photo=photo,
                caption=WELCOME_TEXT,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Если изображение не найдено, логируем ошибку и отправляем только текст с кнопкой
            logger.error(f"Приветственное изображение не найдено по пути: {WELCOME_IMAGE_PATH}.")
            # Создаем директорию, если она отсутствует
            os.makedirs(os.path.dirname(WELCOME_IMAGE_PATH), exist_ok=True)
            # Отправляем приветственный текст с кнопкой
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

        # Запрос номера телефона удален по требованию заказчицы
        # Пользователь может сразу переходить к подписке
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
        error_msg = format_user_error_message(e, "при обработке подписки")
        await callback.answer(error_msg, show_alert=True)


# Модифицируем обработчик нажатия на кнопку подписки, добавляя проверку состояния
@user_router.callback_query(F.data == "subscribe")
@user_router.callback_query(F.data == "subscribe:from_broadcast")
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
                    # НОВАЯ ЛОГИКА: Показываем возможность досрочного продления
                    from utils.early_renewal import (
                        check_early_renewal_eligibility,
                        format_subscription_status_message,
                        format_renewal_options_message
                    )
                    from datetime import datetime
                    
                    # Проверяем возможность досрочного продления
                    can_renew, reason, info = await check_early_renewal_eligibility(session, user.id)
                    
                    if can_renew and info:
                        # Показываем статус подписки и варианты продления
                        status_msg = format_subscription_status_message(
                            info['days_left'],
                            info['end_date'],
                            info['has_autopay']
                        )
                        
                        renewal_msg = format_renewal_options_message(
                            info['end_date'],
                            info['days_left'],
                            info['bonus_eligible'],
                            info['has_autopay']
                        )
                        
                        full_message = f"{status_msg}\n\n{renewal_msg}"
                        
                        # Определяем, откуда вызван
                        from_broadcast = callback.data == "subscribe:from_broadcast"
                        back_button = InlineKeyboardButton(
                            text="🔙 Назад к рассылке" if from_broadcast else "« Назад",
                            callback_data="show_broadcast_loyalty" if from_broadcast else "back_to_profile"
                        )
                        
                        # Кнопки с тарифами
                        keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text=f"📦 1 месяц — {SUBSCRIPTION_PRICE}₽", callback_data="payment_1month")],
                                [InlineKeyboardButton(text=f"📦 2 месяца — {SUBSCRIPTION_PRICE_2MONTHS}₽ 💰", callback_data="payment_2months")],
                                [InlineKeyboardButton(text=f"📦 3 месяца — {SUBSCRIPTION_PRICE_3MONTHS}₽ 💰", callback_data="payment_3months")],
                                [InlineKeyboardButton(text="🔐 Войти в канал", url=CLUB_CHANNEL_URL)],
                                [back_button]
                            ]
                        )
                        
                        try:
                            await callback.message.edit_text(
                                full_message,
                                reply_markup=keyboard,
                                parse_mode="HTML"
                            )
                        except:
                            await callback.message.answer(
                                full_message,
                                reply_markup=keyboard,
                                parse_mode="HTML"
                            )
                        
                        await callback.answer()
                        return
                    
                    # Старая логика (если не можем продлить)
                    await callback.answer("У вас уже есть доступ к каналу", show_alert=True)
                    
                    from_broadcast = callback.data == "subscribe:from_broadcast"
                    back_button = InlineKeyboardButton(text="🔙 Назад к рассылке", callback_data="show_broadcast_loyalty") if from_broadcast else InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🔐 Войти в закрытый канал", url=CLUB_CHANNEL_URL)],
                            [back_button]
                        ]
                    )
                    
                    end_date_formatted = format_subscription_end_date(subscription, escape_for_markdown=False)
                    await callback.message.answer(
                        "🎉 У вас уже есть активная подписка!\n\n" +
                        f"Подписка действует до: {end_date_formatted}\n\n" +
                        f"Нажмите на кнопку ниже, чтобы перейти в закрытый канал Mom's Club.",
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                    return
        
        # Если включен временный режим оплаты
        if TEMPORARY_PAYMENT_MODE:
            message_text = get_payment_notice()
            keyboard = get_payment_method_markup()
            
            # Если вызов из рассылки, заменяем кнопку "Назад" на "Назад к рассылке"
            from_broadcast = callback.data == "subscribe:from_broadcast"
            if from_broadcast and keyboard.inline_keyboard:
                # Заменяем последнюю кнопку "Назад" на "Назад к рассылке"
                new_keyboard = InlineKeyboardMarkup(inline_keyboard=[])
                for row in keyboard.inline_keyboard:
                    new_row = []
                    for button in row:
                        if button.callback_data == "back_to_profile":
                            new_row.append(InlineKeyboardButton(text="🔙 Назад к рассылке", callback_data="show_broadcast_loyalty"))
                        else:
                            new_row.append(button)
                    new_keyboard.inline_keyboard.append(new_row)
                keyboard = new_keyboard
            
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
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            is_first_payment = user and not user.is_first_payment_done
        
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
            # Проверяем, есть ли примененная скидка
            discount_percent = effective_discount(user)
            has_discount = discount_percent > 0
            
            # Формируем текст с информацией о скидке, если она есть
            discount_info = ""
            if has_discount:
                discount_info = f"\n\n💰 <b>Ваша персональная скидка: {discount_percent}% применена!</b>"
            
            subscription_text = f"""<b>Выберите подходящий вам тариф доступа в Mom's Club:</b>

<b>Что тебя ждёт:</b>
• доступ к закрытому каналу
• вирусные подборки Reels и постов
• фишки и лайфхаки по блогингу
• готовые идеи для съёмок
• тренды и примеры для мамского блога
• подкасты и разборы
• поддержка твоего контента
• комьюнити из потрясающих мам{discount_info}

<b>Нажми на один из вариантов, чтобы присоединиться прямо сейчас!</b>"""

        # Определяем, откуда вызван (из рассылки или из профиля)
        from_broadcast = callback.data == "subscribe:from_broadcast"
        
        # Создаем инлайн-клавиатуру с кнопками разных тарифов
        if is_first_payment:
            # Для первой оплаты показываем только 1 месяц
            back_button = InlineKeyboardButton(text="🔙 Назад к рассылке", callback_data="show_broadcast_loyalty") if from_broadcast else InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"🎁 1 месяц — {SUBSCRIPTION_PRICE_FIRST} ₽ (специальная цена)", callback_data="payment_1month")],
                    [back_button]
                ]
            )
        else:
            # Обычные тарифы
            back_button = InlineKeyboardButton(text="🔙 Назад к рассылке", callback_data="show_broadcast_loyalty") if from_broadcast else InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")
            
            # Если есть скидка, показываем цены со скидкой
            if has_discount:
                price_1month = price_with_discount(SUBSCRIPTION_PRICE, discount_percent)
                price_2months = price_with_discount(SUBSCRIPTION_PRICE_2MONTHS, discount_percent)
                price_3months = price_with_discount(SUBSCRIPTION_PRICE_3MONTHS, discount_percent)
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"1 месяц — ~~{SUBSCRIPTION_PRICE}₽~~ {price_1month}₽ (скидка {discount_percent}%)", callback_data="payment_1month")],
                        [InlineKeyboardButton(text=f"2 месяца — ~~{SUBSCRIPTION_PRICE_2MONTHS}₽~~ {price_2months}₽ (скидка {discount_percent}%)", callback_data="payment_2months")],
                        [InlineKeyboardButton(text=f"3 месяца — ~~{SUBSCRIPTION_PRICE_3MONTHS}₽~~ {price_3months}₽ (скидка {discount_percent}%)", callback_data="payment_3months")],
                        [back_button]
                    ]
                )
            else:
                # Обычные цены без скидки
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text=f"1 месяц — {SUBSCRIPTION_PRICE} ₽", callback_data="payment_1month")],
                        [InlineKeyboardButton(text=f"2 месяца — {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data="payment_2months")],
                        [InlineKeyboardButton(text=f"3 месяца — {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data="payment_3months")],
                        [back_button]
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
        error_msg = format_user_error_message(e, "при выборе тарифа подписки")
        await callback.answer(error_msg, show_alert=True)
    
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

            # Создаем платеж БЕЗ запроса телефона
            await create_payment_for_user(callback, state, user, price, days, sub_type)
    
    except Exception as e:
        logger.error(f"Ошибка при создании платежа: {e}")
        error_msg = format_user_error_message(e, "при создании платежа")
        await callback.answer(error_msg, show_alert=True)


async def create_payment_for_user(callback: types.CallbackQuery, state: FSMContext, user, price: int, days: int, sub_type: str):
    """Создает платеж для пользователя с полными данными"""
    try:
        from database.crud import create_payment_log
        
        async with AsyncSessionLocal() as session:
            # Применяем скидку лояльности ТОЛЬКО если это НЕ специальная цена первого платежа
            # Специальная цена 690₽ — это уже скидка, повторная скидка не применяется
            discount_percent = 0
            if price != SUBSCRIPTION_PRICE_FIRST:
                # Скидка применяется только к обычным ценам (990₽ и выше)
                discount_percent = effective_discount(user)
            
            final_price = price_with_discount(price, discount_percent)
            
            # Формируем описание с информацией о скидке
            description = f"Подписка на Mom's Club на {days} дней (username: @{user.username or 'Unknown'})"
            if discount_percent > 0:
                description += f" | Скидка лояльности: {discount_percent}%"
            
            payment_url, payment_id, payment_label = create_payment_link(
                amount=final_price,
                user_id=user.telegram_id,
                description=description,
                sub_type=sub_type,
                days=days,
                phone=user.phone,
                discount_percent=discount_percent
            )
            
            if payment_url and payment_id and payment_label:
                # Сохраняем только метку в state для возможной отладки
                await state.update_data(
                    payment_label=payment_label
                )
                
                # Формируем детали платежа с информацией о скидке
                details_text = f"Подписка на Mom's Club на {days} дней (username: @{user.username or 'Unknown'})"
                if discount_percent > 0:
                    details_text += f" | Скидка лояльности: {discount_percent}% (было {price}₽, стало {final_price}₽)"
                
                # Создаем запись о платеже (статус "pending")
                # Сохраняем исходную цену в amount, чтобы знать базовую цену
                payment_log_entry = await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=None,
                    amount=final_price,  # Сохраняем финальную цену со скидкой
                    status="pending",
                    payment_method="yookassa",
                    transaction_id=payment_id, # Сохраняем UUID платежа
                    details=details_text,
                    payment_label=payment_label,
                    days=days # Сохраняем количество дней
                )
                
                # Используем ID записи лога платежа для callback_data
                payment_db_id = payment_log_entry.id
                
                # Проверяем возможность оплаты балансом
                from utils.balance_payment_helpers import can_pay_with_balance, format_balance_payment_message
                
                has_enough_balance = can_pay_with_balance(user.referral_balance or 0, final_price)
                
                # Формируем клавиатуру в зависимости от баланса
                keyboard_buttons = []
                
                if has_enough_balance:
                    # Достаточно баланса - показываем обе кнопки
                    # Сокращаем sub_type для уменьшения длины callback_data
                    sub_short = sub_type.replace("momclub_subscription_", "").replace("month", "m")
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"💰 Оплатить балансом ({final_price:,}₽)",
                            callback_data=f"cbp:{final_price}:{days}:{sub_short}"
                        )
                    ])
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"💳 Оплатить картой ({final_price:,}₽)",
                            url=payment_url
                        )
                    ])
                else:
                    # Недостаточно баланса - только карта + приглашение
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"💳 Оплатить картой ({final_price:,}₽)",
                            url=payment_url
                        )
                    ])
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text="🎁 Пригласить подруг",
                            callback_data="referral_program"
                        )
                    ])
                
                keyboard_buttons.append([
                    InlineKeyboardButton(text="« Назад", callback_data="subscribe")
                ])
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
                
                # Формируем текст сообщения
                payment_text, _ = format_balance_payment_message(
                    user.referral_balance or 0,
                    final_price,
                    days,
                    discount_percent
                )
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Отправляем новое сообщение с информацией о платеже
                    await callback.message.answer(
                        payment_text,
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения о платеже: {e}")
                    error_msg = format_user_error_message(e, "при отправке информации о платеже")
                    await callback.answer(error_msg, show_alert=True)
            else:
                error_msg = format_user_error_message(Exception("Не удалось создать ссылку на оплату"), "при создании ссылки на оплату")
                await callback.answer(error_msg, show_alert=True)
                
    except Exception as e:
        logger.error(f"Ошибка при создании платежа для пользователя: {e}")
        error_msg = format_user_error_message(e, "при создании платежа")
        await callback.answer(error_msg, show_alert=True)


@user_router.callback_query(F.data.startswith("cbp:"))
async def confirm_payment_with_balance(callback: types.CallbackQuery):
    """Обработчик подтверждения оплаты подписки реферальным балансом"""
    try:
        # Парсим данные из callback (формат: cbp:price:days:sub_short[:e:renewal_price:renewal_days])
        parts = callback.data.split(":")
        price = int(parts[1])
        days = int(parts[2])
        sub_short = parts[3]
        mode = parts[4] if len(parts) >= 5 and parts[4] == "e" else "standard"
        renewal_price = int(parts[5]) if len(parts) >= 6 else None
        renewal_days = int(parts[6]) if len(parts) >= 7 else None
        
        # Восстанавливаем полный sub_type из короткого
        sub_type = f"momclub_subscription_{sub_short.replace('m', 'month')}"
        
        logger.info(f"Пользователь {callback.from_user.id} запросил подтверждение оплаты балансом: {price}₽ на {days} дней")
        
        from database.crud import get_user_by_telegram_id
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            current_balance = user.referral_balance or 0
            remaining_balance = current_balance - price
            
            # Формируем текст подтверждения
            confirmation_text = (
                f"💰 <b>Подтверждение оплаты балансом</b>\n\n"
                f"<b>Детали покупки:</b>\n"
                f"📦 Подписка: {days} дней\n"
                f"💵 Стоимость: {price:,}₽\n\n"
                f"<b>Информация о балансе:</b>\n"
                f"💎 Текущий баланс: {current_balance:,}₽\n"
                f"➖ Будет списано: {price:,}₽\n"
                f"📊 Останется: {remaining_balance:,}₽\n\n"
                f"⚡ <i>Оплата произойдёт мгновенно!</i>\n"
                f"🎉 <i>Подписка активируется автоматически</i>\n\n"
                f"<b>Подтвердить оплату?</b>"
            )
            
            # Формируем callback для финальной оплаты (сокращенный формат)
            if mode == "e" and renewal_price and renewal_days:
                pay_callback = f"pb:{price}:{days}:{sub_short}:e:{renewal_price}:{renewal_days}"
            else:
                pay_callback = f"pb:{price}:{days}:{sub_short}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"✅ Да, оплатить {price:,}₽",
                    callback_data=pay_callback
                )],
                [InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data="subscribe"
                )]
            ])
            
            await callback.message.edit_text(
                confirmation_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Ошибка в confirm_payment_with_balance: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.callback_query(F.data.startswith("pb:"))
async def process_payment_with_balance(callback: types.CallbackQuery):
    """Обработчик оплаты подписки реферальным балансом"""
    try:
        # Парсим данные из callback (формат: pb:price:days:sub_short[:e:renewal_price:renewal_days])
        parts = callback.data.split(":")
        price = int(parts[1])
        days = int(parts[2])
        sub_short = parts[3]
        mode = parts[4] if len(parts) >= 5 and parts[4] == "e" else "standard"
        renewal_price = int(parts[5]) if len(parts) >= 6 else None
        renewal_days = int(parts[6]) if len(parts) >= 7 else None
        
        # Восстанавливаем полный sub_type из короткого
        sub_type = f"momclub_subscription_{sub_short.replace('m', 'month')}"
        
        logger.info(f"Пользователь {callback.from_user.id} пытается оплатить балансом: {price}₽ на {days} дней")
        
        from database.crud import (
            get_user_by_telegram_id,
            deduct_referral_balance,
            extend_subscription_days,
            create_subscription,
            create_payment_log,
            get_active_subscription
        )
        from utils.group_manager import GroupManager
        import time
        
        async with AsyncSessionLocal() as session:
            # Получаем пользователя
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            # КРИТИЧНО: Проверяем баланс еще раз (защита от race condition)
            current_balance = user.referral_balance or 0
            if current_balance < price:
                await callback.answer(
                    f"❌ Недостаточно средств!\n\n"
                    f"Баланс: {current_balance:,}₽\n"
                    f"Нужно: {price:,}₽",
                    show_alert=True
                )
                return
            
            try:
                # Списываем баланс
                success = await deduct_referral_balance(session, user.id, price)
                
                if not success:
                    await callback.answer("❌ Ошибка при списании баланса", show_alert=True)
                    return
                
                logger.info(f"Баланс списан для пользователя {user.id}: {price}₽")
                
                # Проверяем есть ли активная подписка
                active_sub = await get_active_subscription(session, user.id)
                
                if active_sub:
                    # Продлеваем существующую подписку
                    success = await extend_subscription_days(
                        session,
                        user.id,
                        days,
                        reason=f"balance_payment_{price}"
                    )
                    if not success:
                        # Откатываем списание если не удалось продлить
                        await session.rollback()
                        await callback.answer("❌ Ошибка при продлении подписки", show_alert=True)
                        return
                    
                    # Получаем обновлённую подписку
                    subscription = active_sub
                    logger.info(f"Подписка продлена для пользователя {user.id} на {days} дней")
                else:
                    # Создаем новую подписку
                    from datetime import datetime, timedelta
                    from utils.constants import CHAT_GROUP_ID
                    
                    end_date = datetime.now() + timedelta(days=days)
                    subscription = await create_subscription(
                        session,
                        user_id=user.id,
                        start_date=datetime.now(),
                        end_date=end_date,
                        group_id=CHAT_GROUP_ID
                    )
                    
                    logger.info(f"Создана новая подписка для пользователя {user.id} до {end_date}")
                
                # Логируем платеж балансом
                payment_log = await create_payment_log(
                    session,
                    user_id=user.id,
                    subscription_id=subscription.id,
                    amount=price,
                    status="success",
                    payment_method="referral_balance",  # Специальный тип для оплаты балансом
                    transaction_id=f"balance_{user.id}_{int(time.time())}",
                    details=f"Оплата балансом на {days} дней. Тип: {sub_type}",
                    days=days
                )
                
                # Коммитим транзакцию
                await session.commit()
                await session.refresh(user)
                
                logger.info(f"Оплата балансом успешно завершена для пользователя {user.id}")
                
                # Если у пользователя НЕ БЫЛО активной подписки - отправляем ссылку на группу
                # (это может быть как первая покупка, так и повторная после истечения)
                if not active_sub:
                    try:
                        from utils.constants import CLUB_CHANNEL_URL
                        
                        await callback.bot.send_message(
                            user.telegram_id,
                            f"🎉 <b>Добро пожаловать в Mom's Club!</b>\n\n"
                            f"Твоя подписка активирована балансом!\n"
                            f"Теперь присоединяйся к нашей закрытой группе:\n\n"
                            f"👇 <b>Нажми на кнопку ниже</b>",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(
                                    text="🚀 Присоединиться к группе",
                                    url=CLUB_CHANNEL_URL
                                )]
                            ]),
                            parse_mode="HTML"
                        )
                        logger.info(f"Ссылка на группу отправлена пользователю {user.id} после первой оплаты балансом")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке ссылки на группу: {e}")
                
                # Отправляем уведомление пользователю
                new_balance = user.referral_balance or 0
                from datetime import datetime
                
                # Формируем детальное сообщение
                success_text = (
                    "✅ <b>Оплата балансом успешна!</b>\n\n"
                    f"<b>📦 Детали покупки:</b>\n"
                    f"• Подписка: {days} дней\n"
                    f"• Стоимость: {price:,}₽\n\n"
                    f"<b>💰 Баланс:</b>\n"
                    f"• Было: {price + new_balance:,}₽\n"
                    f"• Списано: {price:,}₽\n"
                    f"• Осталось: {new_balance:,}₽\n\n"
                    f"<b>🎉 Статус:</b>\n"
                    f"• Подписка активирована мгновенно!\n"
                    f"• Доступ к закрытому контенту открыт\n"
                )
                
                if mode == "e" and renewal_price and renewal_days:
                    success_text += f"• Параметры автопродления обновлены\n"
                
                success_text += "\n💝 <i>Спасибо, что остаешься с Mom's Club!</i>"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Мой баланс", callback_data="referral_program")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="start")]
                ])
                
                await callback.message.edit_text(
                    success_text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                
                # Логируем успешную оплату в payment logger
                payment_logger = logging.getLogger("payments")
                payment_logger.info(
                    f"ОПЛАТА БАЛАНСОМ: user_id={user.id}, "
                    f"amount={price}₽, days={days}, "
                    f"new_balance={new_balance}₽, subscription_id={subscription.id}"
                )
                
                # Отправляем уведомление админам
                try:
                    from utils.constants import ADMIN_IDS
                    
                    admin_text = (
                        f"💰 <b>НОВАЯ ОПЛАТА БАЛАНСОМ!</b>\n\n"
                        f"<b>Пользователь:</b>\n"
                        f"• ID: {user.id}\n"
                        f"• Telegram: @{user.username or 'нет username'}\n"
                        f"• Имя: {user.first_name or 'Не указано'}\n\n"
                        f"<b>Детали оплаты:</b>\n"
                        f"• Сумма: {price:,}₽\n"
                        f"• Подписка: {days} дней\n"
                        f"• Остаток баланса: {new_balance:,}₽\n\n"
                        f"<b>Способ оплаты:</b> Реферальный баланс\n"
                        f"<b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                        f"<b>ID подписки:</b> {subscription.id}"
                    )
                    
                    for admin_id in ADMIN_IDS:
                        try:
                            await callback.bot.send_message(
                                admin_id,
                                admin_text,
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
                            
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомлений админам: {e}")
                
            except Exception as e:
                # Откатываем транзакцию при ошибке
                await session.rollback()
                logger.error(f"Ошибка при оплате балансом для пользователя {user.id}: {e}", exc_info=True)
                await callback.answer("❌ Произошла ошибка при оплате", show_alert=True)
                
    except Exception as e:
        logger.error(f"Ошибка в process_payment_with_balance: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# Обработчик ввода телефона для оплаты (ОТКЛЮЧЕН по требованию заказчицы)
@user_router.message(StateFilter(PaymentDataStates.waiting_for_phone))
async def process_payment_phone_input(message: types.Message, state: FSMContext):
    """Обрабатывает ввод номера телефона для оплаты (заглушка)"""
    # Запрос телефона отключен
    await message.answer("❌ Запрос телефона отключен")
    return
    
    
    # Старый код (закомментирован):
    """
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
    """
    pass  # Закрывающий комментарий


# Email полностью удален из системы (не используется)


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
                end_date_formatted = format_subscription_end_date(active_subscription, escape_for_markdown=True)
                subscription_text = f"\n\n✅ Ваша текущая подписка активна до *{end_date_formatted}* и продолжает действовать\\."
            
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

                            # Начисляем бонус рефералу (самому пользователю) при первом платеже, если ещё не начисляли
                            ref_self_reason = f"referral_bonus_self_from_{referrer.id}"
                            self_exists_q = await session.execute(
                                select(PaymentLog).where(
                                    PaymentLog.user_id == user.id,
                                    PaymentLog.payment_method == "bonus",
                                    PaymentLog.details.like(f"%{ref_self_reason}%")
                                )
                            )
                            already_self_bonus = self_exists_q.scalars().first() is not None
                            if not already_self_bonus:
                                success_self = await extend_subscription_days(session, user.id, REFERRAL_BONUS_DAYS, reason=ref_self_reason)
                                if success_self:
                                    ref_name = referrer.first_name or "Пользователь"
                                    if referrer.username:
                                        ref_name = f"{ref_name} (@{referrer.username})"
                                    from database.crud import send_referee_bonus_notification
                                    await send_referee_bonus_notification(callback.bot, user.telegram_id, ref_name, REFERRAL_BONUS_DAYS)
                                    payment_logger.info(f"Реферальный бонус {REFERRAL_BONUS_DAYS} дней начислен рефералу user_id={user.id}")
                                else:
                                    payment_logger.warning(f"Не удалось начислить реферальный бонус рефералу user_id={user.id}")
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
                        [InlineKeyboardButton(text="🎀 Перейти в Mom's Club", url=CLUB_CHANNEL_URL)]
                    ]
                )
                
                # Форматируем дату окончания подписки для отображения (с учетом пожизненной)
                end_date_formatted = format_subscription_end_date(subscription, escape_for_markdown=True)
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    
                    # Сначала отправляем видео-кружок от Полины
                    try:
                        video_path = os.path.join(os.getcwd(), "media", "videoposlepay.mp4")
                        if os.path.exists(video_path):
                            video_note = FSInputFile(video_path)
                            await callback.bot.send_video_note(
                                chat_id=user.telegram_id,
                                video_note=video_note
                            )
                            payment_logger.info(f"Отправлен видео-кружок пользователю {user.telegram_id}")
                        else:
                            payment_logger.warning(f"Видео-файл не найден: {video_path}")
                    except Exception as e:
                        payment_logger.error(f"Ошибка отправки видео-кружка: {e}")
                        # Продолжаем отправку текстового сообщения даже если видео не отправилось
                    
                    # Затем отправляем текстовое сообщение об успешном платеже
                    success_text = (
                        f"🎉 *Поздравляем\\!* Ваш платеж успешно прошел\\.\n\n"
                        f"Подписка активна до: *{escape_markdown_v2(end_date_formatted)}*\n\n"
                        f"Добро пожаловать в клуб\\! Теперь вы можете перейти в закрытый канал и получить доступ ко всем материалам\\."
                    )
                    
                    await callback.message.answer(
                        success_text,
                        reply_markup=keyboard,
                        parse_mode="MarkdownV2"
                    )
                    # Второе сообщение: промо InstaBot
                    try:
                        instabot_keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text="✨ Перейти в InstaBot", url="https://t.me/instaio_bot")]]
                        )
                        instabot_text = (
                            "✨ Дополнительно для участниц Mom's Club\n\n"
                            "Вам доступен наш Instagram AI-бот для продвижения — <b>InstaBot</b>.\n"
                            "Он подскажет идеи постов и Reels, поможет с текстами и оформлением.\n\n"
                            "Попробуйте прямо сейчас:"
                        )
                        await callback.message.answer(
                            instabot_text,
                            reply_markup=instabot_keyboard,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logging.error(f"Ошибка отправки промо InstaBot: {e}")
                    
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
                    # Продублируем промо и в этом варианте
                    try:
                        instabot_keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text="✨ Перейти в InstaBot", url="https://t.me/instaio_bot")]]
                        )
                        instabot_text = (
                            "✨ Дополнительно для участниц Mom's Club\n\n"
                            "Вам доступен наш Instagram AI-бот для продвижения — <b>InstaBot</b>.\n"
                            "Он подскажет идеи постов и Reels, поможет с текстами и оформлением.\n\n"
                            "Попробуйте прямо сейчас:"
                        )
                        await callback.message.answer(
                            instabot_text,
                            reply_markup=instabot_keyboard,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logging.error(f"Ошибка отправки промо InstaBot: {e}")
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
        error_msg = format_user_error_message(e, "при проверке платежа")
        await callback.answer(error_msg, show_alert=True)


# Обработчик команды /profile
@user_router.message(Command("profile"), F.chat.type == "private")
async def cmd_profile(message: types.Message):
    """Обработчик команды /profile - открывает личный кабинет"""
    log_message(message.from_user.id, "/profile", "command")
    # Перенаправляем на обработчик кнопки "Личный кабинет"
    await process_profile(message)


# Обработчик команды /referral  
@user_router.message(Command("referral"), F.chat.type == "private")
async def cmd_referral(message: types.Message):
    """Обработчик команды /referral - открывает реферальную программу"""
    log_message(message.from_user.id, "/referral", "command")
    
    from database.crud import get_user_by_telegram_id, has_active_subscription, create_referral_code
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        
        if not user:
            await message.answer("Пользователь не найден")
            return
        
        # Проверяем, есть ли активная подписка
        has_subscription = await has_active_subscription(session, user.id)
        
        if not has_subscription:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💸 Оформить подписку", callback_data="subscribe")],
                    [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
                ]
            )
            
            await message.answer(
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
            await message.answer("Ошибка при создании реферального кода")
            return
        
        # Формируем реферальную ссылку
        bot_username = (await message.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start=ref_{referral_code}"
        
        # Получаем статистику рефералов
        from sqlalchemy import select, func as sql_func
        from database.models import User as UserModel
        
        # Считаем всех приглашенных
        total_referrals_query = select(sql_func.count(UserModel.id)).where(UserModel.referrer_id == user.id)
        total_referrals = await session.scalar(total_referrals_query) or 0
        
        # Получаем данные для текста
        from utils.referral_helpers import get_loyalty_name, get_bonus_percent_for_level
        from utils.constants import MIN_WITHDRAWAL_AMOUNT
        
        balance = user.referral_balance or 0
        total_earned = user.total_earned_referral or 0
        total_paid = user.total_referrals_paid or 0
        loyalty_level = user.current_loyalty_level or 'none'
        level_name = get_loyalty_name(loyalty_level)
        bonus_percent = get_bonus_percent_for_level(loyalty_level)
        
        # Формируем текст через helper
        from utils.referral_messages import get_referral_program_text
        text = get_referral_program_text(
            balance,
            total_earned,
            total_referrals,
            total_paid,
            level_name,
            bonus_percent,
            referral_link
        )
        
        # Создаем клавиатуру
        keyboard_buttons = [
            [InlineKeyboardButton(
                text="📤 Поделиться ссылкой",
                switch_inline_query=f"Присоединяйся к Mom's Club по моей ссылке! {referral_link}"
            )]
        ]
        
        # Кнопка вывода (если баланс >= минимума)
        if balance >= MIN_WITHDRAWAL_AMOUNT:
            keyboard_buttons.append([
                InlineKeyboardButton(text="💸 Вывести средства", callback_data="ref_withdraw")
            ])
        
        # Кнопка истории
        keyboard_buttons.append([
            InlineKeyboardButton(text="📊 История начислений", callback_data="ref_history")
        ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )


# Обработчик команды /faq
@user_router.message(Command("faq"), F.chat.type == "private")
async def cmd_faq(message: types.Message):
    """Обработчик команды /faq - открывает частые вопросы"""
    log_message(message.from_user.id, "/faq", "command")
    # Перенаправляем на обработчик кнопки "Частые вопросы"
    await process_faq(message)


# Обработчик команды /support
@user_router.message(Command("support"), F.chat.type == "private")
async def cmd_support(message: types.Message):
    """Обработчик команды /support - открывает службу поддержки"""
    log_message(message.from_user.id, "/support", "command")
    # Перенаправляем на обработчик кнопки "Служба поддержки"
    await process_support(message)


# Обработчик команды /help
@user_router.message(Command("help"), F.chat.type == "private")
async def cmd_help(message: types.Message):
    """
    Обработчик команды /help
    """
    help_text = """Доступные команды:
/start - Начать работу с ботом
/profile - Личный кабинет
/faq - Частые вопросы
/support - Служба поддержки
/club - Получить ссылку на закрытый канал
/help - Показать это сообщение помощи"""
    
    await message.answer(help_text)


# Обработчик команды /club
@user_router.message(Command("club"), F.chat.type == "private")
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


# УДАЛЕНО: Обработчик "Мои подписки" - функция не используется
# Все операции с подпиской теперь через "Управление подпиской"


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
                    # Активная подписка есть - показываем дату окончания (с учетом пожизненной)
                    end_date_str = format_subscription_end_date(subscription, escape_for_markdown=False)
                    
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
                # Форматируем дату и дни (с учетом пожизненной подписки)
                end_date_str = format_subscription_end_date(subscription, escape_for_markdown=False)
                days_text = format_subscription_days_left(subscription, escape_for_markdown=False)
                
                # Формируем текст подтверждения
                confirmation_text = f"""<b>Подтверждение продления подписки</b>

У вас уже есть активная подписка до: <b>{end_date_str}</b>
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
        error_msg = format_user_error_message(e, "при продлении подписки")
        await callback.answer(error_msg, show_alert=True)
    
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
                # Форматируем дату и дни (с учетом пожизненной подписки)
                end_date_str = format_subscription_end_date(subscription, escape_for_markdown=False)
                days_text = format_subscription_days_left(subscription, escape_for_markdown=False)
                
                # Формируем текст с упоминанием текущей подписки
                subscription_text = f"""<b>Продление подписки в Mom's Club</b>

🔍 <b>Информация о текущей подписке:</b>
📆 Действует до: {end_date_str}
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
        error_msg = format_user_error_message(e, "при подтверждении продления подписки")
        await callback.answer(error_msg, show_alert=True)
    
    # Убираем часы загрузки на кнопке
    await callback.answer()


# Вспомогательная функция для форматирования краткой информации о лояльности (для главного экрана)
async def format_loyalty_status_short(db, user) -> str:
    """
    Формирует краткую информацию о статусе лояльности для главного экрана.
    Возвращает пустую строку, если нет информации о лояльности.
    Форматирование уже готово для MarkdownV2.
    """
    tenure_days = await calc_tenure_days(db, user)
    level = user.current_loyalty_level or 'none'
    discount = effective_discount(user)
    
    # Получаем прогресс до следующего уровня
    progress = get_loyalty_progress(tenure_days, level)
    
    # Если есть уровень
    if level != 'none':
        level_names = {
            'silver': ('Silver Mom', '⭐'),
            'gold': ('Gold Mom', '🌟'),
            'platinum': ('Platinum Mom', '💍')
        }
        level_name, emoji = level_names.get(level, ('', ''))
        
        # Если есть скидка, показываем её
        if discount > 0:
            discount_escaped = escape_markdown_v2(str(discount))
            # Все скидки лояльности теперь постоянные
            status_text = f"💎 *Твой статус:* {level_name} {emoji}\n💎 *Постоянная скидка:* {discount_escaped}% ✨\n"
        else:
            status_text = f"💎 *Твой статус:* {level_name} {emoji}\n"
        
        # Добавляем прогресс-бар, если есть следующий уровень
        if progress['next_level']:
            next_level_names = {
                'silver': 'Silver Mom ⭐',
                'gold': 'Gold Mom 🌟',
                'platinum': 'Platinum Mom 💍'
            }
            next_level_name = next_level_names.get(progress['next_level'], progress['next_level'])
            days_needed_escaped = escape_markdown_v2(str(progress['days_needed']))
            progress_bar_escaped = escape_markdown_v2(progress['progress_bar'])
            status_text += f"\n📊 *Прогресс до {next_level_name}:*\n`{progress_bar_escaped}`\nОсталось: *{days_needed_escaped}* дней\n"
        elif progress['current_level'] == 'platinum':
            # Максимальный уровень достигнут
            status_text += "\n🏆 *Ты достигла максимального уровня\\!*\n"
        
        return status_text
    
    # Если нет уровня, но есть скидка
    elif discount > 0:
        discount_escaped = escape_markdown_v2(str(discount))
        # Если есть постоянная скидка, показываем её как постоянную
        if user.lifetime_discount_percent > 0:
            return f"💎 *Твоя постоянная скидка:* {discount_escaped}% ✨\n"
        else:
            return f"💰 *Твоя скидка:* {discount_escaped}% на следующее продление ✨\n"
    
    # Если есть стаж (больше 0 дней), но нет уровня
    elif tenure_days > 0:
        tenure_escaped = escape_markdown_v2(str(tenure_days))
        # Показываем прогресс до Silver
        if progress['next_level']:
            days_needed_escaped = escape_markdown_v2(str(progress['days_needed']))
            progress_bar_escaped = escape_markdown_v2(progress['progress_bar'])
            return f"💫 Ты с нами уже *{tenure_escaped}* дней\\! Скоро откроются бонусы ✨\n\n📊 *Прогресс до Silver Mom ⭐:*\n`{progress_bar_escaped}`\nОсталось: *{days_needed_escaped}* дней\n"
        return f"💫 Ты с нами уже *{tenure_escaped}* дней\\! Скоро откроются бонусы ✨\n"
    
    # Если ничего нет
    return ""


async def format_user_badges(db, user) -> str:
    """
    Форматирует список badges пользователя для отображения в профиле.
    Возвращает пустую строку, если badges нет.
    """
    badges = await get_user_badges(db, user.id)
    if not badges:
        return ""
    
    badges_text = "\n\n🏆 *Твои достижения:*\n"
    for badge in badges:
        # Получаем название badge из словаря, если нет - используем badge_type
        badge_info = BADGE_NAMES_AND_DESCRIPTIONS.get(badge.badge_type)
        if badge_info:
            name, desc = badge_info
        else:
            # Если badge_type не найден в словаре, используем его как есть
            name = badge.badge_type
        name_escaped = escape_markdown_v2(name)
        badges_text += f"• {name_escaped}\n"
    
    return badges_text


# Вспомогательная функция для форматирования подробной информации о лояльности (для управления подпиской)
async def format_loyalty_status_detailed(db, user) -> str:
    """
    Формирует подробную информацию о статусе лояльности для раздела управления подпиской.
    """
    tenure_days = await calc_tenure_days(db, user)
    level = user.current_loyalty_level or 'none'
    discount = effective_discount(user)
    
    loyalty_text = "💎 *Твой статус лояльности:*\n"
    
    # Если есть уровень
    if level != 'none':
        level_names = {
            'silver': ('Silver Mom', '⭐'),
            'gold': ('Gold Mom', '🌟'),
            'platinum': ('Platinum Mom', '💍')
        }
        level_name, emoji = level_names.get(level, ('', ''))
        
        tenure_escaped = escape_markdown_v2(str(tenure_days))
        loyalty_text += f"⭐ Уровень: *{level_name}* {emoji}\n"
        loyalty_text += f"📅 С нами: *{tenure_escaped} дней*\n"
        
        # Если есть ожидающий бонус
        if user.pending_loyalty_reward:
            loyalty_text += "🎁 *У тебя есть невыбранный бонус\\!*\n\n"
            loyalty_text += "Выбери свой подарок в личных сообщениях ✨\n"
        else:
            # Информация о скидке
            if user.lifetime_discount_percent > 0:
                discount_escaped = escape_markdown_v2(str(discount))
                loyalty_text += f"💎 Постоянная скидка: *{discount_escaped}%* на все продления ✨\n"
            elif discount > 0:
                discount_escaped = escape_markdown_v2(str(discount))
                loyalty_text += f"💰 Скидка: *{discount_escaped}%* на следующее продление\n"
            else:
                loyalty_text += "💰 Скидка: Нет\n"
            
            loyalty_text += "🎁 Ожидает бонус: Нет\n"
    
    # Если нет уровня, но есть скидка
    elif discount > 0:
        discount_escaped = escape_markdown_v2(str(discount))
        if user.lifetime_discount_percent > 0:
            loyalty_text += f"💎 Постоянная скидка: *{discount_escaped}%* на все продления ✨\n"
        else:
            loyalty_text += f"💰 На следующее продление: *{discount_escaped}%* ✨\n"
    
    # Если нет ничего, но есть стаж
    elif tenure_days > 0:
        tenure_escaped = escape_markdown_v2(str(tenure_days))
        loyalty_text += f"💫 Ты с нами уже *{tenure_escaped} дней*\n"
        loyalty_text += "✨ Скоро откроются бонусы за верность\\!\n"
    
    # Если совсем ничего нет
    else:
        loyalty_text += "💫 Ты новичок в нашем клубе\n"
        loyalty_text += "✨ Бонусы появятся со временем\\!\n"
    
    return loyalty_text


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
            
            # Выбираем картинку в зависимости от уровня лояльности
            tenure_days = await calc_tenure_days(session, user)
            level = user.current_loyalty_level or level_for_days(tenure_days)
            
            # Определяем путь к картинке на основе уровня лояльности
            if level == 'silver':
                banner_filename = "silverlk.png"
            elif level == 'gold':
                banner_filename = "goldlk.png"
            elif level == 'platinum':
                banner_filename = "platinum.png"
            else:
                # Для пользователей без уровня лояльности или с level == 'none'
                banner_filename = "nonelk.png"
            
            banner_path = os.path.join(os.getcwd(), "media", banner_filename)
            banner_photo = FSInputFile(banner_path)
            
            if subscription:
                # Форматируем даты для красивого отображения с экранированием
                start_date = escape_markdown_v2(subscription.start_date.strftime("%d.%m.%Y"))
                end_date = format_subscription_end_date(subscription, escape_for_markdown=True)
                
                # Рассчитываем оставшиеся дни (с учетом пожизненной подписки)
                days_text = format_subscription_days_left(subscription, escape_for_markdown=True)
                
                # Формируем информацию о лояльности
                loyalty_status = await format_loyalty_status_short(session, user)
                loyalty_status_escaped = loyalty_status  # Уже готово для MarkdownV2
                
                # Формируем информацию о badges
                badges_text = await format_user_badges(session, user)
                badges_text_escaped = badges_text  # Уже готово для MarkdownV2
                
                # Добавляем статус админа, если есть
                admin_status_text = ""
                if user.admin_group:
                    from utils.admin_permissions import get_admin_group_display
                    admin_display = get_admin_group_display(user)
                    if admin_display:
                        admin_display_escaped = escape_markdown_v2(admin_display)
                        admin_status_text = f"\n\n✨ *{admin_display_escaped}* ✨\n"
                
                # Добавляем информацию о заработке
                referral_earnings_text = ""
                total_earned = user.total_earned_referral or 0
                current_balance = user.referral_balance or 0
                
                if total_earned > 0:
                    total_earned_escaped = escape_markdown_v2(f"{total_earned:,}₽")
                    balance_escaped = escape_markdown_v2(f"{current_balance:,}₽")
                    referral_earnings_text = f"\n💰 *Заработано с Moms Club:* {total_earned_escaped}\n"
                    referral_earnings_text += f"💵 *Баланс:* {balance_escaped}\n"
                elif current_balance == 0:
                    referral_earnings_text = f"\n💡 *Начни зарабатывать\\!* Загляни в реферальную программу\n"
                
                # Новый формат текста
                profile_text = f"""🎀 *Добро пожаловать в личный кабинет\\!*

👋 Рады видеть вас, {user_name_escaped}
{admin_status_text}{referral_earnings_text}{loyalty_status_escaped}{badges_text_escaped}Выберите нужный пункт в меню ниже — всё под рукой"""
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        # Основной доступ
                        [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)],
                        # Подписка и программы (отдельные строки для длинных текстов)
                        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="manage_subscription")],
                        [InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="referral_program")],
                        # Платежи и промокод
                        [
                            InlineKeyboardButton(text="💳 История платежей", callback_data="payment_history"),
                            InlineKeyboardButton(text="🎁 Промокод", callback_data="enter_promo_code")
                        ],
                        # Настройки
                        [
                            InlineKeyboardButton(text="📅 Дата рождения", callback_data="set_birthday"),
                            InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")
                        ]
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
                        # Основное действие
                        [InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")],
                        # Дополнительно
                        [
                            InlineKeyboardButton(text="🎁 Промокод", callback_data="enter_promo_code"),
                            InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")
                        ]
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
        error_msg = format_user_error_message(e, "при загрузке отзывов")
        await message.answer(error_msg)


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


# Обработчик кнопки "🤎 Служба поддержки"
@user_router.message(lambda message: message.text == "🤎 Служба поддержки")
async def process_support(message: types.Message):
    """
    Обработчик кнопки "Служба поддержки".
    Отправляет сообщение с информацией и кнопкой для связи со службой поддержки.
    """
    # Создаем кнопку для перехода в Telegram
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤎 Написать в поддержку", url="https://t.me/momsclubsupport")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_support")]
        ]
    )
    
    # Текст с форматированием
    text = (
        "<b>🤎 Служба поддержки Mom's Club</b>\n\n"
        "👋 Если у тебя есть вопросы или нужна помощь — напиши нам!\n\n"
        "✨ Мы всегда рады помочь и ответить на все твои вопросы 🤎"
    )
    
    await message.answer(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# Обработчик кнопки закрытия сообщения "Служба поддержки"
@user_router.callback_query(lambda c: c.data == "close_support")
async def close_support_message(callback: types.CallbackQuery):
    """Закрывает сообщение со службой поддержки"""
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при закрытии сообщения 'Служба поддержки': {e}")
    
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
            
            # Выбираем картинку в зависимости от уровня лояльности
            tenure_days = await calc_tenure_days(session, user)
            level = user.current_loyalty_level or level_for_days(tenure_days)
            
            # Определяем путь к картинке на основе уровня лояльности
            if level == 'silver':
                banner_filename = "silverlk.png"
            elif level == 'gold':
                banner_filename = "goldlk.png"
            elif level == 'platinum':
                banner_filename = "platinum.png"
            else:
                # Для пользователей без уровня лояльности или с level == 'none'
                banner_filename = "nonelk.png"
            
            banner_path = os.path.join(os.getcwd(), "media", banner_filename)
            banner_photo = FSInputFile(banner_path)
            
            if subscription:
                # Форматируем даты для красивого отображения с экранированием
                start_date = escape_markdown_v2(subscription.start_date.strftime("%d.%m.%Y"))
                end_date = format_subscription_end_date(subscription, escape_for_markdown=True)
                
                # Рассчитываем оставшиеся дни (с учетом пожизненной подписки)
                days_text = format_subscription_days_left(subscription, escape_for_markdown=True)
                
                # Формируем информацию о лояльности
                loyalty_status = await format_loyalty_status_short(session, user)
                loyalty_status_escaped = loyalty_status  # Уже готово для MarkdownV2
                
                # Формируем информацию о badges
                badges_text = await format_user_badges(session, user)
                badges_text_escaped = badges_text  # Уже готово для MarkdownV2
                
                # Добавляем статус админа, если есть
                admin_status_text = ""
                if user.admin_group:
                    from utils.admin_permissions import get_admin_group_display
                    admin_display = get_admin_group_display(user)
                    if admin_display:
                        admin_display_escaped = escape_markdown_v2(admin_display)
                        admin_status_text = f"\n\n✨ *{admin_display_escaped}* ✨\n"
                
                # Добавляем информацию о заработке
                referral_earnings_text = ""
                total_earned = user.total_earned_referral or 0
                current_balance = user.referral_balance or 0
                
                if total_earned > 0:
                    total_earned_escaped = escape_markdown_v2(f"{total_earned:,}₽")
                    balance_escaped = escape_markdown_v2(f"{current_balance:,}₽")
                    referral_earnings_text = f"\n💰 *Заработано с Moms Club:* {total_earned_escaped}\n"
                    referral_earnings_text += f"💵 *Баланс:* {balance_escaped}\n"
                elif current_balance == 0:
                    referral_earnings_text = f"\n💡 *Начни зарабатывать\\!* Загляни в реферальную программу\n"
                
                # Новый формат текста
                profile_text = f"""🎀 *Добро пожаловать в личный кабинет\\!*

👋 Рады видеть вас, {user_name_escaped}
{admin_status_text}{referral_earnings_text}{loyalty_status_escaped}{badges_text_escaped}Выберите нужный пункт в меню ниже — всё под рукой"""
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        # Основной доступ
                        [InlineKeyboardButton(text="🔐 Войти в Mom's Club", url=CLUB_CHANNEL_URL)],
                        # Подписка и программы (отдельные строки для длинных текстов)
                        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="manage_subscription")],
                        [InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="referral_program")],
                        # Платежи и промокод
                        [
                            InlineKeyboardButton(text="💳 История платежей", callback_data="payment_history"),
                            InlineKeyboardButton(text="🎁 Промокод", callback_data="enter_promo_code")
                        ],
                        # Настройки
                        [
                            InlineKeyboardButton(text="📅 Дата рождения", callback_data="set_birthday"),
                            InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")
                        ]
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
                        # Основное действие
                        [InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")],
                        # Дополнительно
                        [
                            InlineKeyboardButton(text="🎁 Промокод", callback_data="enter_promo_code"),
                            InlineKeyboardButton(text="❌ Закрыть", callback_data="close_message")
                        ]
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
@user_router.message(Command("profile"), F.chat.type == "private")
async def cmd_profile(message: types.Message):
    # Перенаправляем на обработчик кнопки профиля
    await process_profile(message)


# Обработчик возврата к рассылке о системе лояльности
@user_router.callback_query(F.data == "show_broadcast_loyalty")
async def show_broadcast_loyalty(callback: types.CallbackQuery):
    """Обработчик для возврата к сообщению рассылки о системе лояльности"""
    import os
    from aiogram.types import FSInputFile
    
    # Путь к изображению рассылки
    BROADCAST_IMAGE_PATH = os.path.join("media", "2025-11-03 16.57.59.jpg")
    BROADCAST_TEXT = """💎 <b>Новое в MOMS CLUB: Система лояльности!</b> ✨

Привет, красотка! 🤎

Мы запускаем что-то особенное — <b>система лояльности</b>, которая станет нашей благодарностью за твою верность и участие в клубе! 

Чем дольше ты с нами, тем больше бонусов получаешь 🍿

🎞️ <b>Три уровня, три истории роста:</b>

<b>Silver Mom ⭐</b> — 3 месяца вместе
• Постоянная скидка <b>5%</b> на все продления подписки или
• <b>+7 дней</b> бесплатного доступа к клубу

<b>Gold Mom 🌟</b> — 6 месяцев вместе  
• Постоянная скидка <b>10%</b> на все продления подписки или
• <b>+14 дней</b> бесплатного доступа к клубу

<b>Platinum Mom 💍</b> — 12 месяцев вместе
• Постоянная скидка <b>15%</b> на все продления подписки или
• <b>+30 дней</b> бесплатного доступа + особенный подарок 🎁

📊 <b>Как это работает?</b>

Каждый день твоей подписки приближает тебя к следующему уровню! Стаж считается только за периоды активной подписки, так что чем дольше ты с нами, тем ближе к новым бонусам 🎯

🧺 <b>Твой выбор — твои бонусы</b>

Когда ты достигаешь нового уровня, мы отправим тебе сообщение с выбором: ты сможешь выбрать либо постоянную скидку на все будущие продления, либо дополнительные дни доступа к клубу. Решать только тебе! 🥹🫂

💡 <b>Важно знать:</b>

• Все скидки <b>постоянные</b> — действуют на все будущие продления подписки
• Стаж накапливается автоматически — просто продолжай пользоваться подпиской
• Бонусы доступны только при активной подписке

📱 <b>Где посмотреть свой статус?</b>

Твой текущий статус лояльности, стаж до следующего уровня и выбранные бонусы всегда доступны в <b>Личном кабинете</b> — нажми на кнопку "👤 Личный кабинет" в главном меню бота или воспользуйся командой <code>/profile</code> 🎀

Это наш способ сказать тебе "спасибо" за то, что ты часть нашего сообщества мам-креаторов 🫂🤎

Растем вместе! 🍯🥨

<b>Команда MOMS CLUB</b>"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Узнать подробнее про статус лояльности", callback_data="loyalty_info:from_broadcast")],
            [InlineKeyboardButton(text="💰 Купить доступ по акции", callback_data="subscribe:from_broadcast")]
        ]
    )
    
    try:
        # Удаляем текущее сообщение
        await callback.message.delete()
    except:
        pass
    
    # Отправляем фото отдельно
    if os.path.exists(BROADCAST_IMAGE_PATH):
        photo = FSInputFile(BROADCAST_IMAGE_PATH)
        await callback.message.answer_photo(photo=photo)
    
    # Отправляем текст с кнопками
    await callback.message.answer(
        BROADCAST_TEXT,
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


# Обработчик кнопки "Все про систему лояльности"
@user_router.callback_query(F.data == "faq_loyalty")
@user_router.callback_query(F.data == "loyalty_info")
@user_router.callback_query(F.data == "loyalty_info:from_broadcast")
async def process_loyalty_info(callback: types.CallbackQuery):
    """Обработчик для отображения информации о системе лояльности"""
    log_message(callback.from_user.id, "loyalty_info", "callback")
    
    from database.crud import get_user_by_telegram_id
    from datetime import datetime
    from loyalty.levels import SILVER_THRESHOLD, GOLD_THRESHOLD, PLATINUM_THRESHOLD
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем информацию о текущем статусе пользователя
        tenure_days = await calc_tenure_days(session, user)
        current_level = user.current_loyalty_level or level_for_days(tenure_days)
        discount = effective_discount(user)
        
        # Определяем следующие уровни и сколько дней осталось
        next_level_info = ""
        if current_level == 'none':
            days_to_silver = SILVER_THRESHOLD - tenure_days
            next_level_info = f"\n\n📈 <b>До уровня Silver:</b> {days_to_silver} дней (всего {SILVER_THRESHOLD} дней)"
        elif current_level == 'silver':
            days_to_gold = GOLD_THRESHOLD - tenure_days
            next_level_info = f"\n\n📈 <b>До уровня Gold:</b> {days_to_gold} дней (всего {GOLD_THRESHOLD} дней)"
        elif current_level == 'gold':
            days_to_platinum = PLATINUM_THRESHOLD - tenure_days
            next_level_info = f"\n\n📈 <b>До уровня Platinum:</b> {days_to_platinum} дней (всего {PLATINUM_THRESHOLD} дней)"
        elif current_level == 'platinum':
            next_level_info = f"\n\n🏆 <b>Поздравляем!</b> Ты достигла максимального уровня лояльности! 💍"
        
        # Формируем текст с текущим статусом
        current_status = ""
        if current_level != 'none':
            level_names = {
                'silver': ('Silver Mom', '⭐'),
                'gold': ('Gold Mom', '🌟'),
                'platinum': ('Platinum Mom', '💍')
            }
            level_name, emoji = level_names.get(current_level, ('', ''))
            current_status = f"\n\n💎 <b>Твой текущий статус:</b> {level_name} {emoji}"
            if discount > 0:
                current_status += f"\n💰 <b>Твоя постоянная скидка:</b> {discount}%"
        elif tenure_days > 0:
            current_status = f"\n\n📅 <b>Твой стаж:</b> {tenure_days} дней"
        
        # Основной текст о системе лояльности
        loyalty_info_text = f"""💎 <b>Система лояльности Mom's Club</b> ✨

🎁 <b>Что это?</b>
Система лояльности — это наша благодарность за твою верность и постоянное участие в клубе! Чем дольше ты с нами, тем больше бонусов получаешь 🩷

⭐ <b>Уровни лояльности:</b>

<b>Silver Mom</b> ⭐ — <b>3 месяца</b> вместе
• Постоянная скидка <b>5%</b> на все продления подписки
• <b>+7 дней</b> бесплатного доступа к клубу

<b>Gold Mom</b> 🌟 — <b>6 месяцев</b> вместе
• Постоянная скидка <b>10%</b> на все продления подписки
• <b>+14 дней</b> бесплатного доступа к клубу

<b>Platinum Mom</b> 💍 — <b>12 месяцев</b> вместе
• Постоянная скидка <b>15%</b> на все продления подписки
• <b>+30 дней</b> бесплатного доступа + особенный подарок 🎁

📊 <b>Как повысить уровень?</b>
Просто продолжай пользоваться подпиской! Уровень зависит от стажа — количества дней с момента первой оплаты. Каждый день с подпиской приближает тебя к следующему уровню ✨

🎁 <b>Как выбрать бонус?</b>
Когда достигаешь нового уровня, мы отправим тебе сообщение с выбором бонуса. Ты сможешь выбрать либо постоянную скидку, либо дополнительные дни доступа к клубу — решать только тебе! 💝

💡 <b>Важно:</b>
• Скидки <b>постоянные</b> — действуют на все будущие продления подписки
• Стаж считается с момента первой оплаты
• Бонусы доступны только при активной подписке{current_status}{next_level_info}"""
        
        # Определяем, откуда вызван (из рассылки, FAQ или профиля)
        from_broadcast = callback.data == "loyalty_info:from_broadcast"
        from_faq = callback.data == "faq_loyalty"
        
        # Создаем кнопки в зависимости от источника
        if from_broadcast:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад к рассылке", callback_data="show_broadcast_loyalty")]
                ]
            )
        elif from_faq:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад к вопросам", callback_data="back_to_faq")]
                ]
            )
        else:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")]
                ]
            )
        
        try:
            await callback.message.delete()
        except:
            pass
        
        await callback.message.answer(
            loyalty_info_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()


@user_router.callback_query(F.data == "faq_badges")
@user_router.callback_query(F.data == "badges_info")
async def process_badges_info(callback: types.CallbackQuery):
    """Обработчик кнопки 'Все про достижения'"""
    log_message(callback.from_user.id, "view_badges_info", "action")
    
    from_faq = callback.data == "faq_badges"
    
    badges_info_text = """🏆 *Все про достижения в Mom's Club\\!*

Красотка, в нашем клубе есть система достижений, которые ты можешь получить за свою активность и преданность\\!

*📋 Автоматические достижения:*

💳 *Первая оплата*
Твоя первая оплата в Mom's Club\\! Это твой первый шаг в нашем сообществе 💖

🤝 *Пригласила друга*
Ты пригласила первого друга в клуб\\! Спасибо, что делишься Mom's Club с подругами ✨

🌟 *Пригласила 5 друзей*
5 подруг уже с нами благодаря тебе\\! Ты настоящий амбассадор клуба 🎀

✨ *Пригласила 10 друзей*
10 подруг уже в Mom's Club благодаря тебе\\! Это настоящий подвиг 💎

📅 *Месяц в клубе*
Ты с нами уже целый месяц\\! За это время ты стала частью нашего теплого сообщества 💕

💫 *Полгода в клубе*
Полгода вместе — это уже серьезно\\! Ты настоящая часть нашей семьи 🌟

🏆 *Год в клубе*
Целый год вместе\\! Ты прошла с нами весь путь, и мы бесконечно благодарны за твою верность 💖

💎 *Верный клиент*
5\\+ успешных платежей — это говорит о твоей преданности Mom's Club\\! Мы очень ценим таких участников 🤍

👑 *Платиновый клиент*
10\\+ успешных платежей — это настоящий рекорд\\! Ты одна из самых преданных участниц нашего клуба 🏆

🔥 *Активный участник*
Подписка продлевалась 3\\+ раза — это значит, что Mom's Club стал частью твоей жизни\\! ✨

🎂 *День рождения*
Получен подарок на день рождения\\! Мы помним о твоем особом дне 💕

*💡 Как получить достижения?*

Достижения выдаются автоматически при выполнении условий\\. Просто будь активной, приглашай друзей, продлевай подписку — и достижения сами найдут тебя\\! 🎀

*⭐ Специальные достижения*

Также есть особые достижения, которые выдаются администраторами в знак особой благодарности за вклад в развитие клуба\\. Они не выдаются автоматически, а только лично от команды Mom's Club 💖

*🎯 Где посмотреть свои достижения?*

Все твои достижения отображаются в личном кабинете\\. Просто открой профиль и увидишь список всех своих наград\\! 🏆

Продолжай быть активной, красотка\\! Мы ценим каждую участницу нашего клуба 💕"""
    
    # Кнопка назад в зависимости от источника
    if from_faq:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад к вопросам", callback_data="back_to_faq")]
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")]
            ]
        )
    
    try:
        await callback.message.delete()
    except:
        pass
    
    await callback.message.answer(
        badges_info_text,
        reply_markup=keyboard,
        parse_mode="MarkdownV2"
    )
    
    await callback.answer()


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
        
        # Получаем статистику рефералов
        from sqlalchemy import select, func as sql_func
        from database.models import User as UserModel
        
        # Считаем всех приглашенных
        total_referrals_query = select(sql_func.count(UserModel.id)).where(UserModel.referrer_id == user.id)
        total_referrals = await session.scalar(total_referrals_query) or 0
        
        # Получаем данные для текста
        from utils.referral_helpers import get_loyalty_name, get_bonus_percent_for_level
        from utils.constants import MIN_WITHDRAWAL_AMOUNT
        
        balance = user.referral_balance or 0
        total_earned = user.total_earned_referral or 0
        total_paid = user.total_referrals_paid or 0
        loyalty_level = user.current_loyalty_level or 'none'
        level_name = get_loyalty_name(loyalty_level)
        bonus_percent = get_bonus_percent_for_level(loyalty_level)
        
        # Формируем текст через helper
        from utils.referral_messages import get_referral_program_text
        text = get_referral_program_text(
            balance,
            total_earned,
            total_referrals,
            total_paid,
            level_name,
            bonus_percent,
            referral_link
        )
        
        # Создаем клавиатуру
        keyboard_buttons = [
            [InlineKeyboardButton(
                text="📤 Поделиться ссылкой",
                switch_inline_query=f"Присоединяйся к Mom's Club по моей ссылке! {referral_link}"
            )]
        ]
        
        # Кнопка вывода (если баланс >= минимума)
        if balance >= MIN_WITHDRAWAL_AMOUNT:
            keyboard_buttons.append([
                InlineKeyboardButton(text="💸 Вывести средства", callback_data="ref_withdraw")
            ])
        
        # Кнопка истории
        keyboard_buttons.append([
            InlineKeyboardButton(text="📊 История начислений", callback_data="ref_history")
        ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Отправляем новое сообщение
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )


# Обработчик копирования реферальной ссылки
@user_router.callback_query(F.data.startswith("copy_link:"))
async def process_copy_link(callback: types.CallbackQuery):
    # Извлекаем ссылку из callback data
    link = callback.data.split(":", 1)[1]
    
    await callback.answer("Ссылка скопирована! Отправьте её друзьям.", show_alert=True)


# Обработчик истории платежей
@user_router.callback_query(F.data == "payment_history")
async def process_payment_history(callback: types.CallbackQuery):
    """Отображает историю платежей пользователя с улучшенным форматированием и статистикой"""
    log_message(callback.from_user.id, "payment_history", "action")
    
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем историю платежей
        payments = await get_user_payment_history(session, user.id, limit=20)
        
        if not payments:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")]
                ]
            )
            await callback.message.answer(
                "💳 <b>История платежей</b>\n\n"
                "У вас пока нет платежей.\n"
                "Оформите подписку, чтобы начать пользоваться Mom's Club! 💕",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()
            return
        
        # Вычисляем статистику
        total_amount = sum(p.amount for p in payments)
        total_count = len(payments)
        avg_amount = total_amount / total_count if total_count > 0 else 0
        
        # Группируем платежи по месяцам
        payments_by_month = defaultdict(list)
        month_names = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
        }
        
        for payment in payments:
            month_key = (payment.created_at.year, payment.created_at.month)
            payments_by_month[month_key].append(payment)
        
        # Формируем текст с историей
        history_lines = [
            "💳 <b>История платежей</b>\n",
            f"📊 <b>Статистика:</b>\n"
            f"• Всего платежей: <b>{total_count}</b>\n"
            f"• Общая сумма: <b>{total_amount:.0f} ₽</b>\n"
            f"• Средний чек: <b>{avg_amount:.0f} ₽</b>\n",
            "━━━━━━━━━━━━━━━━━━━━\n"
        ]
        
        # Сортируем месяцы по убыванию (новые первыми)
        sorted_months = sorted(payments_by_month.keys(), reverse=True)
        
        for year, month in sorted_months:
            month_payments = payments_by_month[(year, month)]
            month_name = month_names[month]
            history_lines.append(f"\n📅 <b>{month_name} {year}</b>\n")
            
            for payment in month_payments:
                # Форматируем дату
                date_str = payment.created_at.strftime("%d.%m.%Y %H:%M")
                
                # Статус платежа
                status_emoji = {
                    'success': '✅',
                    'pending': '⏳',
                    'failed': '❌'
                }
                status_icon = status_emoji.get(payment.status, '❓')
                
                # Метод оплаты (красивое отображение)
                method_map = {
                    'yookassa': '💳 ЮKassa',
                    'prodamus': '💳 Prodamus',
                    'youkassa_autopay': '🔄 Автопродление',
                    'youkassa': '💳 ЮKassa',
                    'admin': '🎁 Подарок от админа',
                    'referral_balance': '💰 Оплата балансом'
                }
                method = method_map.get(payment.payment_method, payment.payment_method or "💳 Не указан")
                
                # Дни подписки
                days_info = f" • {payment.days} дней" if payment.days else ""
                
                history_lines.append(
                    f"{status_icon} <b>{date_str}</b>\n"
                    f"   💰 <b>{payment.amount:.0f} ₽</b>{days_info}\n"
                    f"   {method}\n"
                )
        
        history_text = "\n".join(history_lines)
        
        # Если платежей много, ограничиваем длину сообщения
        if len(history_text) > 4000:
            # Оставляем статистику и первые 10 платежей
            limited_lines = history_lines[:3]  # Заголовок и статистика
            payment_count = 0
            for year, month in sorted_months:
                if payment_count >= 10:
                    break
                month_payments = payments_by_month[(year, month)]
                month_name = month_names[month]
                limited_lines.append(f"\n📅 <b>{month_name} {year}</b>\n")
                
                for payment in month_payments:
                    if payment_count >= 10:
                        break
                    date_str = payment.created_at.strftime("%d.%m.%Y %H:%M")
                    status_icon = '✅' if payment.status == 'success' else '⏳' if payment.status == 'pending' else '❌'
                    method_map = {
                        'yookassa': '💳 ЮKassa',
                        'prodamus': '💳 Prodamus',
                        'youkassa_autopay': '🔄 Автопродление',
                        'youkassa': '💳 ЮKassa'
                    }
                    method = method_map.get(payment.payment_method, payment.payment_method or "💳 Не указан")
                    days_info = f" • {payment.days} дней" if payment.days else ""
                    limited_lines.append(
                        f"{status_icon} <b>{date_str}</b>\n"
                        f"   💰 <b>{payment.amount:.0f} ₽</b>{days_info}\n"
                        f"   {method}\n"
                    )
                    payment_count += 1
            
            remaining = total_count - payment_count
            if remaining > 0:
                limited_lines.append(f"\n\n... и еще <b>{remaining}</b> платежей")
            
            history_text = "\n".join(limited_lines)
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Назад в профиль", callback_data="back_to_profile")]
            ]
        )
        
        try:
            await callback.message.delete()
        except:
            pass
        
        await callback.message.answer(
            history_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer()


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
            error_msg = format_user_error_message(Exception("Пользователь не найден в базе данных"), "при поиске пользователя")
            await message.answer(error_msg)
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
                    error_msg = format_user_error_message(Exception("Не удалось применить промокод"), "при применении промокода")
                    await message.answer(error_msg)
                    await state.clear()
                    return

                # Отмечаем использование промокода
                await use_promo_code(session, db_user.id, promo_code.id)
                
                # Формируем сообщение об успехе (с учетом пожизненной подписки)
                end_date_formatted = format_subscription_end_date(subscription, escape_for_markdown=True)
                success_text = (
                    f"🎉 Промокод *{escape_markdown_v2(promo_code.code)}* успешно активирован\\!\n\n"
                    f"🎁 Вам добавлено *{bonus_days} дней* подписки\\.\n"
                    f"Теперь ваша подписка активна до *{end_date_formatted}*\\.\n\n"
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

            elif promo_code.discount_type == 'percent':
                # Применяем процентный промокод
                from database.crud import apply_promo_code_percent
                success = await apply_promo_code_percent(session, db_user.id, promo_code.id)
                
                if not success:
                    error_msg = format_user_error_message(Exception("Не удалось применить промокод"), "при применении промокода")
                    await message.answer(error_msg)
                    await state.clear()
                    return
                
                # Формируем сообщение об успехе
                expiry_date_str = promo_code.expiry_date.strftime("%d.%m.%Y") if promo_code.expiry_date else "не ограничен"
                
                success_text = (
                    f"✅ <b>Промокод применен!</b>\n\n"
                    f"🎁 Ваша скидка: <b>{promo_code.value}%</b>\n"
                    f"⏰ Действует до: <b>{expiry_date_str}</b>\n\n"
                    f"Теперь выберите тариф и оплатите со скидкой!"
                )
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Выбрать тариф со скидкой", callback_data="subscribe")],
                        [InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
                    ]
                )
                
                await message.answer(success_text, reply_markup=keyboard, parse_mode="HTML")
                await state.clear()
                logger.info(f"Процентный промокод {promo_code_text} успешно применен для пользователя {user_id}")

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
            error_msg = format_user_error_message(e, "при применении промокода")
            await message.answer(error_msg)
            await state.clear()

# Обработчик отмены ввода промокода
@user_router.callback_query(F.data == "back_to_profile", StateFilter(PromoCodeStates.waiting_for_promo_code))
async def cancel_promo_code_input(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Ввод промокода отменен")
    await process_back_to_profile(callback)

# Обработчик кнопки "Использовать промокод"
@user_router.callback_query(F.data.startswith("use_return_promo:"))
async def process_use_return_promo(callback: types.CallbackQuery):
    """
    Обработчик кнопки "Использовать промокод"
    Применяет персональный промокод и показывает сообщение с кнопкой выбора тарифа
    """
    log_message(callback.from_user.id, "use_return_promo", "action")
    
    try:
        # Извлекаем ID промокода из callback_data
        promo_code_id = int(callback.data.split(":")[1])
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            
            # Применяем промокод
            from database.crud import apply_promo_code_percent
            success = await apply_promo_code_percent(session, user.id, promo_code_id)
            
            if not success:
                await callback.answer("❌ Не удалось применить промокод. Возможно, он уже использован или истек.", show_alert=True)
                return
            
            # Получаем промокод для отображения информации
            from database.crud import get_promo_code_by_id
            promo_code = await get_promo_code_by_id(session, promo_code_id)
            
            if not promo_code:
                await callback.answer("Промокод не найден", show_alert=True)
                return
            
            # Формируем сообщение об успешном применении
            expiry_date_str = promo_code.expiry_date.strftime("%d.%m.%Y") if promo_code.expiry_date else "не ограничен"
            
            success_text = (
                f"✅ <b>Промокод применен!</b>\n\n"
                f"🎁 Ваша персональная скидка: <b>{promo_code.value}%</b>\n"
                f"⏰ Действует до: <b>{expiry_date_str}</b>\n\n"
                f"Теперь выберите тариф и оплатите со скидкой!"
            )
            
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Выбрать тариф со скидкой", callback_data="subscribe")],
                    [InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
                ]
            )
            
            try:
                await callback.message.delete()
            except Exception:
                pass
            
            await callback.message.answer(
                success_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await callback.answer()
            
    except ValueError:
        await callback.answer("Ошибка: некорректный ID промокода", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при применении промокода через кнопку: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при применении промокода", show_alert=True)

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

        # Форматируем дату окончания (с учетом пожизненной подписки)
        end_date_str = format_subscription_end_date(active_sub, escape_for_markdown=True)
        # Автопродление активно, если is_recurring_active=True
        is_autorenewal_active = user.is_recurring_active
        autorenewal_status_text = "Включено ✅" if is_autorenewal_active else "Отключено ❌"

        # Экранируем динамические части
        escaped_end_date = end_date_str  # Уже экранировано в format_subscription_end_date
        escaped_autorenewal_status = escape_markdown_v2(autorenewal_status_text)
        escaped_start_date = escape_markdown_v2(active_sub.start_date.strftime("%d.%m.%Y"))

        # Формируем блок информации о подписке
        profile_info_text = f"🗓 Подписка оформлена: *{escaped_start_date}*\n"
        profile_info_text += f"📆 Действует до: *{escaped_end_date}*\n"

        # Форматируем оставшиеся дни (с учетом пожизненной подписки)
        days_text_for_profile = format_subscription_days_left(active_sub, escape_for_markdown=True)
        profile_info_text += f"⏳ Осталось: *{days_text_for_profile}*\n"
        profile_info_text += f"🔐 Статус подписки: *Активна* ✅\n\n"

        # Формируем информацию о лояльности
        loyalty_status_detailed = await format_loyalty_status_detailed(session, user)
        # Экранирование уже выполнено в функции format_loyalty_status_detailed
        loyalty_status_escaped = loyalty_status_detailed

        manage_text = f"⚙️ *Управление подпиской Mom's Club*\n\n"
        manage_text += profile_info_text
        manage_text += loyalty_status_escaped + "\n"
        manage_text += f"🔄 Статус автопродления: *{escaped_autorenewal_status}*\n\n"

        if not is_autorenewal_active:
            # Показываем информацию о возможности включения
            info_text = "ℹ️ Вы можете включить автопродление для автоматического продления подписки."
            manage_text += escape_markdown_v2(info_text) + "\n\n"
        else:
            info_text = "✅ Ваша подписка будет автоматически продлеваться."
            manage_text += escape_markdown_v2(info_text) + "\n\n"

        inline_keyboard_buttons = []
        
        # НОВАЯ КНОПКА: Досрочное продление
        from utils.early_renewal import check_early_renewal_eligibility
        from datetime import datetime as dt_now
        
        can_renew, reason, info = await check_early_renewal_eligibility(session, user.id)
        if info and info.get('bonus_eligible'):
            inline_keyboard_buttons.append([InlineKeyboardButton(
                text="🎁 Продлить досрочно с бонусом +3 дня",
                callback_data="early_renewal"
            )])
        else:
            inline_keyboard_buttons.append([InlineKeyboardButton(
                text="💎 Продлить подписку",
                callback_data="early_renewal"
            )])
        
        # Основная кнопка переключения автопродления
        if is_autorenewal_active:
            # НОВАЯ СИСТЕМА: создание заявки вместо прямой отмены
            inline_keyboard_buttons.append([InlineKeyboardButton(text="🚫 Отменить автопродление", callback_data="request_cancel_autorenewal")])
            # СТАРАЯ СИСТЕМА ОТКЛЮЧЕНА (но функция сохранена):
            # inline_keyboard_buttons.append([InlineKeyboardButton(text="🚫 Отключить автопродление", callback_data="disable_autorenewal")])
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

# НОВЫЙ обработчик - создание заявки на отмену автопродления
@user_router.callback_query(F.data == "request_cancel_autorenewal")
async def process_request_cancel_autorenewal(callback: types.CallbackQuery):
    """Обработчик кнопки 'Отменить автопродление' - показывает причины"""
    logger.info(f"[REQUEST_CANCEL_RENEWAL] User {callback.from_user.id} requested cancellation.")
    log_message(callback.from_user.id, "request_cancel_autorenewal", "action")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            logger.warning(f"[REQUEST_CANCEL_RENEWAL] User {callback.from_user.id} not found in DB.")
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        if not user.is_recurring_active:
            await callback.answer("У вас уже отключено автопродление.", show_alert=True)
            await process_manage_subscription(callback)
            return

        # Проверяем streak — если есть, показываем предупреждение
        streak = user.autopay_streak or 0
        if streak > 0:
            from utils.autopay_bonus import get_next_streak_bonus_days, format_streak_warning_message
            next_bonus = get_next_streak_bonus_days(streak)
            
            warning_text = format_streak_warning_message(streak, next_bonus)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Всё равно отключить", callback_data="confirm_cancel_autorenewal")],
                [InlineKeyboardButton(text="💕 Оставить автопродление", callback_data="manage_subscription")]
            ])
            
            try:
                await callback.message.edit_text(
                    warning_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except:
                await callback.message.answer(
                    warning_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            
            await callback.answer()
            return

        # Показываем выбор причины отмены (если нет streak)
        text = (
            "🤔 <b>Почему вы хотите отменить автопродление?</b>\n\n"
            "Пожалуйста, выберите причину, это поможет нам стать лучше 💖"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Дорого", callback_data="cancel_reason_expensive")],
            [InlineKeyboardButton(text="📉 Не использую контент", callback_data="cancel_reason_no_use")],
            [InlineKeyboardButton(text="⏸ Временная пауза", callback_data="cancel_reason_pause")],
            [InlineKeyboardButton(text="😞 Не оправдал ожидания", callback_data="cancel_reason_expectations")],
            [InlineKeyboardButton(text="🔄 Технические проблемы", callback_data="cancel_reason_technical")],
            [InlineKeyboardButton(text="💭 Другая причина", callback_data="cancel_reason_other")],
            [InlineKeyboardButton(text="« Назад", callback_data="manage_subscription")]
        ])
        
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        
        await callback.answer()


# Обработчик подтверждения отмены после предупреждения о streak
@user_router.callback_query(F.data == "confirm_cancel_autorenewal")
async def process_confirm_cancel_autorenewal(callback: types.CallbackQuery):
    """Показывает причины отмены после подтверждения потери streak"""
    logger.info(f"[CONFIRM_CANCEL_RENEWAL] User {callback.from_user.id} confirmed streak loss.")
    
    # Показываем выбор причины отмены
    text = (
        "🤔 <b>Почему вы хотите отменить автопродление?</b>\n\n"
        "Пожалуйста, выберите причину, это поможет нам стать лучше 💖"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Дорого", callback_data="cancel_reason_expensive")],
        [InlineKeyboardButton(text="📉 Не использую контент", callback_data="cancel_reason_no_use")],
        [InlineKeyboardButton(text="⏸ Временная пауза", callback_data="cancel_reason_pause")],
        [InlineKeyboardButton(text="😞 Не оправдал ожидания", callback_data="cancel_reason_expectations")],
        [InlineKeyboardButton(text="🔄 Технические проблемы", callback_data="cancel_reason_technical")],
        [InlineKeyboardButton(text="💭 Другая причина", callback_data="cancel_reason_other")],
        [InlineKeyboardButton(text="« Назад", callback_data="manage_subscription")]
    ])
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
    
    await callback.answer()


# Обработчики выбора причины отмены
@user_router.callback_query(F.data.startswith("cancel_reason_"))
async def process_cancel_reason(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора причины отмены автопродления"""
    reason_code = callback.data.replace("cancel_reason_", "")
    
    # Если выбрана "Другая причина" - запрашиваем ввод
    if reason_code == "other":
        await state.set_state(CancelRenewalStates.waiting_for_custom_reason)
        
        text = (
            "💭 <b>Напишите свою причину отмены автопродления</b>\n\n"
            "Это поможет нам стать лучше 💖"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к выбору", callback_data="request_cancel_autorenewal")]
        ])
        
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        
        await callback.answer()
        return
    
    # Маппинг кодов на текстовые причины
    reasons = {
        "expensive": "💸 Дорого",
        "no_use": "📉 Не использую контент",
        "pause": "⏸ Временная пауза",
        "expectations": "😞 Не оправдал ожидания",
        "technical": "🔄 Технические проблемы"
    }
    
    reason_text = reasons.get(reason_code, "Не указана")
    
    try:
        # Создаем заявку
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            if not user:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return

            user_id = user.id
            request = await create_autorenewal_cancellation_request(session, user_id, reason=reason_text)
            request_id = request.id
            logger.info(f"[REQUEST_CANCEL_RENEWAL] Created request ID {request_id} for user {user_id} with reason: {reason_text}")
        
        # Отправляем уведомления (в новой сессии)
        from bot import bot
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            if user:
                await send_cancellation_request_notifications(bot, user, request_id, reason_text)
        
        await callback.answer("✅ Заявка создана", show_alert=False)
        
        # Отправляем подтверждение пользователю
        confirmation_text = (
            "✅ <b>Ваша заявка на отмену автопродления принята!</b>\n\n"
            f"📝 Причина: {reason_text}\n\n"
            "⏳ Заявка будет рассмотрена в ближайшее время.\n"
            "Мы свяжемся с вами для уточнения деталей.\n\n"
            "🤎 Спасибо за обратную связь!"
        )
        
        try:
            await callback.message.edit_text(
                confirmation_text,
                parse_mode="HTML"
            )
        except:
            await callback.message.answer(
                confirmation_text,
                parse_mode="HTML"
            )
        
        # Через 3 секунды возвращаем в управление подпиской
        import asyncio
        await asyncio.sleep(3)
        await process_manage_subscription(callback)
        
    except Exception as e:
        logger.error(f"[REQUEST_CANCEL_RENEWAL] Error creating request: {e}", exc_info=True)
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)


# Обработчик ввода своей причины отмены
@user_router.message(StateFilter(CancelRenewalStates.waiting_for_custom_reason))
async def process_custom_cancel_reason(message: types.Message, state: FSMContext):
    """Обработчик ввода своей причины отмены автопродления"""
    custom_reason = message.text.strip()
    
    if len(custom_reason) < 5:
        await message.answer(
            "❌ Причина слишком короткая. Пожалуйста, опишите подробнее (минимум 5 символов)."
        )
        return
    
    if len(custom_reason) > 500:
        await message.answer(
            "❌ Причина слишком длинная. Пожалуйста, сократите до 500 символов."
        )
        return
    
    reason_text = f"💭 Другая причина: {custom_reason}"
    
    try:
        # Создаем заявку
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, message.from_user.id)
            if not user:
                await message.answer("Пользователь не найден.")
                await state.clear()
                return

            user_id = user.id
            request = await create_autorenewal_cancellation_request(session, user_id, reason=reason_text)
            request_id = request.id
            logger.info(f"[REQUEST_CANCEL_RENEWAL] Created request ID {request_id} for user {user_id} with custom reason")
        
        # Отправляем уведомления (в новой сессии)
        from bot import bot
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, message.from_user.id)
            if user:
                await send_cancellation_request_notifications(bot, user, request_id, reason_text)
        
        # Отправляем подтверждение пользователю
        confirmation_text = (
            "✅ <b>Ваша заявка на отмену автопродления принята!</b>\n\n"
            f"📝 Причина: {custom_reason}\n\n"
            "⏳ Заявка будет рассмотрена в ближайшее время.\n"
            "Мы свяжемся с вами для уточнения деталей.\n\n"
            "🤎 Спасибо за обратную связь!"
        )
        
        await message.answer(
            confirmation_text,
            parse_mode="HTML"
        )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"[REQUEST_CANCEL_RENEWAL] Error creating request with custom reason: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")
        await state.clear()


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
            error_msg = format_user_error_message(Exception("Данные сессии потеряны"), "при сохранении даты рождения")
            await message.answer(error_msg)
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

                # Применяем скидку лояльности
                discount_percent = effective_discount(user)
                final_price = price_with_discount(price, discount_percent)
                
                # Создаем платеж с учётом скидки
                payment_url, payment_id, payment_label = create_payment_link(
                    amount=final_price,
                    user_id=user.telegram_id,
                    description=f"Продление подписки на Mom's Club на {days} дней (username: @{user.username})",
                    sub_type=sub_type,
                    days=days,
                    phone=user.phone,
                    discount_percent=discount_percent
                )
                
                if not payment_url or not payment_id:
                    error_msg = format_user_error_message(Exception("Не удалось создать ссылку на оплату"), "при создании платежа для продления")
                    await callback.answer(error_msg, show_alert=True)
                    return
                
                # Создаем запись о платеже (сохраняем исходную цену и скидку)
                details_text = f"Продление подписки на {days} дней (c обновлением параметров автопродления)"
                if discount_percent > 0:
                    details_text += f" | Скидка лояльности: {discount_percent}% (было {price}₽, стало {final_price}₽)"
                
                await create_payment_log(
                    session,
                    user_id=user.id,
                    amount=final_price,  # Сохраняем итоговую сумму с учётом скидки
                    status="pending",
                    payment_method="yookassa",
                    transaction_id=payment_id,
                    details=details_text,
                    payment_label=payment_label,
                    days=days
                )
                
                # Формируем текст с учётом скидки
                price_text = f"{final_price} ₽"
                if discount_percent > 0:
                    price_text += f" <s>{price} ₽</s> <b>(−{discount_percent}%)</b>"
                
                from utils.balance_payment_helpers import (
                    can_pay_with_balance,
                    format_balance_payment_message
                )

                user_balance = user.referral_balance or 0
                has_enough_balance = can_pay_with_balance(user_balance, final_price)
                payment_text, _ = format_balance_payment_message(
                    user_balance,
                    final_price,
                    days,
                    discount_percent
                )

                keyboard_buttons = []

                if has_enough_balance:
                    # Сокращаем для уменьшения длины callback_data
                    sub_short = sub_type.replace("momclub_subscription_", "").replace("month", "m")
                    keyboard_buttons.append([
                        InlineKeyboardButton(
                            text=f"💰 Оплатить балансом ({final_price:,}₽)",
                            callback_data=f"cbp:{final_price}:{days}:{sub_short}:e:{renewal_price}:{renewal_duration_days}"
                        )
                    ])

                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text=f"💳 Оплатить картой ({final_price:,}₽)",
                        url=payment_url
                    )
                ])

                keyboard_buttons.append([
                    InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")
                ])

                keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

                # Отправляем сообщение с информацией о продлении и кнопками оплаты
                renewal_text = f"""<b>🎉 Продление подписки на Mom's Club</b>

<b>Выбранный тариф:</b> {days} дней за {price_text}

<b>После оплаты:</b>
• Ваша подписка будет продлена
• Параметры автопродления будут обновлены
{f"• Применена скидка лояльности: {discount_percent}%" if discount_percent > 0 else ""}

<i>Для продолжения выбери способ оплаты ниже</i>"""

                full_text = f"{renewal_text}\n\n{payment_text}"
                
                try:
                    # Удаляем текущее сообщение
                    await callback.message.delete()
                    # Отправляем новое сообщение с информацией о платеже
                    await callback.message.answer(
                        full_text,
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
            error_msg = format_user_error_message(e, "при обработке платежа для продления")
            await callback.answer(error_msg, show_alert=True)
        
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
                    error_msg = format_user_error_message(Exception("Не удалось создать ссылку на оплату"), "при создании платежа")
                    await message.answer(error_msg)
                    return
                
                # Создаем запись о платеже
                await create_payment_log(
                    session,
                    user_id=user.id,
                    amount=price,
                    status="pending",
                    payment_method="yookassa",
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
            error_msg = format_user_error_message(e, "при обработке данных для оплаты")
            await message.answer(error_msg, reply_markup=main_keyboard)
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

    # Обработчик выбора бонуса лояльности
@user_router.callback_query(F.data.startswith("benefit:"))
async def process_loyalty_benefit_choice(callback: types.CallbackQuery):
    """Обрабатывает выбор бонуса лояльности пользователем"""
    try:
        # Парсим callback_data: benefit:<level>:<code>
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Неверный формат данных", show_alert=True)
            return
        
        _, level, code = parts
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return
            
            # Проверяем идемпотентность - проверяем, был ли уже выбран бонус для этого уровня
            from sqlalchemy import select
            from database.models import LoyaltyEvent
            
            benefit_check = await session.execute(
                select(LoyaltyEvent.id).where(
                    LoyaltyEvent.user_id == user.id,
                    LoyaltyEvent.kind == 'benefit_chosen',
                    LoyaltyEvent.level == level
                )
            )
            
            if benefit_check.scalar_one_or_none():
                await callback.answer("Бонус для этого уровня уже выбран ✨", show_alert=True)
                # Убираем клавиатуру, если она еще есть
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except:
                    pass
                return
            
            # Дополнительная проверка через флаг (для обратной совместимости)
            if not user.pending_loyalty_reward:
                await callback.answer("Бонус уже применён ✨", show_alert=True)
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except:
                    pass
                return
            
            # Валидация уровня и кода
            valid_levels = ['silver', 'gold', 'platinum']
            valid_codes = ['days_7', 'days_14', 'days_30_gift', 'discount_5', 'discount_10', 'discount_15_forever']
            
            # ПРОВЕРКА: Если выбран бонус с днями — нужна активная подписка
            if code in ['days_7', 'days_14', 'days_30_gift']:
                has_sub = await has_active_subscription(session, user.id)
                if not has_sub:
                    # Показываем сообщение с кнопкой оплаты
                    no_sub_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Оплатить подписку", callback_data="payment_1month")],
                    ])
                    await callback.message.edit_text(
                        "💕 Красотка, для получения бонусных дней нужна активная подписка\\!\n\n"
                        "Оплати — и подарок сразу твой ✨",
                        reply_markup=no_sub_keyboard,
                        parse_mode="MarkdownV2"
                    )
                    await callback.answer()
                    return
            
            if level not in valid_levels:
                await callback.answer("Неверный уровень лояльности", show_alert=True)
                return
            
            if code not in valid_codes:
                await callback.answer("Неверный код бонуса", show_alert=True)
                return
            
            # ИСПРАВЛЕНИЕ БАГА: Проверяем, что уровень в callback соответствует АКТУАЛЬНОМУ рассчитанному уровню
            # Это предотвращает применение бонуса с устаревшим уровнем из старого сообщения
            from loyalty.levels import calc_tenure_days, level_for_days
            tenure_days = await calc_tenure_days(session, user)
            actual_level = level_for_days(tenure_days)
            
            if level != actual_level:
                logger.warning(
                    f"⚠️ Несоответствие уровней для user_id={user.id}: "
                    f"callback={level}, actual={actual_level}, db={user.current_loyalty_level}, tenure={tenure_days}"
                )
                await callback.answer(
                    f"Твой текущий уровень: {actual_level}. Бонус для {level} недоступен.", 
                    show_alert=True
                )
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except:
                    pass
                return
            
            # Применяем бонус
            success = await apply_benefit_from_callback(session, user, level, code)
            
            if success:
                # Формируем детали бонуса для уведомления админам
                benefit_details = {}
                if code in ['days_7', 'days_14', 'days_30_gift']:
                    days_map = {'days_7': 7, 'days_14': 14, 'days_30_gift': 30}
                    benefit_details['days'] = days_map.get(code, 0)
                elif code in ['discount_5', 'discount_10', 'discount_15_forever']:
                    discount_map = {'discount_5': 5, 'discount_10': 10, 'discount_15_forever': 15}
                    benefit_details['discount_percent'] = discount_map.get(code, 0)
                
                # Отправляем уведомление администраторам
                try:
                    logger.info(f"Отправка уведомления админам о выборе бонуса: user_id={user.id}, level={level}, code={code}")
                    await send_loyalty_benefit_notification_to_admins(
                        callback.bot, 
                        user, 
                        level, 
                        code,
                        benefit_details
                    )
                    logger.info(f"✅ Уведомление админам успешно отправлено для user_id={user.id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке уведомления админам о выборе бонуса для user_id={user.id}: {e}", exc_info=True)
                
                # Убираем inline-клавиатуру у сообщения
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except:
                    pass  # Если не удалось убрать клавиатуру, продолжаем
                
                # Отправляем подтверждение
                await callback.answer("✅ Готово! Бонус применён ✨", show_alert=False)
                
                # Отправляем отдельное сообщение с деталями
                benefit_texts = {
                    'days_7': (
                        '🎁 <b>Готово, красотка!</b> ✨\n\n'
                        'Мы добавили тебе <b>+7 дней</b> доступа к клубу! 🩷\n\n'
                        'Наслаждайся контентом и общением с девочками ещё дольше 💖'
                    ),
                    'days_14': (
                        '🎁 <b>Готово, красотка!</b> ✨\n\n'
                        'Мы добавили тебе <b>+14 дней</b> доступа к клубу! 🩷\n\n'
                        'Теперь у тебя ещё больше времени для вдохновения и роста! 💖'
                    ),
                    'days_30_gift': (
                        '🎁 <b>Ого, как же мы рады!</b> 😍✨\n\n'
                        'Мы добавили тебе <b>+1 месяц</b> доступа к клубу!\n\n'
                        'А ещё у тебя есть особенный подарок 🎀\n'
                        'Мы свяжемся с тобой в ближайшее время для доставки — жди от нас сообщение! 💌\n\n'
                        'Спасибо, что ты с нами целый год! 🩷🫂'
                    ),
                    'discount_5': (
                        '💰 <b>Отлично, красотка!</b> ✨\n\n'
                        'Теперь у тебя <b>постоянная скидка 5%</b> на все продления подписки! 💖\n\n'
                        'Это наша благодарность за твою верность 🩷\n'
                        'Ты всегда будешь платить меньше — просто за то, что ты с нами! 🫂'
                    ),
                    'discount_10': (
                        '💰 <b>Отлично, красотка!</b> ✨\n\n'
                        'Теперь у тебя <b>постоянная скидка 10%</b> на все продления подписки! 💖\n\n'
                        'Это наша благодарность за твою верность 🩷\n'
                        'Ты всегда будешь платить меньше — просто за то, что ты с нами! 🫂'
                    ),
                    'discount_15_forever': (
                        '💎 <b>Поздравляем, красотка!</b> 😍✨\n\n'
                        'Теперь у тебя <b>пожизненная скидка 15%</b> на все продления подписки! 🎀\n\n'
                        'Это наша благодарность за целый год вместе 💖\n'
                        'Ты всегда будешь платить меньше — просто за то, что ты с нами! 🩷🫂'
                    ),
                }
                
                benefit_text = benefit_texts.get(code, '🎁 Бонус успешно применён!')
                
                await callback.bot.send_message(
                    chat_id=user.telegram_id,
                    text=benefit_text,
                    parse_mode="HTML"
                )
            else:
                error_msg = format_user_error_message(Exception("Не удалось применить бонус"), "при применении бонуса лояльности")
                await callback.answer(error_msg, show_alert=True)
                
    except Exception as e:
        logger.error(f"Ошибка при обработке выбора бонуса лояльности: {e}", exc_info=True)
        error_msg = format_user_error_message(e, "при выборе бонуса лояльности")
        await callback.answer(error_msg, show_alert=True)

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


# ==================== FAQ (ЧАСТЫЕ ВОПРОСЫ) ====================

@user_router.message(lambda message: message.text in ["❓ Частые вопросы", "Частые вопросы", "FAQ"])
async def process_faq(message: types.Message):
    """Обработчик кнопки 'Частые вопросы'"""
    log_message(message.from_user.id, "faq_menu", "command")
    
    faq_text = """❓ <b>Частые вопросы</b>

Выбери интересующий тебя вопрос, красотка! 💖"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎀 Как пользоваться личным кабинетом?", callback_data="faq_cabinet")],
            [InlineKeyboardButton(text="💳 Как купить/продлить подписку?", callback_data="faq_purchase")],
            [InlineKeyboardButton(text="💎 Что такое лояльность?", callback_data="faq_loyalty")],
            [InlineKeyboardButton(text="🏆 Что такое достижения?", callback_data="faq_badges")],
            [InlineKeyboardButton(text="👭 Что дает реферальная программа?", callback_data="faq_referral")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_faq_message")]
        ]
    )
    
    await message.answer(faq_text, reply_markup=keyboard, parse_mode="HTML")


@user_router.callback_query(F.data == "back_to_faq")
async def process_back_to_faq(callback: types.CallbackQuery):
    """Возврат в меню FAQ"""
    log_message(callback.from_user.id, "back_to_faq", "callback")
    
    faq_text = """❓ <b>Частые вопросы</b>

Выбери интересующий тебя вопрос, красотка! 💖"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎀 Как пользоваться личным кабинетом?", callback_data="faq_cabinet")],
            [InlineKeyboardButton(text="💳 Как купить/продлить подписку?", callback_data="faq_purchase")],
            [InlineKeyboardButton(text="💎 Что такое лояльность?", callback_data="faq_loyalty")],
            [InlineKeyboardButton(text="🏆 Что такое достижения?", callback_data="faq_badges")],
            [InlineKeyboardButton(text="👭 Что дает реферальная программа?", callback_data="faq_referral")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="close_faq_message")]
        ]
    )
    
    try:
        await callback.message.edit_text(faq_text, reply_markup=keyboard, parse_mode="HTML")
    except:
        await callback.message.answer(faq_text, reply_markup=keyboard, parse_mode="HTML")
    
    await callback.answer()


@user_router.callback_query(F.data == "faq_cabinet")
async def process_faq_cabinet(callback: types.CallbackQuery):
    """FAQ: Как пользоваться личным кабинетом"""
    log_message(callback.from_user.id, "faq_cabinet", "callback")
    
    text = """🎀 <b>Как пользоваться личным кабинетом?</b>

Личный кабинет — твой центр управления подпиской!

Нажми на кнопку <b>"🎀 Личный кабинет"</b> в главном меню, и ты увидишь:

💎 <b>Управление подпиской</b>
   • Посмотреть когда заканчивается подписка
   • Включить/выключить автопродление
   • Продлить подписку досрочно с бонусом +3 дня

📊 <b>Твоя статистика</b>
   • Уровень лояльности (None/Silver/Gold/Platinum)
   • Количество дней в клубе
   • Твои достижения и награды

🎁 <b>Бонусы</b>
   • Персональные скидки
   • Реферальная программа
   • Специальные предложения

💡 Заходи в личный кабинет регулярно — там всегда что-то интересное! 💖"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к вопросам", callback_data="back_to_faq")]
        ]
    )
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    await callback.answer()


@user_router.callback_query(F.data == "faq_purchase")
async def process_faq_purchase(callback: types.CallbackQuery):
    """FAQ: Как купить/продлить подписку"""
    log_message(callback.from_user.id, "faq_purchase", "callback")
    
    text = """💳 <b>Как купить/продлить подписку?</b>

Купить или продлить подписку очень просто!

📍 <b>Если у тебя НЕТ подписки:</b>
1. Нажми <b>"🎀 Личный кабинет"</b>
2. Нажми <b>"💸 Оформить подписку"</b>
3. Выбери тариф (1, 2 или 3 месяца)
4. Оплати картой — и готово! 🎉

📍 <b>Если подписка ЗАКАНЧИВАЕТСЯ:</b>
1. Зайди в <b>"🎀 Личный кабинет"</b>
2. Нажми <b>"💎 Управление подпиской"</b>
3. Выбери <b>"💎 Продлить подписку"</b>
4. Выбери тариф и оплати

💡 <b>ЛАЙФХАК:</b> Включи автопродление — подписка будет продлеваться автоматически, и ты не потеряешь доступ! 🔄

🎁 <b>БОНУС:</b> Если продлишь за 7+ дней до окончания — получишь +3 дня в подарок! ✨"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к вопросам", callback_data="back_to_faq")]
        ]
    )
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    await callback.answer()


@user_router.callback_query(F.data == "faq_referral")
async def process_faq_referral(callback: types.CallbackQuery):
    """FAQ: Что дает реферальная программа"""
    log_message(callback.from_user.id, "faq_referral", "callback")
    
    text = """👭 <b>Что дает реферальная программа?</b>

Приглашай подруг и получай бонусы!

🎁 <b>Что ты получаешь:</b>
   • +7 дней подписки за каждую подругу 📅
   • Или деньги на баланс (10-30% от оплаты) 💰
   • При КАЖДОЙ оплате подруги — ты выбираешь награду! 🔄
   • Неограниченное количество приглашений!

💎 <b>От чего зависит процент:</b>

Твой процент зависит от уровня лояльности:

• <b>Bronze (10%)</b> — начальный уровень
• <b>Silver (15%)</b> — от 3 месяцев с подпиской
• <b>Gold (20%)</b> — от 6 месяцев с подпиской
• <b>Platinum (30%)</b> — от 1 года с подпиской

Чем дольше с нами — тем больше зарабатываешь! 🚀

📍 <b>Как это работает:</b>
1. Зайди в <b>"🎀 Личный кабинет"</b> или нажми /referral
2. Нажми <b>"🤝 Реферальная программа"</b>
3. Скопируй свою реферальную ссылку
4. Отправь подруге
5. Когда она оплатит подписку — выбери награду: деньги или дни! 🎉
6. При каждом продлении — снова выбирай награду! 💖

💡 <b>Что делать с заработанными деньгами:</b>
   • Оплатить свою подписку балансом (полная оплата) 💳
   • Вывести от 500₽ на карту или СБП 💸

Чем больше подруг и чем выше уровень лояльности — тем больше заработок!"""
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад к вопросам", callback_data="back_to_faq")]
        ]
    )
    
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    
    await callback.answer()


@user_router.callback_query(F.data == "close_faq_message")
async def process_close_faq(callback: types.CallbackQuery):
    """Закрытие меню FAQ с удалением сообщения"""
    log_message(callback.from_user.id, "close_faq", "callback")
    
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения FAQ: {e}")
    
    await callback.answer()

# Функция для регистрации всех обработчиков
def register_user_handlers(dp):
    # Регистрируем обработчик досрочного продления
    from handlers.early_renewal_handler import early_renewal_router
    dp.include_router(early_renewal_router)
    
    # Регистрируем основной роутер
    dp.include_router(user_router)

# Обработчик для кнопки с информацией о текущем отзыве
@user_router.callback_query(lambda c: c.data == "review_info")
async def process_review_info(callback: types.CallbackQuery):
    await callback.answer("Это индикатор текущей позиции в галерее отзывов")


# =============================================================================
# РЕФЕРАЛЬНАЯ СИСТЕМА 2.0 - ОБРАБОТЧИКИ ВЫБОРА НАГРАДЫ
# =============================================================================

@user_router.callback_query(F.data.startswith("ref_reward_money:"))
async def process_referral_reward_money(callback: types.CallbackQuery):
    """Обработчик выбора денежной награды"""
    try:
        # Парсим callback_data: ref_reward_money:referee_id:payment_id
        parts = callback.data.split(":")
        referee_id = int(parts[1])
        payment_id = int(parts[2])  # ID конкретного платежа
        
        async with AsyncSessionLocal() as session:
            referrer = await get_user_by_telegram_id(session, callback.from_user.id)
            referee = await get_user_by_id(session, referee_id)
            
            if not referrer or not referee:
                await callback.answer("❌ Ошибка: пользователь не найден", show_alert=True)
                return
            
            # НЕКРИТИЧЕСКАЯ ПРОБЛЕМА #2: Проверяем активную подписку реферера
            from database.crud import has_active_subscription
            if not await has_active_subscription(session, referrer.id):
                await callback.answer("💕 Красотка, для получения награды нужна активная подписка! Оплати — и бонус твой ✨", show_alert=True)
                return
            
            # КРИТИЧЕСКАЯ ПРОБЛЕМА #1: Получаем КОНКРЕТНЫЙ платеж по payment_id
            payment = await session.get(PaymentLog, payment_id)
            if not payment:
                await callback.answer("❌ Платеж не найден", show_alert=True)
                return
            
            # Проверяем, что платеж принадлежит рефералу и успешен
            if payment.user_id != referee.id or payment.status != 'success':
                await callback.answer("❌ Некорректный платеж", show_alert=True)
                return
            
            # Проверяем дубль по конкретному платежу (ИЗМЕНЕНО для Реферальной системы 3.0)
            from database.models import ReferralReward
            existing = await session.execute(
                select(ReferralReward).where(
                    ReferralReward.payment_id == payment.id
                )
            )
            if existing.scalar_one_or_none():
                await callback.answer("❌ Награда за этот платеж уже получена", show_alert=True)
                return
            
            # Проверяем право на деньги
            from database.crud import is_eligible_for_money_reward
            if not await is_eligible_for_money_reward(session, referrer.id):
                await callback.answer("❌ Денежные награды недоступны", show_alert=True)
                return
            
            # Начисляем
            from utils.referral_helpers import calculate_referral_bonus, get_bonus_percent_for_level
            from database.crud import add_referral_balance, create_referral_reward
            
            loyalty_level = referrer.current_loyalty_level or 'none'
            bonus_percent = get_bonus_percent_for_level(loyalty_level)
            money_amount = calculate_referral_bonus(payment.amount, loyalty_level)
            
            if not await add_referral_balance(session, referrer.id, money_amount, bot=callback.bot):
                await callback.answer("❌ Ошибка начисления", show_alert=True)
                return
            
            await create_referral_reward(
                session, referrer.id, referee.id, payment.amount,
                'money', money_amount, loyalty_level, bonus_percent, payment.id
            )
            
            await session.refresh(referrer)
            
            from utils.referral_messages import get_money_reward_success_text
            text = get_money_reward_success_text(money_amount, referrer.referral_balance)
            
            await callback.message.edit_text(text, parse_mode="HTML")
            await callback.answer("✅ Начислено!")
            
    except Exception as e:
        logger.error(f"Ошибка в ref_reward_money: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.callback_query(F.data.startswith("ref_reward_days:"))
async def process_referral_reward_days(callback: types.CallbackQuery):
    """Обработчик выбора дней подписки"""
    try:
        # Парсим callback_data: ref_reward_days:referee_id:payment_id
        parts = callback.data.split(":")
        referee_id = int(parts[1])
        payment_id = int(parts[2])  # ID конкретного платежа
        
        async with AsyncSessionLocal() as session:
            referrer = await get_user_by_telegram_id(session, callback.from_user.id)
            referee = await get_user_by_id(session, referee_id)
            
            if not referrer or not referee:
                await callback.answer("❌ Ошибка: пользователь не найден", show_alert=True)
                return
            
            # НЕКРИТИЧЕСКАЯ ПРОБЛЕМА #2: Проверяем активную подписку реферера
            from database.crud import has_active_subscription
            if not await has_active_subscription(session, referrer.id):
                await callback.answer("💕 Красотка, для получения награды нужна активная подписка! Оплати — и бонус твой ✨", show_alert=True)
                return
            
            # КРИТИЧЕСКАЯ ПРОБЛЕМА #1: Получаем КОНКРЕТНЫЙ платеж по payment_id
            payment = await session.get(PaymentLog, payment_id)
            if not payment:
                await callback.answer("❌ Платеж не найден", show_alert=True)
                return
            
            # Проверяем, что платеж принадлежит рефералу и успешен
            if payment.user_id != referee.id or payment.status != 'success':
                await callback.answer("❌ Некорректный платеж", show_alert=True)
                return
            
            # Проверяем дубль по конкретному платежу (ИЗМЕНЕНО для Реферальной системы 3.0)
            from database.models import ReferralReward
            existing = await session.execute(
                select(ReferralReward).where(
                    ReferralReward.payment_id == payment.id
                )
            )
            if existing.scalar_one_or_none():
                await callback.answer("❌ Награда за этот платеж уже получена", show_alert=True)
                return
            
            # Начисляем дни
            from utils.constants import REFERRAL_BONUS_DAYS
            from database.crud import extend_subscription_days, create_referral_reward
            from utils.referral_helpers import get_bonus_percent_for_level
            
            if not await extend_subscription_days(session, referrer.id, REFERRAL_BONUS_DAYS, reason=f"ref_{referee.id}"):
                await callback.answer("❌ Ошибка начисления", show_alert=True)
                return
            
            loyalty_level = referrer.current_loyalty_level or 'none'
            bonus_percent = get_bonus_percent_for_level(loyalty_level)
            
            await create_referral_reward(
                session, referrer.id, referee.id, payment.amount,
                'days', REFERRAL_BONUS_DAYS, loyalty_level, bonus_percent, payment.id
            )
            
            subscription = await get_active_subscription(session, referrer.id)
            end_date = subscription.end_date.strftime('%d.%m.%Y') if subscription else "н/д"
            
            from utils.referral_messages import get_days_reward_success_text
            text = get_days_reward_success_text(REFERRAL_BONUS_DAYS, end_date)
            
            await callback.message.edit_text(text, parse_mode="HTML")
            await callback.answer("✅ Начислено!")
            
    except Exception as e:
        logger.error(f"Ошибка в ref_reward_days: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.callback_query(F.data == "ref_history")
async def process_referral_history(callback: types.CallbackQuery):
    """Обработчик просмотра истории реферальных начислений"""
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            # Получаем историю наград
            from database.crud import get_referral_rewards
            rewards = await get_referral_rewards(session, user.id, limit=20)
            
            # Получаем историю выводов
            from database.models import WithdrawalRequest, AdminBalanceAdjustment
            from sqlalchemy import select
            withdrawals_query = select(WithdrawalRequest).where(
                WithdrawalRequest.user_id == user.id,
                WithdrawalRequest.status.in_(['approved', 'rejected'])
            ).order_by(WithdrawalRequest.created_at.desc()).limit(20)
            withdrawals_result = await session.execute(withdrawals_query)
            withdrawals = withdrawals_result.scalars().all()
            
            # Получаем ручные начисления админов
            adjustments_query = select(AdminBalanceAdjustment).where(
                AdminBalanceAdjustment.user_id == user.id
            ).order_by(AdminBalanceAdjustment.created_at.desc()).limit(20)
            adjustments_result = await session.execute(adjustments_query)
            adjustments = adjustments_result.scalars().all()
            
            # Объединяем операции
            all_operations = []
            
            # Добавляем награды
            for reward, referee in rewards:
                all_operations.append({
                    'type': 'reward',
                    'date': reward.created_at,
                    'data': reward,
                    'referee': referee
                })
            
            # Добавляем списания
            for withdrawal in withdrawals:
                all_operations.append({
                    'type': 'withdrawal',
                    'date': withdrawal.created_at,
                    'data': withdrawal
                })
            
            # Добавляем ручные начисления админов
            for adjustment in adjustments:
                all_operations.append({
                    'type': 'adjustment',
                    'date': adjustment.created_at,
                    'data': adjustment
                })
            
            # Сортируем по дате
            all_operations.sort(key=lambda x: x['date'], reverse=True)
            
            # Формируем текст
            text = f"📊 <b>История операций</b>\n\n"
            text += f"💰 Текущий баланс: {user.referral_balance or 0:,}₽\n\n"
            
            if not all_operations:
                text += "📋 Нет операций"
            else:
                for op in all_operations[:20]:
                    date_str = op['date'].strftime('%d.%m.%Y %H:%M')
                    
                    if op['type'] == 'reward':
                        reward = op['data']
                        referee = op['referee']
                        referee_name = referee.username or referee.first_name or f"ID:{referee.telegram_id}"
                        
                        if reward.reward_type == 'money':
                            text += f"💰 <b>+{reward.reward_amount}₽</b> от @{referee_name}\n"
                        else:
                            text += f"📅 <b>+{reward.reward_amount} дн.</b> от @{referee_name}\n"
                        
                        text += f"   {date_str}\n\n"
                    
                    elif op['type'] == 'withdrawal':
                        withdrawal = op['data']
                        status_emoji = "✅" if withdrawal.status == 'approved' else "❌"
                        status_text = "Одобрено" if withdrawal.status == 'approved' else "Отклонено"
                        text += f"💸 <b>-{withdrawal.amount:,}₽</b> вывод {status_emoji}\n"
                        text += f"   {status_text} · {date_str}\n\n"
                    
                    elif op['type'] == 'adjustment':
                        adjustment = op['data']
                        text += f"🎁 <b>+{adjustment.amount:,}₽</b> начислено админом\n"
                        text += f"   {date_str}\n\n"
            
            # Клавиатура
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="referral_program")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в ref_history: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


# =============================================================================
# ВЫВОД РЕФЕРАЛЬНЫХ СРЕДСТВ
# =============================================================================

@user_router.callback_query(F.data == "ref_withdraw")
async def start_withdrawal(callback: types.CallbackQuery):
    """Начало процесса вывода средств"""
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
                return
            
            from utils.constants import MIN_WITHDRAWAL_AMOUNT
            
            if user.referral_balance < MIN_WITHDRAWAL_AMOUNT:
                await callback.answer(
                    f"❌ Минимальная сумма для вывода: {MIN_WITHDRAWAL_AMOUNT}₽",
                    show_alert=True
                )
                return
            
            # Формируем текст
            from utils.referral_messages import get_withdrawal_start_text
            text = get_withdrawal_start_text(user.referral_balance, MIN_WITHDRAWAL_AMOUNT)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Банковская карта", callback_data="withdraw_card")],
                [InlineKeyboardButton(text="📱 СБП (по номеру телефона)", callback_data="withdraw_sbp")],
                [InlineKeyboardButton(text="« Отмена", callback_data="referral_program")]
            ])
            
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Ошибка в start_withdrawal: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.callback_query(F.data == "withdraw_card")
async def choose_card_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    """Выбор вывода на карту"""
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            await state.update_data(payment_method="card", user_balance=user.referral_balance)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="ref_withdraw")]
        ])
        
        await callback.message.delete()
        await callback.message.answer(
            "💳 <b>Вывод на банковскую карту</b>\n\n"
            "Введите номер карты (16 цифр):\n\n"
            "Например: <code>1234567812345678</code>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(WithdrawalStates.waiting_card_number)
        
    except Exception as e:
        logger.error(f"Ошибка в choose_card_withdrawal: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.message(WithdrawalStates.waiting_card_number)
async def process_card_number(message: types.Message, state: FSMContext):
    """Обработка ввода номера карты"""
    try:
        card_number = message.text.strip().replace(" ", "")
        
        # Валидация
        from utils.referral_helpers import validate_card_number, mask_card_number
        is_valid, error_msg = validate_card_number(card_number)
        
        if not is_valid:
            await message.answer(f"❌ {error_msg}\n\nПопробуйте еще раз:")
            return
        
        # Сохраняем и показываем подтверждение
        data = await state.get_data()
        balance = data['user_balance']
        masked = mask_card_number(card_number)
        
        await state.update_data(card_number=card_number, masked_details=masked)
        
        from utils.referral_messages import get_withdrawal_confirmation_text
        text = get_withdrawal_confirmation_text(balance, masked, "card")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_withdrawal")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_withdrawal")]
        ])
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(WithdrawalStates.waiting_confirmation)
        
    except Exception as e:
        logger.error(f"Ошибка в process_card_number: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте снова или /cancel")


@user_router.callback_query(F.data == "withdraw_sbp")
async def choose_sbp_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    """Выбор вывода через СБП"""
    try:
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            await state.update_data(payment_method="sbp", user_balance=user.referral_balance)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data="ref_withdraw")]
        ])
        
        await callback.message.delete()
        await callback.message.answer(
            "📱 <b>Вывод через СБП</b>\n\n"
            "Введите номер телефона (11 цифр):\n\n"
            "Например: <code>79001234567</code>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(WithdrawalStates.waiting_phone_number)
        
    except Exception as e:
        logger.error(f"Ошибка в choose_sbp_withdrawal: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.message(WithdrawalStates.waiting_phone_number)
async def process_phone_number(message: types.Message, state: FSMContext):
    """Обработка ввода номера телефона для СБП"""
    try:
        phone = message.text.strip().replace("+", "").replace(" ", "").replace("-", "")
        
        # Валидация
        from utils.referral_helpers import validate_phone_number, mask_phone_number
        is_valid, error_msg = validate_phone_number(phone)
        
        if not is_valid:
            await message.answer(f"❌ {error_msg}\n\nПопробуйте еще раз:")
            return
        
        # Сохраняем и показываем подтверждение
        data = await state.get_data()
        balance = data['user_balance']
        phone_formatted = f"+{phone}"
        masked = mask_phone_number(phone_formatted)
        
        await state.update_data(phone_number=phone_formatted, masked_details=masked)
        
        from utils.referral_messages import get_withdrawal_confirmation_text
        text = get_withdrawal_confirmation_text(balance, masked, "sbp")
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_withdrawal")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_withdrawal")]
        ])
        
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(WithdrawalStates.waiting_confirmation)
        
    except Exception as e:
        logger.error(f"Ошибка в process_phone_number: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте снова или /cancel")


@user_router.callback_query(F.data == "confirm_withdrawal")
async def confirm_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    """Подтверждение вывода средств"""
    try:
        data = await state.get_data()
        payment_method = data.get('payment_method')
        payment_details = data.get('card_number') or data.get('phone_number')
        
        async with AsyncSessionLocal() as session:
            user = await get_user_by_telegram_id(session, callback.from_user.id)
            
            # Создаем заявку
            from database.crud import create_withdrawal_request
            success = await create_withdrawal_request(
                session,
                user.id,
                user.referral_balance,
                payment_method,
                payment_details
            )
            
            if success:
                from utils.referral_messages import get_withdrawal_request_created_text
                text = get_withdrawal_request_created_text(
                    user.referral_balance,
                    data.get('masked_details', payment_details)
                )
                
                # Добавляем кнопку назад
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="« Назад в реферальную программу", callback_data="referral_program")]
                ])
                
                await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
                
                # Уведомляем админов
                await notify_admins_about_withdrawal(callback.bot, user, payment_method, payment_details)
            else:
                await callback.answer("❌ Ошибка при создании заявки", show_alert=True)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка в confirm_withdrawal: {e}", exc_info=True)
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@user_router.callback_query(F.data == "cancel_withdrawal")
async def cancel_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    """Отмена вывода"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Вывод отменен.\n\nВы можете вернуться в реферальную программу.",
        parse_mode="HTML"
    )


async def notify_admins_about_withdrawal(bot, user, payment_method, payment_details):
    """Уведомляет админов о новой заявке на вывод"""
    try:
        from utils.referral_messages import get_admin_withdrawal_notification_text
        from utils.constants import ADMIN_IDS
        
        user_name = user.first_name or "Без имени"
        if user.username:
            user_name = f"@{user.username}"
        
        text = get_admin_withdrawal_notification_text(
            user_name,
            user.telegram_id,
            user.referral_balance,
            payment_details,
            payment_method
        )
        
        # Добавляем кнопку для перехода к заявкам
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Перейти к заявкам", callback_data="admin_withdrawals")]
        ])
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, reply_markup=keyboard, parse_mode="HTML")
                logger.info(f"Отправлено уведомление о выводе админу {admin_id}")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка в notify_admins_about_withdrawal: {e}", exc_info=True)
