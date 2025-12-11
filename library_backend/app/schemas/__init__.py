"""Pydantic схемы"""

from .auth import TelegramAuthData, TokenResponse, UserInfo, SubscriptionStatus, LoyaltyInfo, ReferralInfo, PaymentItem, PaymentHistory, UserSettings, CreatePaymentRequest, CreatePaymentResponse
from .library import (
    Category, CategoryCreate, CategoryUpdate,
    Tag, TagCreate,
    Material, MaterialListItem, MaterialCreate, MaterialUpdate,
    Attachment, AttachmentCreate,
    Favorite, FavoriteCreate,
    View, ViewCreate,
    MaterialFilters, PaginatedResponse
)

__all__ = [
    # Auth
    'TelegramAuthData',
    'TokenResponse',
    'UserInfo',
    'SubscriptionStatus',
    'LoyaltyInfo',
    'ReferralInfo',
    'PaymentItem',
    'PaymentHistory',
    'UserSettings',
    'CreatePaymentRequest',
    'CreatePaymentResponse',
    
    # Library
    'Category',
    'CategoryCreate',
    'CategoryUpdate',
    'Tag',
    'TagCreate',
    'Material',
    'MaterialListItem',
    'MaterialCreate',
    'MaterialUpdate',
    'Attachment',
    'AttachmentCreate',
    'Favorite',
    'FavoriteCreate',
    'View',
    'ViewCreate',
    'MaterialFilters',
    'PaginatedResponse',
]
