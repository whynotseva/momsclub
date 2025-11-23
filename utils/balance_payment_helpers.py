"""
Helper функции для оплаты подписки реферальным балансом
"""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def can_pay_with_balance(user_balance: int, price: int) -> bool:
    """
    Проверяет достаточность баланса для оплаты
    
    Args:
        user_balance: Текущий баланс пользователя в рублях
        price: Цена подписки в рублях
        
    Returns:
        bool: True если баланса достаточно, False если нет
    """
    return user_balance >= price


def get_balance_progress_bar(current: int, target: int, length: int = 10) -> str:
    """
    Генерирует прогресс-бар накопления баланса
    
    Args:
        current: Текущая сумма в рублях
        target: Целевая сумма в рублях
        length: Длина прогресс-бара (количество символов)
        
    Returns:
        str: Отформатированный прогресс-бар
        
    Examples:
        >>> get_balance_progress_bar(500, 1000)
        '█████░░░░░ 500/1,000₽ (50%)'
        
        >>> get_balance_progress_bar(900, 990)
        '█████████░ 900/990₽ (91%)'
        
        >>> get_balance_progress_bar(1000, 990)
        '██████████ 1,000/990₽ (100%)'
    """
    if target <= 0:
        return f"{'░' * length} 0/0₽ (0%)"
    
    # Вычисляем процент (макс 100%)
    percent = min(100, int((current / target) * 100))
    
    # Количество заполненных блоков
    filled = int(length * percent / 100)
    
    # Генерируем бар
    bar = "█" * filled + "░" * (length - filled)
    
    # Форматируем числа с разделителями тысяч
    return f"{bar} {current:,}/{target:,}₽ ({percent}%)"


def get_next_achievable_price(current_balance: int) -> int:
    """
    Определяет ближайший достижимый тариф для показа прогресса
    
    Args:
        current_balance: Текущий баланс
        
    Returns:
        int: Цена ближайшего тарифа (990₽, 1790₽ или 2490₽)
    """
    prices = get_subscription_prices()  # [990, 1790, 2490]
    
    # Находим ближайший тариф, который еще не достигнут
    for price in prices:
        if current_balance < price:
            return price
    
    # Если хватает на все - возвращаем максимальный
    return prices[-1]


def format_balance_payment_message(
    user_balance: int, 
    price: int, 
    days: int,
    discount_percent: int = 0
) -> Tuple[str, bool]:
    """
    Форматирует сообщение о выборе способа оплаты
    
    Args:
        user_balance: Баланс пользователя
        price: Цена подписки
        days: Количество дней подписки
        discount_percent: Процент скидки лояльности
        
    Returns:
        Tuple[str, bool]: (текст сообщения, хватает ли баланса)
    """
    has_enough = can_pay_with_balance(user_balance, price)
    
    # Формируем текст о цене
    if discount_percent > 0:
        original_price = int(price / (1 - discount_percent / 100))
        price_text = f"<s>{original_price:,}₽</s> {price:,}₽"
        discount_info = f"\n💰 <b>Ваша скидка лояльности: {discount_percent}%</b>"
    else:
        price_text = f"{price:,}₽"
        discount_info = ""
    
    text = f"💳 <b>Выберите способ оплаты</b>\n\n"
    text += f"📦 Подписка: {days} дней\n"
    text += f"💵 Стоимость: {price_text}{discount_info}\n\n"
    
    if has_enough:
        # Баланса хватает
        text += f"💰 <b>Ваш баланс: {user_balance:,}₽</b> ✅\n"
        text += f"После оплаты балансом останется: {user_balance - price:,}₽\n\n"
        text += "⚡ Оплата балансом произойдет мгновенно!"
    else:
        # Баланса не хватает - показываем прогресс до БЛИЖАЙШЕГО тарифа
        deficit = price - user_balance
        
        # Определяем ближайший достижимый тариф
        next_price = get_next_achievable_price(user_balance)
        progress = get_balance_progress_bar(user_balance, next_price)
        
        text += f"💰 <b>Ваш баланс: {user_balance:,}₽</b>\n"
        
        # Если ближайший тариф - это не выбранная подписка, показываем оба прогресса
        if next_price != price:
            text += f"\n<b>Прогресс до ближайшего тарифа ({next_price:,}₽):</b>\n"
            text += f"{progress}\n"
            text += f"Еще {next_price - user_balance:,}₽ до {next_price:,}₽!\n\n"
            text += f"<b>Выбранный тариф ({price:,}₽):</b>\n"
            text += f"❌ Не хватает: {deficit:,}₽\n\n"
        else:
            # Показываем только один прогресс
            text += f"{progress}\n"
            text += f"❌ Не хватает: {deficit:,}₽\n\n"
        
        text += "💡 Пригласи подруг чтобы накопить нужную сумму!"
    
    return text, has_enough


def get_subscription_prices() -> list:
    """
    Возвращает список всех цен подписок для проверки порогов накопления
    ВАЖНО: 690₽ НЕ включаем - это только для первой оплаты, балансом не оплачивается!
    
    Returns:
        list: Отсортированный список цен (990₽, 1790₽, 2490₽)
    """
    from utils.constants import (
        SUBSCRIPTION_PRICE,
        SUBSCRIPTION_PRICE_2MONTHS,
        SUBSCRIPTION_PRICE_3MONTHS
    )
    
    prices = [
        SUBSCRIPTION_PRICE,        # 990₽ - 1 месяц
        SUBSCRIPTION_PRICE_2MONTHS, # 1790₽ - 2 месяца
        SUBSCRIPTION_PRICE_3MONTHS  # 2490₽ - 3 месяца
    ]
    
    return sorted(set(prices))  # Убираем дубликаты и сортируем


def check_balance_milestone(old_balance: int, new_balance: int) -> int:
    """
    Проверяет достижение порога накопления для уведомления
    
    Args:
        old_balance: Старый баланс
        new_balance: Новый баланс после начисления
        
    Returns:
        int: Цена подписки, на которую накоплено (0 если порог не достигнут)
    """
    prices = get_subscription_prices()
    
    # Проверяем каждую цену
    for price in prices:
        # Если раньше не хватало, а теперь хватает
        if old_balance < price and new_balance >= price:
            return price
    
    return 0


async def send_balance_milestone_notification(bot, user_telegram_id: int, achieved_price: int):
    """
    Отправляет уведомление пользователю о накоплении нужной суммы
    
    Args:
        bot: Экземпляр бота
        user_telegram_id: Telegram ID пользователя
        achieved_price: Достигнутая сумма
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Определяем срок подписки по цене
    days_map = {
        990: 30,
        1790: 60,
        2490: 90
    }
    
    days = days_map.get(achieved_price, 30)
    
    text = (
        f"🎉 <b>УРА! ТЫ НАКОПИЛА {achieved_price:,}₽!</b>\n\n"
        f"Теперь можешь оплатить подписку балансом!\n"
        f"💰 Не нужно платить картой!\n"
        f"📅 Доступна подписка на {days} дней\n\n"
        f"⚡ Оплата балансом происходит мгновенно!\n"
        f"Жми кнопку ниже чтобы оформить подписку 👇"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Оплатить подписку", callback_data="subscribe")],
        [InlineKeyboardButton(text="📊 Мой баланс", callback_data="referral_program")]
    ])
    
    try:
        await bot.send_message(
            user_telegram_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        logger.info(f"Отправлено уведомление о накоплении {achieved_price}₽ пользователю {user_telegram_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о накоплении: {e}")
