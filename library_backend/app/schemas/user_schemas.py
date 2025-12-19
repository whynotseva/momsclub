"""
Схемы для API пользователей (админка)
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date


# ==================== БАЗОВЫЕ СХЕМЫ ====================

class UserShort(BaseModel):
    """Краткая информация о пользователе (для списков)"""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    
    class Config:
        from_attributes = True


class SubscriptionInfo(BaseModel):
    """Информация о подписке"""
    id: int
    start_date: datetime
    end_date: datetime
    is_active: bool
    price: int
    days_left: int
    is_expired: bool
    
    class Config:
        from_attributes = True


class LoyaltyInfo(BaseModel):
    """Информация о лояльности"""
    level: str  # 'none', 'silver', 'gold', 'platinum'
    first_payment_date: Optional[datetime] = None
    days_in_club: int = 0
    one_time_discount_percent: int = 0
    lifetime_discount_percent: int = 0
    pending_loyalty_reward: bool = False
    gift_due: bool = False


class ReferralInfo(BaseModel):
    """Информация о рефералах"""
    referral_code: Optional[str] = None
    referral_balance: int = 0
    total_referrals_paid: int = 0
    total_earned_referral: int = 0
    referrer: Optional[UserShort] = None
    referrals_count: int = 0


class BadgeInfo(BaseModel):
    """Информация о достижении"""
    badge_type: str
    earned_at: datetime
    
    class Config:
        from_attributes = True


class GroupActivityInfo(BaseModel):
    """Информация об активности в группе"""
    message_count: int = 0
    last_activity: Optional[datetime] = None


class PaymentInfo(BaseModel):
    """Информация о платеже"""
    id: int
    amount: int
    status: str
    days: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== ПОЛНАЯ КАРТОЧКА ПОЛЬЗОВАТЕЛЯ ====================

class UserCard(BaseModel):
    """Полная карточка пользователя для админки"""
    # Основная информация
    id: int
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    birthday: Optional[date] = None
    is_active: bool = True
    is_blocked: bool = False
    created_at: datetime
    
    # Подписка
    subscription: Optional[SubscriptionInfo] = None
    has_active_subscription: bool = False
    is_recurring_active: bool = False
    autopay_streak: int = 0
    
    # Лояльность
    loyalty: LoyaltyInfo
    
    # Рефералы
    referral: ReferralInfo
    
    # Достижения
    badges: List[BadgeInfo] = []
    
    # Активность в группе
    group_activity: Optional[GroupActivityInfo] = None
    
    # История платежей (последние 5)
    recent_payments: List[PaymentInfo] = []
    total_payments_count: int = 0
    total_paid_amount: int = 0
    
    # Админ-информация
    admin_group: Optional[str] = None
    is_first_payment_done: bool = False
    
    class Config:
        from_attributes = True


# ==================== ПОИСК ====================

class UserSearchResult(BaseModel):
    """Результат поиска пользователя"""
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    has_active_subscription: bool = False
    loyalty_level: str = "none"
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserSearchResponse(BaseModel):
    """Ответ на поиск пользователей"""
    users: List[UserSearchResult]
    total: int
    query: str
