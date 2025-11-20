import logging
import os
import aiohttp
import base64
from datetime import datetime
from aiogram.types import URLInputFile, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from utils.constants import (
    TEMPORARY_PAYMENT_MODE, TEMPORARY_PAYMENT_ADMIN, TEMPORARY_PAYMENT_URL,
    SUBSCRIPTION_PRICE, SUBSCRIPTION_PRICE_2MONTHS, SUBSCRIPTION_PRICE_3MONTHS,
    SUBSCRIPTION_DAYS, SUBSCRIPTION_DAYS_2MONTHS, SUBSCRIPTION_DAYS_3MONTHS,
    LIFETIME_THRESHOLD, LIFETIME_SUBSCRIPTION_GROUP
)

# Настраиваем логгер
logger = logging.getLogger(__name__)


def log_message(user_id, message_text, message_type="text"):
    """
    Логирует полученное сообщение
    
    Args:
        user_id: ID пользователя Telegram
        message_text: Текст сообщения
        message_type: Тип сообщения
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{current_time}] Получено сообщение от пользователя {user_id}: {message_text} (тип: {message_type})")


def format_message(text, user_name=None):
    """
    Форматирует сообщение для отправки пользователю
    
    Args:
        text: Текст сообщения
        user_name: Имя пользователя (опционально)
        
    Returns:
        str: Отформатированное сообщение
    """
    if user_name:
        return f"{user_name}, {text}"
    return text


async def save_image_from_url(url, file_path):
    """
    Сохраняет изображение из URL в указанный путь
    
    Args:
        url: URL изображения
        file_path: Путь для сохранения файла
        
    Returns:
        bool: True если сохранение успешно, иначе False
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    # Создаем директорию, если она не существует
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    
                    # Сохраняем файл
                    with open(file_path, 'wb') as f:
                        f.write(await response.read())
                    return True
                else:
                    logger.error(f"Ошибка загрузки изображения. Статус: {response.status}")
                    return False
    except Exception as e:
        logger.error(f"Ошибка при сохранении изображения: {e}")
        return False


def save_base64_image(base64_str, file_path):
    """
    Сохраняет изображение из base64 строки в указанный путь
    
    Args:
        base64_str: Строка base64 с изображением (без префикса data:image/jpeg;base64,)
        file_path: Путь для сохранения файла
        
    Returns:
        bool: True если сохранение успешно, иначе False
    """
    try:
        # Удаляем префикс data:image если он есть
        if "base64," in base64_str:
            base64_str = base64_str.split("base64,")[1]
        
        # Создаем директорию, если она не существует
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Декодируем base64 и сохраняем как файл
        image_data = base64.b64decode(base64_str)
        with open(file_path, 'wb') as f:
            f.write(image_data)
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении изображения из base64: {e}")
        return False

# --- Вспомогательная функция для экранирования MarkdownV2 ---
def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # Убедимся, что text это строка
    if not isinstance(text, str):
        text = str(text) # Преобразуем в строку, если это не так
    # Используем ДВОЙНОЙ обратный слэш ПЕРЕД переменной в f-строке
    return ''.join(f'\\{char}' if char in escape_chars else char for char in text)
# --- Конец вспомогательной функции --- 

def get_payment_method_markup(callback_prefix=""):
    """
    Возвращает разметку кнопок в зависимости от режима оплаты
    """
    # Логируем для отладки
    logger.info(f"get_payment_method_markup вызван с prefix='{callback_prefix}'")
    
    if TEMPORARY_PAYMENT_MODE:
        logger.info(f"Создается кнопка назад с текстом '« Назад'")
        
        # Временный режим оплаты - используем текст кнопки как callback_data для отладки
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💌 Написать Полине", url=TEMPORARY_PAYMENT_URL)],
                [InlineKeyboardButton(text="« Назад", callback_data="back_to_profile")]
            ]
        )
    else:
        # Стандартный режим оплаты
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"💝 1 месяц - {SUBSCRIPTION_PRICE} ₽", callback_data=f"{callback_prefix}payment_1month")],
                [InlineKeyboardButton(text=f"💞 2 месяца - {SUBSCRIPTION_PRICE_2MONTHS} ₽", callback_data=f"{callback_prefix}payment_2months")],
                [InlineKeyboardButton(text=f"💓 3 месяца - {SUBSCRIPTION_PRICE_3MONTHS} ₽", callback_data=f"{callback_prefix}payment_3months")],
                [InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data=f"{callback_prefix}enter_promo_code")],
                [InlineKeyboardButton(text="« Назад", callback_data=f"{callback_prefix}back_to_profile")]
            ]
        )

