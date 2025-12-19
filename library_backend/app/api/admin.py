"""
API endpoints для админ-панели библиотеки
Доступ только для указанных telegram_id
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete, func
from typing import List, Optional
import os
import uuid
from datetime import datetime

from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.library_models import (
    LibraryCategory, LibraryMaterial, LibraryTag, 
    LibraryAttachment, materials_tags
)
from app.schemas.library import (
    MaterialCreate, MaterialUpdate, Material, MaterialListItem,
    CategoryCreate, Category,
    TagCreate, Tag
)
from app.services import AdminService, is_admin, ADMIN_IDS, send_telegram_notification
from app.schemas.user_schemas import (
    UserCard, UserSearchResult, UserSearchResponse,
    UserShort, SubscriptionInfo, LoyaltyInfo, ReferralInfo,
    BadgeInfo, GroupActivityInfo, PaymentInfo
)

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(current_user: dict = Depends(get_current_user)):
    """Проверка что пользователь — админ"""
    if not is_admin(current_user.get("telegram_id")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён. Только для администраторов."
        )
    return current_user


# ==================== СТАТИСТИКА ====================

@router.get("/stats")
def get_admin_stats(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Получить статистику библиотеки"""
    service = AdminService(db)
    return service.get_stats()


# ==================== МАТЕРИАЛЫ ====================

@router.get("/materials", response_model=List[MaterialListItem])
def get_all_materials(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
    page: int = 1,
    limit: int = 20,
    category_id: Optional[int] = None,
    is_published: Optional[bool] = None,
    search: Optional[str] = None
):
    """Получить все материалы (включая черновики)"""
    service = AdminService(db)
    return service.get_materials_list(page, limit, category_id, is_published, search)


@router.post("/materials", response_model=Material)
def create_material(
    material: MaterialCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Создать новый материал"""
    
    # Создаём материал
    db_material = LibraryMaterial(
        title=material.title,
        description=material.description,
        content=material.content,
        external_url=material.external_url,
        cover_image=material.cover_image,
        category_id=material.category_id,
        format=material.format,
        level=material.level,
        duration=material.duration,
        topic=material.topic,
        niche=material.niche,
        viral_score=material.viral_score,
        is_published=material.is_published,
        is_featured=material.is_featured,
        author=material.author
    )
    
    db.add(db_material)
    db.commit()
    db.refresh(db_material)
    
    # Добавляем теги если есть
    if material.tag_ids:
        for tag_id in material.tag_ids:
            db.execute(
                materials_tags.insert().values(
                    material_id=db_material.id,
                    tag_id=tag_id
                )
            )
        db.commit()
    
    return db_material


@router.get("/materials/{material_id}", response_model=Material)
def get_material(
    material_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Получить материал по ID"""
    
    result = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    )
    material = result.scalar_one_or_none()
    
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    return material


@router.put("/materials/{material_id}", response_model=Material)
def update_material(
    material_id: int,
    material: MaterialUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Обновить материал"""
    
    result = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    )
    db_material = result.scalar_one_or_none()
    
    if not db_material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    # Обновляем поля
    update_data = material.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field != "tag_ids":
            setattr(db_material, field, value)
    
    db_material.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_material)
    
    # Обновляем теги если переданы
    if material.tag_ids is not None:
        # Удаляем старые теги
        db.execute(
            delete(materials_tags).where(materials_tags.c.material_id == material_id)
        )
        # Добавляем новые
        for tag_id in material.tag_ids:
            db.execute(
                materials_tags.insert().values(
                    material_id=material_id,
                    tag_id=tag_id
                )
            )
        db.commit()
    
    return db_material


@router.delete("/materials/{material_id}")
def delete_material(
    material_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Удалить материал"""
    
    result = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    )
    db_material = result.scalar_one_or_none()
    
    if not db_material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    db.delete(db_material)
    db.commit()
    
    return {"message": "Материал удалён", "id": material_id}


