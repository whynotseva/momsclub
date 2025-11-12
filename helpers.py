import logging
import os
import aiohttp
import base64
from datetime import datetime
from aiogram.types import URLInputFile, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from utils.constants import (
    TEMPORARY_PAYMENT_MODE, TEMPORARY_PAYMENT_ADMIN, TEMPORARY_PAYMENT_URL,
    SUBSCRIPTION_PRICE, SUBSCRIPTION_PRICE_2MONTHS, SUBSCRIPTION_PRICE_3MONTHS,
    SUBSCRIPTION_DAYS, SUBSCRIPTION_DAYS_2MONTHS, SUBSCRIPTION_DAYS_3MONTHS
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

def mask_sensitive_data(data: str, keep_start: int = 4, keep_end: int = 4) -> str:
    """
    Маскирует чувствительные данные (токены, ключи, пароли) в логах.
    
    Args:
        data: Исходная строка для маскирования
        keep_start: Количество символов в начале, которые оставляем видимыми
        keep_end: Количество символов в конце, которые оставляем видимыми
        
    Returns:
        Маскированная строка вида "xxxx...xxxx"
    """
    if not data or len(data) <= keep_start + keep_end:
        return "***"  # Если строка слишком короткая, полностью маскируем
    
    masked_middle = "*" * max(8, len(data) - keep_start - keep_end)
    return f"{data[:keep_start]}{masked_middle}{data[-keep_end:]}" 

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