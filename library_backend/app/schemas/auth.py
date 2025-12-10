"""
Pydantic схемы для авторизации
"""

from typing import Optional
from pydantic import BaseModel, Field


class TelegramAuthData(BaseModel):
    """Данные от Telegram Login Widget"""
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class UserInfo(BaseModel):
    """Информация о пользователе"""
    telegram_id: int
    first_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    loyalty_level: str = "none"
    admin_group: Optional[str] = None  # creator, developer, curator
    has_active_subscription: bool
    subscription_end: Optional[str] = None
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Ответ с токеном"""
    access_token: str
    token_type: str = "bearer"
    user: UserInfo


class SubscriptionStatus(BaseModel):
    """Статус подписки"""
    has_active_subscription: bool
    subscription_end: Optional[str] = None
    days_left: Optional[int] = None


class LoyaltyInfo(BaseModel):
    """Информация о лояльности пользователя"""
    current_level: str = "none"  # none, silver, gold, platinum
    days_in_club: int = 0
    next_level: Optional[str] = None
    days_to_next_level: Optional[int] = None
    progress_percent: int = 0
    discount_percent: int = 0
    # Пороги уровней (для отображения)
    silver_days: int = 90
    gold_days: int = 180
    platinum_days: int = 365