@router.post("/materials/{material_id}/publish")
def publish_material(
    material_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Опубликовать материал"""
    
    db.execute(
        update(LibraryMaterial)
        .where(LibraryMaterial.id == material_id)
        .values(is_published=True, published_at=datetime.utcnow())
    )
    db.commit()
    
    return {"message": "Материал опубликован", "id": material_id}


@router.post("/materials/{material_id}/unpublish")
def unpublish_material(
    material_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Снять материал с публикации"""
    
    db.execute(
        update(LibraryMaterial)
        .where(LibraryMaterial.id == material_id)
        .values(is_published=False)
    )
    db.commit()
    
    return {"message": "Материал снят с публикации", "id": material_id}


# ==================== КАТЕГОРИИ ====================

@router.post("/categories", response_model=Category)
def create_category(
    category: CategoryCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Создать категорию"""
    
    db_category = LibraryCategory(
        name=category.name,
        slug=category.slug or generate_slug(category.name),
        description=category.description,
        icon=category.icon,
        position=category.position or 0
    )
    
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    
    return db_category


@router.put("/categories/{category_id}", response_model=Category)
def update_category(
    category_id: int,
    category: CategoryCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Обновить категорию"""
    
    result = db.execute(
        select(LibraryCategory).where(LibraryCategory.id == category_id)
    )
    db_category = result.scalar_one_or_none()
    
    if not db_category:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    
    db_category.name = category.name
    db_category.slug = category.slug or db_category.slug
    db_category.description = category.description
    db_category.icon = category.icon
    db_category.position = category.position if category.position is not None else db_category.position
    
    db.commit()
    db.refresh(db_category)
    
    return db_category


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Удалить категорию"""
    
    # Проверяем есть ли материалы в категории
    materials_count = db.scalar(
        select(func.count(LibraryMaterial.id))
        .where(LibraryMaterial.category_id == category_id)
    )
    
    if materials_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя удалить категорию с материалами ({materials_count} шт.)"
        )
    
    db.execute(
        delete(LibraryCategory).where(LibraryCategory.id == category_id)
    )
    db.commit()
    
    return {"message": "Категория удалена", "id": category_id}


# ==================== ТЕГИ ====================

@router.get("/tags", response_model=List[Tag])
def get_all_tags(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Получить все теги"""
    
    result = db.execute(
        select(LibraryTag).order_by(LibraryTag.name)
    )
    return result.scalars().all()


@router.post("/tags", response_model=Tag)
def create_tag(
    tag: TagCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Создать тег"""
    
    db_tag = LibraryTag(
        name=tag.name,
        slug=tag.slug or generate_slug(tag.name)
    )
    
    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)
    
    return db_tag


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Удалить тег"""
    
    db.execute(delete(LibraryTag).where(LibraryTag.id == tag_id))
    db.commit()
    
    return {"message": "Тег удалён", "id": tag_id}


# ==================== ЗАГРУЗКА ФАЙЛОВ ====================

UPLOAD_DIR = "uploads"

@router.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin)
):
    """Загрузить файл (обложка, PDF, видео)"""
    
    # Создаём директорию если нет
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Генерируем уникальное имя
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    
    # Сохраняем файл
    with open(file_path, "wb") as f:
        content = file.read()
        f.write(content)
    
    return {
        "filename": unique_name,
        "original_name": file.filename,
        "url": f"/uploads/{unique_name}",
        "size": len(content)
    }


# ==================== УТИЛИТЫ ====================

def generate_slug(text: str) -> str:
    """Генерация slug из текста"""
    import re
    from transliterate import translit
    
    try:
        # Транслитерация кириллицы
        text = translit(text, 'ru', reversed=True)
    except:
        pass
    
    # Очищаем от спецсимволов
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    
    return slug


# ==================== ПОЛЬЗОВАТЕЛИ ====================

@router.get("/users/search", response_model=UserSearchResponse)
def search_users(
    q: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
    limit: int = 20
):
    """
    Поиск пользователей по telegram_id, username, имени или телефону.
    """
    if not q or len(q) < 2:
        return UserSearchResponse(users=[], total=0, query=q)
    
    # Пробуем найти по telegram_id (если это число)
    users = []
    
    try:
        telegram_id = int(q)
        result = db.execute(
            select(
                "users.id", "users.telegram_id", "users.username", 
                "users.first_name", "users.last_name", "users.created_at",
                "users.current_loyalty_level"
            ).select_from(
                db.execute("SELECT 1").scalar_subquery().table  # dummy
            ).where(False)  # placeholder
        )
    except ValueError:
        telegram_id = None
    
    # SQL запрос поиска
    sql = """
        SELECT 
            u.id, u.telegram_id, u.username, u.first_name, u.last_name,
            u.created_at, u.current_loyalty_level,
            CASE WHEN s.id IS NOT NULL AND s.end_date > datetime('now') AND s.is_active = 1 
                 THEN 1 ELSE 0 END as has_subscription
        FROM users u
        LEFT JOIN subscriptions s ON u.id = s.user_id
        WHERE 
            u.telegram_id = :telegram_id
            OR u.username LIKE :pattern
            OR u.first_name LIKE :pattern
            OR u.last_name LIKE :pattern
            OR u.phone LIKE :pattern
        GROUP BY u.id
        ORDER BY u.created_at DESC
        LIMIT :limit
    """
    
    from sqlalchemy import text
    result = db.execute(
        text(sql),
        {
            "telegram_id": telegram_id if telegram_id else -1,
            "pattern": f"%{q}%",
            "limit": limit
        }
    )
    
    users = []
    for row in result:
        users.append(UserSearchResult(
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            has_active_subscription=bool(row.has_subscription),
            loyalty_level=row.current_loyalty_level or "none",
            created_at=row.created_at
        ))
    
    return UserSearchResponse(users=users, total=len(users), query=q)


@router.get("/users/{telegram_id}", response_model=UserCard)
def get_user_card(
    telegram_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """
    Получить полную карточку пользователя по telegram_id.
    """
    from sqlalchemy import text
    
    # Получаем пользователя
    user_sql = """
        SELECT * FROM users WHERE telegram_id = :telegram_id
    """
    user_result = db.execute(text(user_sql), {"telegram_id": telegram_id})
    user_row = user_result.fetchone()
    
    if not user_row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user = dict(user_row._mapping)
    
    # Получаем активную подписку
    sub_sql = """
        SELECT * FROM subscriptions 
        WHERE user_id = :user_id AND is_active = 1
        ORDER BY end_date DESC LIMIT 1
    """
    sub_result = db.execute(text(sub_sql), {"user_id": user["id"]})
    sub_row = sub_result.fetchone()
    
    subscription = None
    has_active_subscription = False
    if sub_row:
        sub = dict(sub_row._mapping)
        from datetime import datetime, timezone
        end_date = sub["end_date"]
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        
        now = datetime.now()
        days_left = (end_date - now).days if end_date > now else 0
        is_expired = end_date < now
        has_active_subscription = not is_expired
        
        subscription = SubscriptionInfo(
            id=sub["id"],
            start_date=sub["start_date"],
            end_date=sub["end_date"],
            is_active=sub["is_active"],
            price=sub["price"],
            days_left=max(0, days_left),
            is_expired=is_expired
        )
    
    # Лояльность
    days_in_club = 0
    if user.get("first_payment_date"):
        first_payment = user["first_payment_date"]
        if isinstance(first_payment, str):
            first_payment = datetime.fromisoformat(first_payment.replace("Z", "+00:00"))
        days_in_club = (datetime.now() - first_payment).days
    
    loyalty = LoyaltyInfo(
        level=user.get("current_loyalty_level") or "none",
        first_payment_date=user.get("first_payment_date"),
        days_in_club=days_in_club,
        one_time_discount_percent=user.get("one_time_discount_percent") or 0,
        lifetime_discount_percent=user.get("lifetime_discount_percent") or 0,
        pending_loyalty_reward=user.get("pending_loyalty_reward") or False,
        gift_due=user.get("gift_due") or False
    )
    
    # Рефералы
    referrer = None
    if user.get("referrer_id"):
        ref_sql = "SELECT telegram_id, username, first_name, last_name FROM users WHERE id = :id"
        ref_result = db.execute(text(ref_sql), {"id": user["referrer_id"]})
        ref_row = ref_result.fetchone()
        if ref_row:
            referrer = UserShort(
                telegram_id=ref_row.telegram_id,
                username=ref_row.username,
                first_name=ref_row.first_name,
                last_name=ref_row.last_name
            )
    
    # Количество рефералов
    refs_count_sql = "SELECT COUNT(*) as cnt FROM users WHERE referrer_id = :user_id"
    refs_count = db.execute(text(refs_count_sql), {"user_id": user["id"]}).scalar() or 0
    
    referral = ReferralInfo(
        referral_code=user.get("referral_code"),
        referral_balance=user.get("referral_balance") or 0,
        total_referrals_paid=user.get("total_referrals_paid") or 0,
        total_earned_referral=user.get("total_earned_referral") or 0,
        referrer=referrer,
        referrals_count=refs_count
    )
    
    # Достижения (badges)
    badges_sql = "SELECT badge_type, earned_at FROM user_badges WHERE user_id = :user_id"
    badges_result = db.execute(text(badges_sql), {"user_id": user["id"]})
    badges = [BadgeInfo(badge_type=row.badge_type, earned_at=row.earned_at) for row in badges_result]
    
    # Активность в группе
    activity_sql = "SELECT message_count, last_activity FROM group_activity WHERE user_id = :user_id"
    activity_result = db.execute(text(activity_sql), {"user_id": user["id"]})
    activity_row = activity_result.fetchone()
    group_activity = None
    if activity_row:
        group_activity = GroupActivityInfo(
            message_count=activity_row.message_count or 0,
            last_activity=activity_row.last_activity
        )
    
    # Последние платежи
    payments_sql = """
        SELECT id, amount, status, days, created_at 
        FROM payment_logs 
        WHERE user_id = :user_id 
        ORDER BY created_at DESC 
        LIMIT 5
    """
    payments_result = db.execute(text(payments_sql), {"user_id": user["id"]})
    recent_payments = [
        PaymentInfo(
            id=row.id, amount=row.amount, status=row.status,
            days=row.days, created_at=row.created_at
        ) for row in payments_result
    ]
    
    # Статистика платежей
    stats_sql = """
        SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total 
        FROM payment_logs 
        WHERE user_id = :user_id AND status = 'success'
    """
    stats_result = db.execute(text(stats_sql), {"user_id": user["id"]})
    stats_row = stats_result.fetchone()
    total_payments_count = stats_row.cnt if stats_row else 0
    total_paid_amount = stats_row.total if stats_row else 0
    
    return UserCard(
        id=user["id"],
        telegram_id=user["telegram_id"],
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        phone=user.get("phone"),
        email=user.get("email"),
        birthday=user.get("birthday"),
        is_active=user.get("is_active", True),
        is_blocked=user.get("is_blocked", False),
        created_at=user["created_at"],
        subscription=subscription,
        has_active_subscription=has_active_subscription,
        is_recurring_active=user.get("is_recurring_active", False),
        autopay_streak=user.get("autopay_streak") or 0,
        loyalty=loyalty,
        referral=referral,
        badges=badges,
        group_activity=group_activity,
        recent_payments=recent_payments,
        total_payments_count=total_payments_count,
        total_paid_amount=total_paid_amount,
        admin_group=user.get("admin_group"),
        is_first_payment_done=user.get("is_first_payment_done", False)
    )


# ==================== СПИСКИ ====================

@router.get("/subscriptions")
def get_subscriptions_list(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
    filter: str = "active",  # active, expiring, expired, all
    limit: int = 50
):
    """Список подписок с фильтрами"""
    from sqlalchemy import text
    
    if filter == "active":
        where = "s.is_active = 1 AND s.end_date > datetime('now')"
    elif filter == "expiring":
        where = "s.is_active = 1 AND s.end_date > datetime('now') AND s.end_date < datetime('now', '+7 days')"
    elif filter == "expired":
        where = "s.is_active = 1 AND s.end_date < datetime('now')"
    else:
        where = "1=1"
    
    sql = f"""
        SELECT u.telegram_id, u.username, u.first_name, u.is_recurring_active,
               s.end_date, s.price, julianday(s.end_date) - julianday('now') as days_left
        FROM subscriptions s
        JOIN users u ON s.user_id = u.id
        WHERE {where}
        ORDER BY s.end_date ASC
        LIMIT :limit
    """
    result = db.execute(text(sql), {"limit": limit})
    
    return [{
        "telegram_id": r.telegram_id,
        "username": r.username,
        "first_name": r.first_name,
        "is_recurring_active": r.is_recurring_active,
        "end_date": r.end_date,
        "price": r.price,
        "days_left": int(r.days_left) if r.days_left else 0
    } for r in result]


@router.get("/withdrawals")
def get_withdrawals_list(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
    status: str = "pending"  # pending, approved, rejected, all
):
    """Список заявок на вывод"""
    from sqlalchemy import text
    
    where = f"w.status = '{status}'" if status != "all" else "1=1"
    
    sql = f"""
        SELECT w.id, w.amount, w.payment_method, w.payment_details, w.status, w.created_at,
               u.telegram_id, u.username, u.first_name
        FROM withdrawal_requests w
        JOIN users u ON w.user_id = u.id
        WHERE {where}
        ORDER BY w.created_at DESC
        LIMIT 50
    """
    result = db.execute(text(sql))
    
    return [{
        "id": r.id,
        "amount": r.amount,
        "payment_method": r.payment_method,
        "payment_details": r.payment_details,
        "status": r.status,
        "created_at": r.created_at,
        "user": {"telegram_id": r.telegram_id, "username": r.username, "first_name": r.first_name}
    } for r in result]


@router.post("/withdrawals/{withdrawal_id}/approve")
async def approve_withdrawal(
    withdrawal_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Одобрить заявку на вывод"""
    from sqlalchemy import text
    from datetime import datetime
    
    # Получаем заявку
    sql = "SELECT w.*, u.telegram_id FROM withdrawal_requests w JOIN users u ON w.user_id = u.id WHERE w.id = :id"
    result = db.execute(text(sql), {"id": withdrawal_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    # Обновляем статус
    db.execute(text("UPDATE withdrawal_requests SET status = 'approved', processed_at = :now WHERE id = :id"),
               {"now": datetime.now(), "id": withdrawal_id})
    db.commit()
    
    # Уведомляем пользователя
    from app.services import send_telegram_notification, NotificationTemplates
    await send_telegram_notification(row.telegram_id, NotificationTemplates.withdrawal_approved(row.amount), "withdrawal_approved")
    
    return {"success": True}


@router.post("/withdrawals/{withdrawal_id}/reject")
async def reject_withdrawal(
    withdrawal_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
    reason: str = ""
):
    """Отклонить заявку на вывод"""
    from sqlalchemy import text
    from datetime import datetime
    
    sql = "SELECT w.*, u.telegram_id, u.referral_balance FROM withdrawal_requests w JOIN users u ON w.user_id = u.id WHERE w.id = :id"
    result = db.execute(text(sql), {"id": withdrawal_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="Заявка уже обработана")
    
    # Обновляем статус и возвращаем деньги на баланс
    db.execute(text("UPDATE withdrawal_requests SET status = 'rejected', processed_at = :now, admin_comment = :reason WHERE id = :id"),
               {"now": datetime.now(), "id": withdrawal_id, "reason": reason})
    db.execute(text("UPDATE users SET referral_balance = referral_balance + :amount WHERE id = :uid"),
               {"amount": row.amount, "uid": row.user_id})
    db.commit()
    
    from app.services import send_telegram_notification, NotificationTemplates
    await send_telegram_notification(row.telegram_id, NotificationTemplates.withdrawal_rejected(row.amount, reason), "withdrawal_rejected")
    
    return {"success": True}


@router.get("/bot-stats")
def get_bot_stats(
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Статистика бота"""
    from sqlalchemy import text
    
    stats = {}
    
    # Общее количество пользователей
    stats["total_users"] = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
    
    # Активные подписки
    stats["active_subscriptions"] = db.execute(text(
        "SELECT COUNT(*) FROM subscriptions WHERE is_active = 1 AND end_date > datetime('now')"
    )).scalar()
    
    # Истекающие за 7 дней
    stats["expiring_soon"] = db.execute(text(
        "SELECT COUNT(*) FROM subscriptions WHERE is_active = 1 AND end_date > datetime('now') AND end_date < datetime('now', '+7 days')"
    )).scalar()
    
    # С автопродлением
    stats["with_autorenew"] = db.execute(text("SELECT COUNT(*) FROM users WHERE is_recurring_active = 1")).scalar()
    
    # Pending withdrawals
    stats["pending_withdrawals"] = db.execute(text("SELECT COUNT(*) FROM withdrawal_requests WHERE status = 'pending'")).scalar()
    
    # Доходы за месяц
    stats["monthly_revenue"] = db.execute(text(
        "SELECT COALESCE(SUM(amount), 0) FROM payment_logs WHERE status = 'success' AND created_at > datetime('now', '-30 days')"
    )).scalar()
    
    return stats


# ==================== УПРАВЛЕНИЕ ПОДПИСКОЙ ====================

class ExtendSubscriptionRequest(BaseModel):
    days: int
    reason: Optional[str] = None


@router.post("/users/{telegram_id}/subscription/extend")
async def extend_subscription(
    telegram_id: int,
    request: ExtendSubscriptionRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Продлить подписку на N дней"""
    from sqlalchemy import text
    from datetime import datetime, timedelta
    
    user_result = db.execute(text("SELECT id FROM users WHERE telegram_id = :tid"), {"tid": telegram_id})
    user_row = user_result.fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    sub_result = db.execute(text(
        "SELECT id, end_date FROM subscriptions WHERE user_id = :uid AND is_active = 1 ORDER BY end_date DESC LIMIT 1"
    ), {"uid": user_row.id})
    sub_row = sub_result.fetchone()
    if not sub_row:
        raise HTTPException(status_code=400, detail="Нет активной подписки")
    
    old_end = sub_row.end_date
    if isinstance(old_end, str):
        old_end = datetime.fromisoformat(old_end.replace("Z", "+00:00"))
    new_end = old_end + timedelta(days=request.days)
    
    db.execute(text("UPDATE subscriptions SET end_date = :end WHERE id = :id"), {"end": new_end, "id": sub_row.id})
    db.commit()
    
    from app.services import send_telegram_notification, NotificationTemplates
    await send_telegram_notification(telegram_id, NotificationTemplates.subscription_extended(request.days), "subscription_extended")
    
    return {"success": True, "old_end_date": str(old_end), "new_end_date": str(new_end), "days_added": request.days}


@router.post("/users/{telegram_id}/autorenew/toggle")
def toggle_autorenew(telegram_id: int, db: Session = Depends(get_db), admin: dict = Depends(require_admin)):
    """Переключить автопродление"""
    from sqlalchemy import text
    
    result = db.execute(text("SELECT id, is_recurring_active FROM users WHERE telegram_id = :tid"), {"tid": telegram_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    new_status = not row.is_recurring_active
    db.execute(text("UPDATE users SET is_recurring_active = :s WHERE id = :id"), {"s": new_status, "id": row.id})
    db.commit()
    
    return {"success": True, "is_recurring_active": new_status}


# ==================== УПРАВЛЕНИЕ ЛОЯЛЬНОСТЬЮ ====================

class SetLoyaltyLevelRequest(BaseModel):
    level: str  # 'none', 'silver', 'gold', 'platinum'


@router.post("/users/{telegram_id}/loyalty/level")
async def set_loyalty_level(
    telegram_id: int,
    request: SetLoyaltyLevelRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Установить уровень лояльности"""
    from sqlalchemy import text
    
    valid_levels = ['none', 'silver', 'gold', 'platinum']
    if request.level not in valid_levels:
        raise HTTPException(status_code=400, detail=f"Недопустимый уровень: {valid_levels}")
    
    result = db.execute(text("SELECT id, current_loyalty_level FROM users WHERE telegram_id = :tid"), {"tid": telegram_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    old_level = row.current_loyalty_level
    db.execute(text("UPDATE users SET current_loyalty_level = :lvl WHERE id = :id"), {"lvl": request.level, "id": row.id})
    db.commit()
    
    if request.level != 'none' and request.level != old_level:
        from app.services import send_telegram_notification, NotificationTemplates
        await send_telegram_notification(telegram_id, NotificationTemplates.level_changed(request.level), "loyalty_level_changed")
    
    return {"success": True, "old_level": old_level, "new_level": request.level}


# ==================== УПРАВЛЕНИЕ БАЛАНСОМ ====================

class AdjustBalanceRequest(BaseModel):
    amount: int  # положительное = начисление, отрицательное = списание
    comment: Optional[str] = None


@router.post("/users/{telegram_id}/balance/adjust")
async def adjust_balance(
    telegram_id: int,
    request: AdjustBalanceRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Начислить или списать с реферального баланса"""
    from sqlalchemy import text
    
    result = db.execute(text("SELECT id, referral_balance FROM users WHERE telegram_id = :tid"), {"tid": telegram_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    old_balance = row.referral_balance or 0
    new_balance = old_balance + request.amount
    
    if new_balance < 0:
        raise HTTPException(status_code=400, detail="Баланс не может быть отрицательным")
    
    db.execute(text("UPDATE users SET referral_balance = :bal WHERE id = :id"), {"bal": new_balance, "id": row.id})
    db.commit()
    
    if request.amount != 0:
        from app.services import send_telegram_notification, NotificationTemplates
        is_add = request.amount > 0
        await send_telegram_notification(telegram_id, NotificationTemplates.balance_adjusted(abs(request.amount), is_add), "balance_adjusted")
    
    return {"success": True, "old_balance": old_balance, "new_balance": new_balance, "adjustment": request.amount}


# ==================== УВЕДОМЛЕНИЯ ====================

class TestNotificationRequest(BaseModel):
    telegram_id: int
    message: str = "🧪 Тестовое уведомление от сайта!"


@router.post("/test-notification")
async def test_notification(
    request: TestNotificationRequest,
    admin: dict = Depends(require_admin)
):
    """
    Тестовый endpoint для проверки отправки уведомлений.
    Отправляет сообщение в Telegram через API бота.
    """
    success = await send_telegram_notification(
        telegram_id=request.telegram_id,
        message=request.message,
        notification_type="test"
    )
    
    if success:
        return {"success": True, "message": "Уведомление отправлено"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось отправить уведомление"
        )
