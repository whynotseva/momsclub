"""
Сервис для отправки уведомлений в Telegram через API бота
"""

import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)


async def send_telegram_notification(
    telegram_id: int,
    message: str,
    notification_type: str = "general"
) -> bool:
    """
    Отправляет уведомление пользователю в Telegram через API бота.
    
    Args:
        telegram_id: Telegram ID пользователя
        message: Текст сообщения (поддерживает HTML)
        notification_type: Тип уведомления для логирования
        
    Returns:
        True если успешно, False если ошибка
    """
    if not settings.NOTIFICATION_API_KEY:
        logger.error("NOTIFICATION_API_KEY не настроен")
        return False
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.NOTIFICATION_API_URL,
                json={
                    "telegram_id": telegram_id,
                    "message": message,
                    "api_key": settings.NOTIFICATION_API_KEY,
                    "notification_type": notification_type
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.info(f"Уведомление отправлено: telegram_id={telegram_id}, type={notification_type}")
                    return True
                else:
                    logger.error(f"Ошибка от API бота: {result.get('error')}")
                    return False
            else:
                logger.error(f"HTTP ошибка {response.status_code}: {response.text}")
                return False
                
    except httpx.TimeoutException:
        logger.error(f"Таймаут при отправке уведомления telegram_id={telegram_id}")
        return False
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")
        return False


# Шаблоны сообщений для разных типов уведомлений
class NotificationTemplates:
    """Шаблоны сообщений для уведомлений"""
    
    @staticmethod
    def subscription_extended(days: int) -> str:
        return f"✅ Ваша подписка продлена на <b>{days}</b> дней!"
    
    @staticmethod
    def subscription_granted(days: int) -> str:
        return f"🎉 Вам выдана подписка на <b>{days}</b> дней!"
    
    @staticmethod
    def bonus_granted(bonus_type: str, amount: int) -> str:
        if bonus_type == "days":
            return f"🎁 Вам начислен бонус: <b>+{amount} дней</b> подписки!"
        else:
            return f"🎁 Вам начислен бонус: <b>{amount}₽</b>!"
    
    @staticmethod
    def level_changed(new_level: str) -> str:
        level_names = {
            "silver": "🥈 Silver",
            "gold": "🥇 Gold", 
            "platinum": "💎 Platinum"
        }
        level_display = level_names.get(new_level, new_level)
        return f"⭐ Ваш уровень лояльности повышен до <b>{level_display}</b>!"
    
    @staticmethod
    def badge_granted(badge_name: str) -> str:
        return f"🏆 Вы получили достижение: <b>{badge_name}</b>!"
    
    @staticmethod
    def withdrawal_approved(amount: int) -> str:
        return f"✅ Заявка на вывод <b>{amount:,}₽</b> одобрена!"
    
    @staticmethod
    def withdrawal_rejected(amount: int, reason: str = "") -> str:
        text = f"❌ Заявка на вывод <b>{amount:,}₽</b> отклонена."
        if reason:
            text += f"\n\n<b>Причина:</b> {reason}"
        return text
    
    @staticmethod
    def balance_adjusted(amount: int, is_add: bool) -> str:
        if is_add:
            return f"💰 Ваш баланс пополнен на <b>+{amount:,}₽</b>"
        else:
            return f"💸 С вашего баланса списано <b>{amount:,}₽</b>"
