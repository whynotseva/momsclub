"""
Модуль для валидации входных данных от пользователей.

Защищает от:
- Некорректных форматов данных
- XSS атак через инъекцию HTML/JS
- SQL injection (дополнительная защита к ORM)
- Слишком длинных строк
- Некорректных email, телефонов, дат
"""

import re
import logging
from typing import Optional, Tuple
from datetime import datetime
from pydantic import BaseModel, validator, Field

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Исключение для ошибок валидации"""
    pass


class ReferralCodeValidator(BaseModel):
    """Валидатор реферального кода"""
    code: str = Field(..., min_length=6, max_length=12)
    
    @validator('code')
    def validate_code(cls, v):
        """Проверяет формат реферального кода"""
        # Только буквы и цифры
        if not re.match(r'^[A-Z0-9]{6,12}$', v.upper()):
            raise ValueError('Реферальный код должен содержать только буквы и цифры (6-12 символов)')
        return v.upper()
    
    class Config:
        str_strip_whitespace = True


class PhoneValidator(BaseModel):
    """Валидатор номера телефона"""
    phone: str = Field(..., min_length=10, max_length=20)
    
    @validator('phone')
    def validate_phone(cls, v):
        """Проверяет формат телефона"""
        # Удаляем все кроме цифр и +
        cleaned = re.sub(r'[^\d+]', '', v)
        
        # Проверяем формат: +7XXXXXXXXXX или 8XXXXXXXXXX или 7XXXXXXXXXX
        if not re.match(r'^(\+?7|8)\d{10}$', cleaned):
            raise ValueError('Некорректный формат телефона. Используйте формат: +79991234567')
        
        # Нормализуем к формату +7XXXXXXXXXX
        if cleaned.startswith('8'):
            cleaned = '+7' + cleaned[1:]
        elif cleaned.startswith('7'):
            cleaned = '+' + cleaned
        elif not cleaned.startswith('+'):
            cleaned = '+' + cleaned
            
        return cleaned
    
    class Config:
        str_strip_whitespace = True


class EmailValidator(BaseModel):
    """Валидатор email адреса"""
    email: str = Field(..., max_length=100)
    
    @validator('email')
    def validate_email(cls, v):
        """Проверка email"""
        # Базовая проверка формата email
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, v):
            raise ValueError('Некорректный формат email')
        
        # Проверяем на подозрительные символы
        if any(char in v for char in ['<', '>', '"', "'"]):
            raise ValueError('Email содержит недопустимые символы')
        
        # Проверяем длину доменной части
        domain = v.split('@')[1] if '@' in v else ''
        if len(domain) < 3:
            raise ValueError('Некорректный домен email')
            
        return v.lower()
    
    class Config:
        str_strip_whitespace = True


class BirthdayValidator(BaseModel):
    """Валидатор даты рождения"""
    birthday: str = Field(..., min_length=8, max_length=10)
    
    @validator('birthday')
    def validate_birthday(cls, v):
        """Проверяет формат даты рождения"""
        # Поддерживаемые форматы: DD.MM.YYYY, DD-MM-YYYY, DD/MM/YYYY
        formats = ['%d.%m.%Y', '%d-%m-%Y', '%d/%m/%Y']
        
        parsed_date = None
        for fmt in formats:
            try:
                parsed_date = datetime.strptime(v, fmt)
                break
            except ValueError:
                continue
        
        if not parsed_date:
            raise ValueError('Некорректный формат даты. Используйте: ДД.ММ.ГГГГ (например, 15.03.1990)')
        
        # Проверяем разумность даты
        now = datetime.now()
        age = (now - parsed_date).days / 365.25
        
        if age < 16:
            raise ValueError('Возраст должен быть не менее 16 лет')
        if age > 100:
            raise ValueError('Проверьте правильность даты рождения')
        
        # Возвращаем в стандартном формате
        return parsed_date.strftime('%d.%m.%Y')
    
    class Config:
        str_strip_whitespace = True


class PromoCodeValidator(BaseModel):
    """Валидатор промокода"""
    code: str = Field(..., min_length=3, max_length=20)
    
    @validator('code')
    def validate_code(cls, v):
        """Проверяет формат промокода"""
        # Только буквы, цифры и дефис
        if not re.match(r'^[A-Za-z0-9\-]{3,20}$', v):
            raise ValueError('Промокод может содержать только буквы, цифры и дефис')
        
        # Проверяем на подозрительные паттерны (SQL injection попытки)
        suspicious = ['--', ';', 'DROP', 'SELECT', 'INSERT', 'UPDATE', 'DELETE', '<script']
        if any(pattern.lower() in v.lower() for pattern in suspicious):
            raise ValueError('Промокод содержит недопустимые символы')
            
        return v.upper()
    
    class Config:
        str_strip_whitespace = True


class TextInputValidator(BaseModel):
    """Валидатор текстового ввода (для сообщений, комментариев)"""
    text: str = Field(..., min_length=1, max_length=4000)
    
    @validator('text')
    def validate_text(cls, v):
        """Проверяет текстовый ввод на безопасность"""
        # Проверяем на XSS
        xss_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',  # onclick, onload и т.д.
            r'<iframe',
            r'<object',
            r'<embed',
        ]
        
        for pattern in xss_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError('Текст содержит недопустимые элементы')
        
        # Ограничиваем количество повторяющихся символов (защита от спама)
        if re.search(r'(.)\1{50,}', v):
            raise ValueError('Слишком много повторяющихся символов')
        
        return v.strip()
    
    class Config:
        str_strip_whitespace = True


class UsernameValidator(BaseModel):
    """Валидатор username Telegram"""
    username: str = Field(..., min_length=5, max_length=32)
    
    @validator('username')
    def validate_username(cls, v):
        """Проверяет формат username"""
        # Удаляем @ если есть
        v = v.lstrip('@')
        
        # Username может содержать только буквы, цифры и подчеркивания
        if not re.match(r'^[a-zA-Z0-9_]{5,32}$', v):
            raise ValueError('Username может содержать только буквы, цифры и подчеркивания (5-32 символа)')
        
        return v
    
    class Config:
        str_strip_whitespace = True


# Вспомогательные функции для быстрой валидации

def validate_referral_code(code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация реферального кода.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = ReferralCodeValidator(code=code)
        return True, validator.code, None
    except Exception as e:
        return False, None, str(e)


def validate_phone(phone: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация телефона.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = PhoneValidator(phone=phone)
        return True, validator.phone, None
    except Exception as e:
        return False, None, str(e)


def validate_email(email: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация email.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = EmailValidator(email=email)
        return True, validator.email, None
    except Exception as e:
        return False, None, str(e)


def validate_birthday(birthday: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация даты рождения.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = BirthdayValidator(birthday=birthday)
        return True, validator.birthday, None
    except Exception as e:
        return False, None, str(e)


def validate_promo_code(code: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация промокода.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = PromoCodeValidator(code=code)
        return True, validator.code, None
    except Exception as e:
        return False, None, str(e)


def validate_text_input(text: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация текстового ввода.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = TextInputValidator(text=text)
        return True, validator.text, None
    except Exception as e:
        return False, None, str(e)


def validate_username(username: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Быстрая валидация username.
    
    Returns:
        (is_valid, cleaned_value, error_message)
    """
    try:
        validator = UsernameValidator(username=username)
        return True, validator.username, None
    except Exception as e:
        return False, None, str(e)


def sanitize_html(text: str) -> str:
    """
    Удаляет потенциально опасные HTML теги из текста.
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст
    """
    # Удаляем все HTML теги кроме безопасных
    safe_tags = ['b', 'i', 'u', 'code', 'pre', 'a']
    
    # Простая очистка - удаляем все теги
    cleaned = re.sub(r'<(?!/?(' + '|'.join(safe_tags) + r')\b)[^>]+>', '', text)
    
    return cleaned


def truncate_string(text: str, max_length: int = 1000) -> str:
    """
    Обрезает строку до максимальной длины.
    
    Args:
        text: Исходный текст
        max_length: Максимальная длина
        
    Returns:
        Обрезанный текст
    """
    if len(text) <= max_length:
        return text
    return text[:max_length] + '...'


# Логирование попыток валидации
def log_validation_attempt(field_name: str, is_valid: bool, error: Optional[str] = None):
    """Логирует попытки валидации для мониторинга"""
    if not is_valid:
        logger.warning(f"Валидация не пройдена: {field_name} - {error}")
    else:
        logger.debug(f"Валидация пройдена: {field_name}")
