"""
API endpoints для авторизации
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.config import settings
from app.schemas import TelegramAuthData, TokenResponse, UserInfo, SubscriptionStatus
from app.utils.auth import verify_telegram_auth, create_access_token
from app.api.dependencies import get_current_user, get_current_user_with_subscription


router = APIRouter(prefix="/auth", tags=["Авторизация"])


# ==================== DEV ONLY: Тестовый токен ====================

@router.get("/dev-token")
def get_dev_token(
    telegram_id: int = 534740911,  # Твой telegram_id
    db: Session = Depends(get_db)
):
    """
    ⚠️ ТОЛЬКО ДЛЯ РАЗРАБОТКИ!
    Создаёт тестовый токен без Telegram авторизации
    """
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступно только в DEBUG режиме"
        )
    
    # Ищем пользователя
    user_result = db.execute(
        text("SELECT id, telegram_id, first_name, username FROM users WHERE telegram_id = :tg_id"),
        {"tg_id": telegram_id}
    ).fetchone()
    
    if not user_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пользователь {telegram_id} не найден"
        )
    
    user_id, tg_id, first_name, username = user_result
    
    # Создаём токен
    access_token = create_access_token(
        data={"telegram_id": tg_id}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "telegram_id": tg_id,
            "first_name": first_name,
            "username": username
        },
        "warning": "⚠️ DEV TOKEN - не использовать в продакшене!"
    }


@router.post("/telegram", response_model=TokenResponse)
def telegram_login(
    auth_data: TelegramAuthData,
    db: Session = Depends(get_db)
):
    """
    Авторизация через Telegram Login Widget
    
    1. Проверяет подлинность данных от Telegram
    2. Проверяет наличие пользователя в БД
    3. Проверяет активную подписку
    4. Возвращает JWT токен
    """
    # Проверяем подлинность данных от Telegram
    auth_dict = auth_data.model_dump()
    print(f"🔐 Telegram auth attempt: id={auth_data.id}, hash={auth_data.hash[:10]}...")
    
    if not verify_telegram_auth(auth_dict.copy()):  # copy() чтобы не мутировать оригинал
        print(f"❌ Auth failed for telegram_id={auth_data.id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидные данные от Telegram"
        )
    print(f"✅ Auth success for telegram_id={auth_data.id}")
    
    # Проверяем, что пользователь существует в БД
    user_result = db.execute(
        text("SELECT id, telegram_id, first_name, username FROM users WHERE telegram_id = :tg_id"),
        {"tg_id": auth_data.id}
    ).fetchone()
    
    if not user_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден в системе MomsClub"
        )
    
    user_id, telegram_id, _, _ = user_result  # first_name и username берём из auth_data (актуальные)
    first_name = auth_data.first_name
    username = auth_data.username
    
    # Всегда обновляем photo_url, first_name и username из Telegram (могут меняться)
    db.execute(
        text("""
            UPDATE users 
            SET photo_url = :photo_url,
                first_name = :first_name,
                username = :username
            WHERE telegram_id = :tg_id
        """),
        {
            "photo_url": auth_data.photo_url,  # Может быть None если нет аватарки
            "first_name": auth_data.first_name,
            "username": auth_data.username,
            "tg_id": auth_data.id
        }
    )
    db.commit()
    if auth_data.photo_url:
        print(f"📸 Updated photo_url for user {telegram_id}")
    
    # Проверяем активную подписку
    subscription_result = db.execute(
        text("""
        SELECT 
            s.id,
            s.is_active,
            s.end_date
        FROM subscriptions s
        WHERE s.user_id = :user_id
          AND s.is_active = 1
          AND s.end_date > datetime('now')
        ORDER BY s.end_date DESC
        LIMIT 1
        """),
        {"user_id": user_id}
    ).fetchone()
    
    has_active_subscription = subscription_result is not None
    subscription_end = subscription_result[2] if subscription_result else None
    
    # ИЗМЕНЕНО: Пускаем пользователя даже без подписки
    # Доступ к библиотеке ограничивается на фронтенде
    if has_active_subscription:
        print(f"✅ User {first_name} ({telegram_id}) logged in, subscription until {subscription_end}")
    else:
        print(f"⚠️ User {first_name} ({telegram_id}) logged in WITHOUT subscription (profile only)")
    
    # Создаём JWT токен
    access_token = create_access_token(
        data={"telegram_id": telegram_id}
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserInfo(
            telegram_id=telegram_id,
            first_name=first_name,
            username=username,
            photo_url=auth_data.photo_url,
            has_active_subscription=has_active_subscription,
            subscription_end=subscription_end
        )
    )


@router.get("/me", response_model=UserInfo)
def get_current_user_info(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить информацию о текущем пользователе
    """
    # Проверяем активную подписку
    subscription_result = db.execute(
        text("""
        SELECT 
            s.id,
            s.is_active,
            s.end_date
        FROM subscriptions s
        WHERE s.user_id = :user_id
          AND s.is_active = 1
          AND s.end_date > datetime('now')
        ORDER BY s.end_date DESC
        LIMIT 1
        """),
        {"user_id": current_user["user_id"]}
    ).fetchone()
    
    has_active_subscription = subscription_result is not None
    subscription_end = subscription_result[2] if subscription_result else None
    
    return UserInfo(
        telegram_id=current_user["telegram_id"],
        first_name=current_user["first_name"],
        username=current_user.get("username"),
        photo_url=current_user.get("photo_url"),
        loyalty_level=current_user.get("loyalty_level", "none"),
        admin_group=current_user.get("admin_group"),
        has_active_subscription=has_active_subscription,
        subscription_end=subscription_end
    )


@router.get("/check-subscription", response_model=SubscriptionStatus)
def check_subscription(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Проверить статус подписки текущего пользователя
    """
    # Проверяем активную подписку
    subscription_result = db.execute(
        text("""
        SELECT 
            s.end_date
        FROM subscriptions s
        WHERE s.user_id = :user_id
          AND s.is_active = 1
          AND s.end_date > datetime('now')
        ORDER BY s.end_date DESC
        LIMIT 1
        """),
        {"user_id": current_user["user_id"]}
    ).fetchone()
    
    if not subscription_result:
        return SubscriptionStatus(
            has_active_subscription=False,
            subscription_end=None,
            days_left=None
        )
    
    end_date_str = subscription_result[0]
    end_date = datetime.fromisoformat(end_date_str)
    days_left = (end_date - datetime.now()).days
    
    return SubscriptionStatus(
        has_active_subscription=True,
        subscription_end=end_date_str,
        days_left=days_left
    )
