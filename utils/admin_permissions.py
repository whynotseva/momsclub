"""
Утилиты для проверки прав доступа администраторов
"""
from typing import Optional
from database.models import User
from utils.constants import (
    ADMIN_GROUP_CREATOR,
    ADMIN_GROUP_DEVELOPER,
    ADMIN_GROUP_CURATOR,
    ADMIN_GROUP_EMOJIS,
    ADMIN_GROUP_NAMES,
    ADMIN_IDS,
)


def is_admin(user: Optional[User]) -> bool:
    """
    Проверяет, является ли пользователь администратором
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        True если пользователь админ, иначе False
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not user:
        logger.info(f"[admin_permissions] is_admin: user is None")
        return False
    
    # Проверяем по группе админа
    if user.admin_group in [ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR]:
        logger.info(f"[admin_permissions] is_admin: user {user.telegram_id} имеет группу '{user.admin_group}' - доступ разрешен")
        return True
    
    # Обратная совместимость: проверяем по списку ADMIN_IDS
    if user.telegram_id in ADMIN_IDS:
        logger.info(f"[admin_permissions] is_admin: user {user.telegram_id} в списке ADMIN_IDS - доступ разрешен")
        return True
    
    logger.info(f"[admin_permissions] is_admin: user {user.telegram_id} не является админом (admin_group='{user.admin_group}', в ADMIN_IDS={user.telegram_id in ADMIN_IDS})")
    return False


def is_creator_or_developer(user: Optional[User]) -> bool:
    """
    Проверяет, является ли пользователь создательницей или разработчиком
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        True если пользователь создательница или разработчик, иначе False
    """
    if not user:
        return False
    
    return user.admin_group in [ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER]


def can_manage_admins(user: Optional[User]) -> bool:
    """
    Проверяет, может ли пользователь управлять группами админов
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        True если пользователь может управлять админами, иначе False
    """
    return is_creator_or_developer(user)


def can_view_revenue(user: Optional[User]) -> bool:
    """
    Проверяет, может ли пользователь видеть статистику выручки
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        True если пользователь может видеть выручку, иначе False
    """
    if not user:
        return False
    
    # Кураторы не могут видеть выручку
    if user.admin_group == ADMIN_GROUP_CURATOR:
        return False
    
    # Создательница и разработчик могут
    if user.admin_group in [ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER]:
        return True
    
    # Обратная совместимость для старых админов
    if user.telegram_id in ADMIN_IDS:
        return True
    
    return False


def can_receive_payment_notifications(user: Optional[User]) -> bool:
    """
    Проверяет, должен ли пользователь получать уведомления об оплате
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        True если пользователь должен получать уведомления, иначе False
    """
    if not user:
        return False
    
    # Кураторы не получают уведомления об оплате
    if user.admin_group == ADMIN_GROUP_CURATOR:
        return False
    
    # Создательница и разработчик получают
    if user.admin_group in [ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER]:
        return True
    
    # Обратная совместимость для старых админов
    if user.telegram_id in ADMIN_IDS:
        return True
    
    return False


def get_admin_group_display(user: Optional[User]) -> Optional[str]:
    """
    Возвращает красивое отображение группы админа для личного кабинета
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        Строка с эмодзи и названием группы или None
    """
    if not user or not user.admin_group:
        return None
    
    emoji = ADMIN_GROUP_EMOJIS.get(user.admin_group, "")
    name = ADMIN_GROUP_NAMES.get(user.admin_group, "")
    
    if emoji and name:
        return f"{emoji} {name}"
    
    return None


def get_admin_group_emoji(user: Optional[User]) -> str:
    """
    Возвращает эмодзи группы админа
    
    Args:
        user: Объект пользователя или None
        
    Returns:
        Эмодзи группы или пустая строка
    """
    if not user or not user.admin_group:
        return ""
    
    return ADMIN_GROUP_EMOJIS.get(user.admin_group, "")

