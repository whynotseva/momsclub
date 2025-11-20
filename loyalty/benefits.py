"""
Модуль для применения бонусов лояльности
"""
import logging
import json
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from database.models import User, LoyaltyEvent
from database.crud import extend_subscription_days, get_active_subscription
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Типы бонусов
BenefitCode = Literal[
    'days_7', 'days_14', 'days_30_gift',
    'discount_5', 'discount_10', 'discount_15_forever'
]


async def apply_benefit(
    db: AsyncSession,
    user: User,
    level: str,
    code: BenefitCode
) -> bool:
    """
    Применяет выбранный бонус к пользователю.
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        level: Уровень лояльности ('silver', 'gold', 'platinum')
        code: Код бонуса
        
    Returns:
        True если успешно, False в противном случае
    """
    # ИСПРАВЛЕНО: сохраняем user_id в начале для защиты от greenlet
    user_id = user.id
    
    try:
        logger.info(f"Применение бонуса {code} для user_id={user_id}, level={level}")
        
        payload_data = {"benefit": code, "level": level}
        
        if code == 'days_7':
            # Добавляем 7 дней доступа
            active_sub = await get_active_subscription(db, user_id)
            if active_sub:
                success = await extend_subscription_days(db, user_id, 7, reason="loyalty_bonus_silver")
            else:
                success = await apply_benefit_for_inactive_user(db, user, 7)
            if success:
                payload_data["days"] = 7
                
        elif code == 'days_14':
            # Добавляем 14 дней доступа
            active_sub = await get_active_subscription(db, user_id)
            if active_sub:
                success = await extend_subscription_days(db, user_id, 14, reason="loyalty_bonus_gold")
            else:
                success = await apply_benefit_for_inactive_user(db, user, 14)
            if success:
                payload_data["days"] = 14
                
        elif code == 'days_30_gift':
            # Добавляем 30 дней доступа и устанавливаем флаг gift_due
            active_sub = await get_active_subscription(db, user_id)
            if active_sub:
                success = await extend_subscription_days(db, user_id, 30, reason="loyalty_bonus_platinum")
            else:
                success = await apply_benefit_for_inactive_user(db, user, 30)
            if success:
                payload_data["days"] = 30
                # Устанавливаем флаг gift_due
                await db.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(gift_due=True)
                )
                await db.commit()
                
        elif code == 'discount_5':
            # Устанавливаем постоянную скидку 5%
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(lifetime_discount_percent=5)
            )
            await db.commit()
            success = True
            payload_data["discount_percent"] = 5
            payload_data["type"] = "lifetime"
            
        elif code == 'discount_10':
            # Устанавливаем постоянную скидку 10%
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(lifetime_discount_percent=10)
            )
            await db.commit()
            success = True
            payload_data["discount_percent"] = 10
            payload_data["type"] = "lifetime"
            
        elif code == 'discount_15_forever':
            # Устанавливаем пожизненную скидку 15%
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(lifetime_discount_percent=15)
            )
            await db.commit()
            success = True
            payload_data["discount_percent"] = 15
            payload_data["type"] = "lifetime"
            
        else:
            logger.error(f"Неизвестный код бонуса: {code}")
            return False
        
        if success:
            # Записываем событие выбора бонуса
            event = LoyaltyEvent(
                user_id=user_id,
                kind='benefit_chosen',
                level=level,
                payload=json.dumps(payload_data, ensure_ascii=False)
            )
            db.add(event)
            await db.commit()
            
            logger.info(f"✅ Бонус {code} успешно применён для user_id={user_id}")
            return True
        else:
            logger.error(f"❌ Не удалось применить бонус {code} для user_id={user_id}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при применении бонуса {code} для user_id={user_id}: {e}", exc_info=True)
        await db.rollback()
        return False


async def apply_benefit_for_inactive_user(
    db: AsyncSession,
    user: User,
    days: int
) -> bool:
    """
    Применяет бонусные дни для пользователя без активной подписки.
    Активирует доступ от текущей даты на N дней.
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        days: Количество дней
        
    Returns:
        True если успешно, False в противном случае
    """
    try:
        from database.crud import create_subscription
        
        # Создаём новую подписку от текущей даты
        end_date = datetime.now() + timedelta(days=days)
        
        subscription = await create_subscription(
            db=db,
            user_id=user.id,
            end_date=end_date,
            price=0,  # Бесплатный бонус
            payment_id=None
        )
        
        if subscription:
            logger.info(f"✅ Активирована подписка для user_id={user.id} на {days} дней (бонус лояльности)")
            return True
        else:
            logger.error(f"❌ Не удалось активировать подписку для user_id={user.id}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при активации подписки для user_id={user.id}: {e}", exc_info=True)
        await db.rollback()
        return False

