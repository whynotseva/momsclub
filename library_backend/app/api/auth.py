"""
API endpoints для авторизации
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.config import settings
from app.schemas import TelegramAuthData, TokenResponse, UserInfo, SubscriptionStatus, LoyaltyInfo, ReferralInfo, PaymentItem, PaymentHistory
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


# Пороги уровней лояльности (дни)
SILVER_THRESHOLD = 90
GOLD_THRESHOLD = 180
PLATINUM_THRESHOLD = 365


@router.get("/loyalty", response_model=LoyaltyInfo)
def get_loyalty_info(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить информацию о лояльности пользователя
    """
    # Получаем данные о лояльности из БД
    user_result = db.execute(
        text("""
        SELECT 
            first_payment_date,
            current_loyalty_level,
            one_time_discount_percent,
            lifetime_discount_percent
        FROM users 
        WHERE id = :user_id
        """),
        {"user_id": current_user["user_id"]}
    ).fetchone()
    
    if not user_result:
        return LoyaltyInfo()
    
    first_payment_date, current_level, one_time_discount, lifetime_discount = user_result
    
    # Считаем дни в клубе как сумму дней активных подписок (как в боте)
    days_in_club = 0
    if first_payment_date:
        # Получаем все подписки пользователя
        subscriptions = db.execute(
            text("""
                SELECT start_date, end_date FROM subscriptions 
                WHERE user_id = :user_id 
                ORDER BY start_date
            """),
            {"user_id": current_user["user_id"]}
        ).fetchall()
        
        now = datetime.now()
        periods = []
        
        for sub in subscriptions:
            start_date, end_date = sub
            try:
                if isinstance(start_date, str):
                    start = datetime.fromisoformat(start_date.replace('Z', '+00:00').split('+')[0])
                else:
                    start = start_date
                if isinstance(end_date, str):
                    end = datetime.fromisoformat(end_date.replace('Z', '+00:00').split('+')[0])
                else:
                    end = end_date
                
                # Считаем только до текущего момента
                end_for_calc = min(end, now)
                if start <= end_for_calc and start <= now:
                    periods.append((start, end_for_calc))
            except:
                pass
        
        if periods:
            # Сортируем и объединяем перекрывающиеся периоды
            periods.sort(key=lambda x: x[0])
            merged = []
            current_start, current_end = periods[0]
            
            for start, end in periods[1:]:
                if start <= current_end:
                    current_end = max(current_end, end)
                else:
                    merged.append((current_start, current_end))
                    current_start, current_end = start, end
            merged.append((current_start, current_end))
            
            # Суммируем дни
            for start, end in merged:
                days_in_club += max(0, (end - start).days)
    
    current_level = current_level or "none"
    
    # Определяем следующий уровень и прогресс
    if current_level == "none":
        next_level = "silver"
        days_to_next = max(0, SILVER_THRESHOLD - days_in_club)
        progress = min(100, int((days_in_club / SILVER_THRESHOLD) * 100)) if SILVER_THRESHOLD > 0 else 0
    elif current_level == "silver":
        next_level = "gold"
        days_to_next = max(0, GOLD_THRESHOLD - days_in_club)
        progress = min(100, int(((days_in_club - SILVER_THRESHOLD) / (GOLD_THRESHOLD - SILVER_THRESHOLD)) * 100))
    elif current_level == "gold":
        next_level = "platinum"
        days_to_next = max(0, PLATINUM_THRESHOLD - days_in_club)
        progress = min(100, int(((days_in_club - GOLD_THRESHOLD) / (PLATINUM_THRESHOLD - GOLD_THRESHOLD)) * 100))
    else:  # platinum
        next_level = None
        days_to_next = None
        progress = 100
    
    # Эффективная скидка (приоритет: lifetime > one_time)
    discount = lifetime_discount or one_time_discount or 0
    
    return LoyaltyInfo(
        current_level=current_level,
        days_in_club=days_in_club,
        next_level=next_level,
        days_to_next_level=days_to_next,
        progress_percent=max(0, progress),
        discount_percent=discount,
        silver_days=SILVER_THRESHOLD,
        gold_days=GOLD_THRESHOLD,
        platinum_days=PLATINUM_THRESHOLD
    )


# Бонусы рефералов по уровню лояльности
REFERRAL_BONUS_BY_LEVEL = {
    'none': {'percent': 10, 'days': 7},
    'silver': {'percent': 15, 'days': 7},
    'gold': {'percent': 20, 'days': 7},
    'platinum': {'percent': 30, 'days': 7},
}


