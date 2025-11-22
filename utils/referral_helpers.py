"""
Вспомогательные функции для реферальной системы 2.0
Содержит бизнес-логику, не связанную с БД напрямую
"""

from typing import Tuple


def calculate_referral_bonus(payment_amount: int, loyalty_level: str) -> int:
    """
    Рассчитывает размер денежного бонуса по уровню лояльности
    
    Args:
        payment_amount: Сумма платежа в рублях
        loyalty_level: Уровень лояльности ('none', 'silver', 'gold', 'platinum')
        
    Returns:
        Размер бонуса в рублях
    """
    from utils.constants import REFERRAL_MONEY_PERCENT
    
    bonus_percent = REFERRAL_MONEY_PERCENT.get(loyalty_level, 10)
    return int(payment_amount * bonus_percent / 100)


def format_balance_text(balance: int) -> str:
    """
    Форматирует баланс для отображения с разделителями
    
    Args:
        balance: Баланс в рублях
        
    Returns:
        Отформатированная строка (например, "1,240₽")
    """
    return f"{balance:,}₽"


def mask_card_number(card_number: str) -> str:
    """
    Маскирует номер банковской карты
    
    Args:
        card_number: Номер карты (16 цифр)
        
    Returns:
        Маскированный номер (например, "1234 **** **** 5678")
    """
    cleaned = card_number.strip().replace(" ", "")
    return f"{cleaned[:4]} **** **** {cleaned[-4:]}"


def mask_phone_number(phone: str) -> str:
    """
    Маскирует номер телефона для СБП
    
    Args:
        phone: Номер телефона
        
    Returns:
        Маскированный номер (например, "+7 900 ***-**-67")
    """
    cleaned = phone.strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(cleaned) == 11:
        return f"+{cleaned[0]} {cleaned[1:4]} ***-**-{cleaned[-2:]}"
    return phone  # Если формат непонятен, возвращаем как есть


def validate_card_number(card_number: str) -> Tuple[bool, str]:
    """
    Валидирует номер банковской карты
    
    Args:
        card_number: Номер карты
        
    Returns:
        (is_valid, error_message): Кортеж с результатом валидации
    """
    cleaned = card_number.strip().replace(" ", "")
    
    if not cleaned:
        return False, "Номер карты не может быть пустым"
    
    if not cleaned.isdigit():
        return False, "Номер карты должен содержать только цифры"
    
    if len(cleaned) != 16:
        return False, "Номер карты должен содержать 16 цифр"
    
    return True, ""


def validate_phone_number(phone: str) -> Tuple[bool, str]:
    """
    Валидирует номер телефона для СБП
    
    Args:
        phone: Номер телефона
        
    Returns:
        (is_valid, error_message): Кортеж с результатом валидации
    """
    cleaned = phone.strip().replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    
    if not cleaned:
        return False, "Номер телефона не может быть пустым"
    
    if not cleaned.isdigit():
        return False, "Номер телефона должен содержать только цифры"
    
    if len(cleaned) != 11:
        return False, "Номер телефона должен содержать 11 цифр (например, 79001234567)"
    
    if not cleaned.startswith("7"):
        return False, "Номер должен начинаться с 7 (например, 79001234567)"
    
    return True, ""


def get_loyalty_emoji(loyalty_level: str) -> str:
    """
    Возвращает эмодзи для уровня лояльности
    
    Args:
        loyalty_level: Уровень лояльности
        
    Returns:
        Эмодзи уровня
    """
    return {
        'none': '🤍',
        'silver': '🥈',
        'gold': '🥇',
        'platinum': '💎'
    }.get(loyalty_level, '🤍')


def get_loyalty_name(loyalty_level: str) -> str:
    """
    Возвращает название уровня лояльности
    
    Args:
        loyalty_level: Уровень лояльности
        
    Returns:
        Название уровня
    """
    return {
        'none': 'Участник',
        'silver': 'Silver',
        'gold': 'Gold',
        'platinum': 'Platinum'
    }.get(loyalty_level, 'Участник')


def get_bonus_percent_for_level(loyalty_level: str) -> int:
    """
    Возвращает процент бонуса для уровня лояльности
    
    Args:
        loyalty_level: Уровень лояльности
        
    Returns:
        Процент бонуса
    """
    from utils.constants import REFERRAL_MONEY_PERCENT
    return REFERRAL_MONEY_PERCENT.get(loyalty_level, 10)
