"""
Сервисный слой приложения.
Содержит бизнес-логику, отделённую от API роутов.
"""

from .material_service import (
    MaterialService,
    add_cover_url,
    check_admin,
    log_admin_action,
    ADMIN_IDS,
    API_BASE_URL,
)

from .recommendation_service import RecommendationService
from .admin_service import AdminService, is_admin
from .notification_service import send_telegram_notification, NotificationTemplates