def get_payment_notice():
    """
    Возвращает текст уведомления в зависимости от режима оплаты
    """
    if TEMPORARY_PAYMENT_MODE:
        return (
            "🌸 <b>Важное обновление, красотка!</b> 🌸\n\n"
            "У нас временные технические изменения в системе оплаты, но это совсем не помешает тебе присоединиться к нашему комьюнити!\n\n"
            "<b>Как оформить подписку:</b>\n\n"
            f"1. Напиши мне напрямую: @{TEMPORARY_PAYMENT_ADMIN} 💌\n"
            f"2. Выбери удобный тариф:\n"
            f"   • 💝 1 месяц - {SUBSCRIPTION_PRICE} ₽\n"
            f"   • 💞 2 месяца - {SUBSCRIPTION_PRICE_2MONTHS} ₽\n"
            f"   • 💓 3 месяца - {SUBSCRIPTION_PRICE_3MONTHS} ₽\n"
            f"3. Я вышлю тебе реквизиты и активирую твою подписку сразу после оплаты 🤍\n\n"
            f"<i>Я всегда онлайн и отвечу на любые вопросы!</i>"
        )
    else:
        return "Выбери свой тариф подписки Mom's Club:" 


async def safe_edit_message(callback, text, reply_markup=None, parse_mode=None):
    """
    Безопасно редактирует сообщение, проверяя наличие текста

    Args:
        callback: CallbackQuery объект
        text: Новый текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (опционально)

    Returns:
        True если редактирование удалось, False если отправлено новое сообщение
    """
    try:
        # Проверяем, есть ли текст в сообщении
        if callback.message.text or callback.message.caption:
            # Если есть текст или подпись, редактируем
            if callback.message.text:
                # Есть текст - редактируем текст
                await callback.message.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            else:
                # Есть только подпись - редактируем подпись
                await callback.message.edit_caption(
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            return True
        else:
            # Если нет текста и подписи, отправляем новое сообщение
            await callback.message.answer(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return False
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        # В случае ошибки пробуем отправить новое сообщение
        try:
            await callback.message.answer(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return False
        except Exception as e2:
            logger.error(f"Ошибка при отправке нового сообщения: {e2}")
            # Если ничего не получилось, показываем alert
            await callback.answer("Произошла ошибка при обновлении сообщения", show_alert=True)
            return False


# ===== Хелперы форматирования и стандартных клавиатур для админки =====
def format_user_error_message(error: Exception, context: str = "") -> str:
    """
    Форматирует сообщение об ошибке для пользователя в стиле сообщества.
    
    Args:
        error: Объект исключения
        context: Контекст ошибки (например, "при создании платежа", "при проверке подписки")
        
    Returns:
        str: Понятное сообщение об ошибке для пользователя
    """
    error_str = str(error).lower()
    
    # Определяем тип ошибки и возвращаем понятное сообщение
    if "payment" in error_str or "платеж" in error_str or "payment" in context.lower():
        if "timeout" in error_str or "connection" in error_str:
            return (
                "💔 Красотка, произошла ошибка при создании платежа.\n\n"
                "Похоже, возникли проблемы с подключением к платежной системе. "
                "Попробуй еще раз через минуту — обычно это помогает! 💖\n\n"
                "Если проблема повторится, напиши мне — я обязательно помогу! 🩷"
            )
        else:
            return (
                "💔 Красотка, не удалось создать платеж.\n\n"
                "Попробуй еще раз через минуту. Если проблема повторится, "
                "напиши мне — я обязательно помогу разобраться! 💖"
            )
    
    elif "subscription" in error_str or "подписк" in error_str or "subscription" in context.lower():
        return (
            "💔 Красотка, произошла ошибка при работе с подпиской.\n\n"
            "Попробуй еще раз через минуту. Если проблема повторится, "
            "напиши мне — я обязательно помогу! 💖"
        )
    
    elif "database" in error_str or "база данных" in error_str or "connection" in error_str:
        return (
            "💔 Красотка, произошла временная ошибка.\n\n"
            "Попробуй еще раз через минуту — обычно это помогает! 💖\n\n"
            "Если проблема повторится, напиши мне — я обязательно помогу! 🩷"
        )
    
    elif "timeout" in error_str or "timed out" in error_str:
        return (
            "💔 Красотка, операция заняла слишком много времени.\n\n"
            "Попробуй еще раз — обычно это помогает! 💖"
        )
    
    elif "network" in error_str or "connection" in error_str or "unreachable" in error_str:
        return (
            "💔 Красотка, возникли проблемы с подключением.\n\n"
            "Проверь интернет-соединение и попробуй еще раз через минуту. "
            "Если проблема повторится, напиши мне! 💖"
        )
    
    else:
        # Общее сообщение для неизвестных ошибок
        return (
            "💔 Красотка, произошла неожиданная ошибка.\n\n"
            "Попробуй еще раз через минуту. Если проблема повторится, "
            "напиши мне — я обязательно помогу разобраться! 💖"
        )


def fmt_date(dt):
    """Возвращает дату в формате dd.mm.yyyy либо 'N/A'."""
    try:
        return dt.strftime('%d.%m.%Y') if dt else 'N/A'
    except Exception:
        return 'N/A'


def html_kv(label: str, value: str) -> str:
    """Пара 'ключ: значение' в HTML-стиле."""
    return f"<b>{label}:</b> {value}"


def success(text: str) -> str:
    return f"✅ {text}"


def error(text: str) -> str:
    return f"❌ {text}"


def admin_nav_back(callback_data: str = "admin_back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Назад", callback_data=callback_data)]])