@router.get("/referral", response_model=ReferralInfo)
def get_referral_info(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить информацию о реферальной программе пользователя
    """
    telegram_id = current_user["telegram_id"]
    
    # Получаем данные пользователя
    user_result = db.execute(
        text("""
            SELECT referral_code, referral_balance, total_referrals_paid, 
                   total_earned_referral, current_loyalty_level
            FROM users 
            WHERE telegram_id = :tg_id
        """),
        {"tg_id": telegram_id}
    ).fetchone()
    
    if not user_result:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    referral_code, balance, paid_referrals, total_earned, loyalty_level = user_result
    
    # Если нет реферального кода — генерируем
    if not referral_code:
        import random
        import string
        referral_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        db.execute(
            text("UPDATE users SET referral_code = :code WHERE telegram_id = :tg_id"),
            {"code": referral_code, "tg_id": telegram_id}
        )
        db.commit()
    
    # Считаем всего приглашённых (по referrer_id)
    total_referrals_result = db.execute(
        text("""
            SELECT COUNT(*) FROM users 
            WHERE referrer_id = (SELECT id FROM users WHERE telegram_id = :tg_id)
        """),
        {"tg_id": telegram_id}
    ).fetchone()
    total_referrals = total_referrals_result[0] if total_referrals_result else 0
    
    # Бонусы по уровню лояльности
    bonus = REFERRAL_BONUS_BY_LEVEL.get(loyalty_level or 'none', REFERRAL_BONUS_BY_LEVEL['none'])
    
    # Формируем ссылку
    referral_link = f"https://t.me/momsclubsubscribe_bot?start=ref_{referral_code}"
    
    return ReferralInfo(
        referral_code=referral_code,
        referral_link=referral_link,
        referral_balance=balance or 0,
        total_referrals=total_referrals,
        paid_referrals=paid_referrals or 0,
        total_earned=total_earned or 0,
        bonus_percent=bonus['percent'],
        bonus_days=bonus['days']
    )


@router.get("/payments", response_model=PaymentHistory)
def get_payment_history(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить историю платежей пользователя
    
    Показываем:
    - Подтверждённые успешные платежи (is_confirmed = 1)
    - ИЛИ админские выдачи (payment_method = 'admin')
    - ИЛИ оплата балансом (payment_method = 'referral_balance')
    Исключаем тестовые платежи (содержащие 'ТЕСТ', 'тест', 'TEST' в details)
    """
    payments_result = db.execute(
        text("""
            SELECT p.id, p.amount, p.status, p.payment_method, p.details, p.days, p.created_at,
                   u.first_name as admin_first_name, u.username as admin_username
            FROM payment_logs p
            LEFT JOIN users u ON p.admin_id = u.id
            WHERE p.user_id = :user_id
              AND p.status = 'success'
              AND (
                  p.is_confirmed = 1 
                  OR p.payment_method = 'admin' 
                  OR p.payment_method = 'referral_balance'
              )
              AND (
                  p.details IS NULL 
                  OR (
                      p.details NOT LIKE '%ТЕСТ%' 
                      AND p.details NOT LIKE '%Тест%' 
                      AND p.details NOT LIKE '%тест%'
                      AND p.details NOT LIKE '%TEST%'
                      AND p.details NOT LIKE '%Test%'
                      AND p.details NOT LIKE '%test%'
                  )
              )
            ORDER BY p.created_at DESC
            LIMIT 20
        """),
        {"user_id": current_user["user_id"]}
    ).fetchall()
    
    payments = []
    total_paid = 0
    
    for row in payments_result:
        pid, amount, status, method, details, days, created_at, admin_first_name, admin_username = row
        
        # Форматируем дату
        if isinstance(created_at, str):
            date_str = created_at[:19]
        else:
            date_str = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else ""
        
        # Формируем имя админа
        admin_name = None
        if method == 'admin' and (admin_first_name or admin_username):
            admin_name = admin_first_name or f"@{admin_username}"
        
        payments.append(PaymentItem(
            id=pid,
            amount=amount or 0,
            status=status or "unknown",
            payment_method=method,
            details=details,
            days=days,
            created_at=date_str,
            admin_name=admin_name
        ))
        
        if status == "success":
            total_paid += amount or 0
    
    return PaymentHistory(
        payments=payments,
        total_paid=total_paid,
        total_count=len(payments)
    )