def admin_nav_cancel(callback_data: str = "admin_cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Отмена", callback_data=callback_data)]])


def is_lifetime_subscription(subscription) -> bool:
    """Проверяет, является ли подписка бесконечной (пожизненной)"""
    if not subscription:
        return False
    # Бесконечная подписка имеет end_date после LIFETIME_THRESHOLD
    return subscription.end_date >= LIFETIME_THRESHOLD


def format_subscription_end_date(subscription, escape_for_markdown: bool = False) -> str:
    """
    Форматирует дату окончания подписки для отображения.
    Для пожизненных подписок возвращает "∞ Пожизненная".
    
    Args:
        subscription: Объект подписки
        escape_for_markdown: Если True, экранирует для MarkdownV2
        
    Returns:
        str: Отформатированная дата или "∞ Пожизненная"
    """
    if not subscription:
        return "Нет подписки"
    
    if is_lifetime_subscription(subscription):
        return f"{LIFETIME_SUBSCRIPTION_GROUP} Пожизненная"
    
    date_str = subscription.end_date.strftime("%d.%m.%Y")
    if escape_for_markdown:
        return escape_markdown_v2(date_str)
    return date_str


def format_subscription_days_left(subscription, escape_for_markdown: bool = False) -> str:
    """
    Форматирует количество оставшихся дней подписки.
    Для пожизненных подписок возвращает "∞".
    
    Args:
        subscription: Объект подписки
        escape_for_markdown: Если True, экранирует для MarkdownV2
        
    Returns:
        str: Количество дней или "∞"
    """
    if not subscription:
        return "0 дней"
    
    if is_lifetime_subscription(subscription):
        return LIFETIME_SUBSCRIPTION_GROUP
    
    days_left = (subscription.end_date - datetime.now()).days
    if days_left == 1:
        days_text = "1 день"
    elif days_left == 0:
        days_text = "последний день"
    elif days_left < 0:
        days_text = "истекла"
    else:
        days_text = f"{days_left} дней"
    
    if escape_for_markdown:
        return escape_markdown_v2(days_text)
    return days_text