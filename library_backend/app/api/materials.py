"""
API endpoints для материалов библиотеки
"""

from typing import List, Optional
from math import ceil
from datetime import datetime

import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, or_, and_, distinct, text

from app.database import get_db
from app.schemas import Material, MaterialListItem, MaterialCreate, MaterialUpdate, PaginatedResponse
from app.models.library_models import LibraryMaterial, LibraryCategory, LibraryTag, LibraryView, AdminActivityLog, materials_categories
from app.api.dependencies import get_current_user_with_subscription, get_current_user
from app.api.websocket import broadcast_admin_action
from app.api.push import send_push_notification_sync


def log_admin_action(db: Session, user: dict, action: str, entity_type: str, 
                     entity_id: int = None, entity_title: str = None, 
                     background_tasks: BackgroundTasks = None):
    """Записывает действие админа в лог и рассылает через WebSocket"""
    admin_name = user.get("first_name") or user.get("username") or "Админ"
    
    log_entry = AdminActivityLog(
        admin_id=user.get("telegram_id"),
        admin_name=admin_name,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_title=entity_title
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    
    # Рассылаем через WebSocket
    if background_tasks:
        background_tasks.add_task(
            broadcast_admin_action,
            log_entry.to_dict()
        )


router = APIRouter(prefix="/materials", tags=["Материалы"])

# Список админов
ADMIN_IDS = [534740911, 44054166]  # Полина и Всеволод

# URL API для генерации ссылок на обложки
API_BASE_URL = "https://api.librarymomsclub.ru/api"


def add_cover_url(item: dict) -> dict:
    """
    Добавляет cover_url и убирает base64 из cover_image для оптимизации.
    Вызывать для каждого материала перед отправкой клиенту.
    """
    if item.get("cover_image"):
        item["cover_url"] = f"{API_BASE_URL}/materials/{item['id']}/cover"
        item["cover_image"] = None  # Не передаём тяжёлый base64
    return item


@router.get("", response_model=PaginatedResponse)
def get_materials(
    # Фильтры
    search: Optional[str] = Query(None, description="Поиск по названию и описанию"),
    category_id: Optional[int] = Query(None, description="ID категории"),
    format: Optional[str] = Query(None, description="Формат материала"),
    level: Optional[str] = Query(None, description="Уровень сложности"),
    topic: Optional[str] = Query(None, description="Тематика"),
    niche: Optional[str] = Query(None, description="Ниша"),
    is_featured: Optional[bool] = Query(None, description="Только избранные"),
    include_drafts: Optional[bool] = Query(False, description="Включить черновики (только для админов)"),
    
    # Пагинация (без ограничений для библиотеки)
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(10000, ge=1, le=10000, description="Размер страницы (без лимита)"),
    
    # Сортировка
    sort: str = Query("created_desc", description="Сортировка: created_desc, created_asc, views_desc, title_asc"),
    
    # Зависимости
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """
    Получить список материалов с фильтрацией и пагинацией
    
    Требуется активная подписка
    """
    # Базовый запрос с eager loading категорий и избранного
    query = select(LibraryMaterial).options(
        selectinload(LibraryMaterial.categories),
        selectinload(LibraryMaterial.favorites)
    )
    
    # Фильтр по публикации (админы могут видеть черновики)
    if include_drafts and current_user["telegram_id"] in ADMIN_IDS:
        pass  # Показываем все
    else:
        query = query.where(LibraryMaterial.is_published == True)
    
    # Применяем фильтры
    if search:
        search_filter = or_(
            LibraryMaterial.title.ilike(f"%{search}%"),
            LibraryMaterial.description.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
    
    if category_id:
        query = query.where(LibraryMaterial.category_id == category_id)
    
    if format:
        query = query.where(LibraryMaterial.format == format)
    
    if level:
        query = query.where(LibraryMaterial.level == level)
    
    if topic:
        query = query.where(LibraryMaterial.topic == topic)
    
    if niche:
        query = query.where(LibraryMaterial.niche == niche)
    
    if is_featured is not None:
        query = query.where(LibraryMaterial.is_featured == is_featured)
    
    # Подсчёт общего количества
    total_query = select(func.count()).select_from(query.subquery())
    total = db.execute(total_query).scalar()
    
    # Сортировка
    if sort == "created_desc":
        query = query.order_by(LibraryMaterial.created_at.desc())
    elif sort == "created_asc":
        query = query.order_by(LibraryMaterial.created_at.asc())
    elif sort == "views_desc":
        query = query.order_by(LibraryMaterial.views.desc())
    elif sort == "title_asc":
        query = query.order_by(LibraryMaterial.title.asc())
    
    # Пагинация
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    # Выполняем запрос
    materials = db.execute(query).scalars().all()
    
    # Конвертируем в dict и добавляем cover_url
    items = [add_cover_url(m.to_dict()) for m in materials]
    
    # Используем to_dict() для правильной сериализации категорий
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total > 0 else 0
    )


@router.get("/{material_id}", response_model=Material)
def get_material(
    material_id: int,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """
    Получить полную информацию о материале
    
    Требуется активная подписка
    """
    material = db.execute(
        select(LibraryMaterial)
        .options(selectinload(LibraryMaterial.categories))
        .where(
            LibraryMaterial.id == material_id,
            LibraryMaterial.is_published == True
        )
    ).scalar_one_or_none()
    
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Материал не найден"
        )
    
    return material.to_dict(include_content=True)


@router.post("/{material_id}/view")
def record_view(
    material_id: int,
    duration_seconds: Optional[int] = None,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """
    Записать просмотр материала
    
    Требуется активная подписка
    """
    # Проверяем, что материал существует
    material = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    ).scalar_one_or_none()
    
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Материал не найден"
        )
    
    # Создаём запись просмотра
    view = LibraryView(
        material_id=material_id,
        user_id=current_user["user_id"],
        duration_seconds=duration_seconds
    )
    db.add(view)
    
    # Увеличиваем счётчик просмотров
    material.views += 1
    
    db.commit()
    
    return {"status": "ok", "message": "Просмотр записан"}


@router.get("/featured/list", response_model=List[MaterialListItem])
def get_featured_materials(
    limit: int = Query(10, ge=1, le=50, description="Количество материалов"),
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """
    Получить список избранных материалов ("Выбор Полины")
    
    Требуется активная подписка
    """
    materials = db.execute(
        select(LibraryMaterial)
        .where(
            LibraryMaterial.is_published == True,
            LibraryMaterial.is_featured == True
        )
        .order_by(LibraryMaterial.created_at.desc())
        .limit(limit)
    ).scalars().all()
    
    # Оптимизация: добавляем cover_url, убираем base64
    return [add_cover_url(m.to_dict()) for m in materials]


@router.get("/popular/list", response_model=List[MaterialListItem])
def get_popular_materials(
    limit: int = Query(10, ge=1, le=50, description="Количество материалов"),
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """
    Получить список популярных материалов (по просмотрам)
    
    Требуется активная подписка
    """
    materials = db.execute(
        select(LibraryMaterial)
        .where(LibraryMaterial.is_published == True)
        .order_by(LibraryMaterial.views.desc())
        .limit(limit)
    ).scalars().all()
    
    # Оптимизация: добавляем cover_url, убираем base64
    return [add_cover_url(m.to_dict()) for m in materials]


# ============== ИЗБРАННОЕ И ИСТОРИЯ ==============

@router.get("/favorites/my", response_model=List[MaterialListItem])
def get_my_favorites(
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Получить мои избранные материалы"""
    from app.models.library_models import LibraryFavorite
    
    materials = db.execute(
        select(LibraryMaterial)
        .join(LibraryFavorite, LibraryFavorite.material_id == LibraryMaterial.id)
        .where(
            LibraryFavorite.user_id == current_user["user_id"],
            LibraryMaterial.is_published == True
        )
        .order_by(LibraryFavorite.created_at.desc())
    ).scalars().all()
    
    # Оптимизация: добавляем cover_url, убираем base64
    return [add_cover_url(m.to_dict()) for m in materials]


@router.post("/{material_id}/favorite")
async def add_to_favorites(
    material_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Добавить материал в избранное"""
    from app.models.library_models import LibraryFavorite
    from app.api.websocket import broadcast_new_activity
    
    # Проверяем материал
    material = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    ).scalar_one_or_none()
    
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    # Получаем категорию для иконки
    category_icon = "📄"
    if material.category:
        category_icon = material.category.icon or "📄"
    
    # Проверяем, не добавлен ли уже
    existing = db.execute(
        select(LibraryFavorite).where(
            LibraryFavorite.user_id == current_user["user_id"],
            LibraryFavorite.material_id == material_id
        )
    ).scalar_one_or_none()
    
    if existing:
        return {"status": "ok", "message": "Уже в избранном", "is_favorite": True}
    
    favorite = LibraryFavorite(
        user_id=current_user["user_id"],
        material_id=material_id
    )
    db.add(favorite)
    
    # Логируем действие
    db.execute(
        text("INSERT INTO activity_log (user_id, action_type, material_id) VALUES (:user_id, 'favorite_add', :material_id)"),
        {"user_id": current_user["user_id"], "material_id": material_id}
    )
    
    db.commit()
    
    # Отправляем событие через WebSocket
    activity_data = {
        "type": "favorite_add",
        "created_at": datetime.now().isoformat(),
        "user": {
            "telegram_id": current_user["telegram_id"],
            "first_name": current_user["first_name"],
            "username": current_user.get("username"),
            "photo_url": current_user.get("photo_url")
        },
        "material": {
            "id": material.id,
            "title": material.title,
            "icon": category_icon
        }
    }
    asyncio.create_task(broadcast_new_activity(activity_data))
    
    return {"status": "ok", "message": "Добавлено в избранное", "is_favorite": True}


@router.delete("/{material_id}/favorite")
async def remove_from_favorites(
    material_id: int,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Удалить материал из избранного"""
    from app.models.library_models import LibraryFavorite
    from app.api.websocket import broadcast_new_activity
    
    # Получаем материал для данных
    material = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    ).scalar_one_or_none()
    
    category_icon = "📄"
    material_title = "Материал"
    if material:
        material_title = material.title
        if material.category:
            category_icon = material.category.icon or "📄"
    
    favorite = db.execute(
        select(LibraryFavorite).where(
            LibraryFavorite.user_id == current_user["user_id"],
            LibraryFavorite.material_id == material_id
        )
    ).scalar_one_or_none()
    
    if favorite:
        db.delete(favorite)
        
        # Логируем удаление
        db.execute(
            text("INSERT INTO activity_log (user_id, action_type, material_id) VALUES (:user_id, 'favorite_remove', :material_id)"),
            {"user_id": current_user["user_id"], "material_id": material_id}
        )
        
        db.commit()
        
        # Отправляем событие через WebSocket
        activity_data = {
            "type": "favorite_remove",
            "created_at": datetime.now().isoformat(),
            "user": {
                "telegram_id": current_user["telegram_id"],
                "first_name": current_user["first_name"],
                "username": current_user.get("username"),
                "photo_url": current_user.get("photo_url")
            },
            "material": {
                "id": material_id,
                "title": material_title,
                "icon": category_icon
            }
        }
        asyncio.create_task(broadcast_new_activity(activity_data))
    
    return {"status": "ok", "message": "Удалено из избранного", "is_favorite": False}


@router.get("/history/my", response_model=List[MaterialListItem])
def get_my_history(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Получить историю просмотров (уникальные материалы)"""
    # Берём последние уникальные просмотры
    from sqlalchemy import distinct, desc
    
    # Подзапрос для последнего просмотра каждого материала
    subq = db.execute(
        select(
            LibraryView.material_id,
            func.max(LibraryView.viewed_at).label('last_viewed')
        )
        .where(LibraryView.user_id == current_user["user_id"])
        .group_by(LibraryView.material_id)
        .order_by(desc('last_viewed'))
        .limit(limit)
    ).all()
    
    material_ids = [row[0] for row in subq]
    
    if not material_ids:
        return []
    
    materials = db.execute(
        select(LibraryMaterial)
        .where(
            LibraryMaterial.id.in_(material_ids),
            LibraryMaterial.is_published == True
        )
    ).scalars().all()
    
    # Сортируем по порядку просмотров
    materials_dict = {m.id: m for m in materials}
    result = [materials_dict[mid] for mid in material_ids if mid in materials_dict]
    
    # Оптимизация: добавляем cover_url, убираем base64
    return [add_cover_url(m.to_dict()) for m in result]


@router.get("/stats/my")
def get_my_stats(
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Получить статистику пользователя"""
    from app.models.library_models import LibraryFavorite
    
    # Уникальные просмотренные материалы (для прогресса "Изучено")
    unique_viewed = db.execute(
        select(func.count(distinct(LibraryView.material_id)))
        .where(LibraryView.user_id == current_user["user_id"])
    ).scalar() or 0
    
    # Общее количество просмотров (все, включая повторные)
    total_views = db.execute(
        select(func.count(LibraryView.id))
        .where(LibraryView.user_id == current_user["user_id"])
    ).scalar() or 0
    
    # Количество избранных
    favorites_count = db.execute(
        select(func.count(LibraryFavorite.id))
        .where(LibraryFavorite.user_id == current_user["user_id"])
    ).scalar() or 0
    
    # Общее количество материалов
    total_materials = db.execute(
        select(func.count(LibraryMaterial.id))
        .where(LibraryMaterial.is_published == True)
    ).scalar() or 0
    
    return {
        "materials_viewed": total_views,
        "unique_viewed": unique_viewed,
        "favorites": favorites_count,
        "total_materials": total_materials
    }


# ============== ADMIN ENDPOINTS ==============

def check_admin(current_user: dict):
    """Проверка что пользователь админ"""
    if current_user["telegram_id"] not in ADMIN_IDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещён"
        )


@router.post("", response_model=Material)
def create_material(
    data: MaterialCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Создать материал (только для админов)"""
    check_admin(current_user)
    
    # Определяем category_ids (новый формат) или category_id (старый)
    category_ids = data.category_ids or []
    if not category_ids and data.category_id:
        category_ids = [data.category_id]  # Обратная совместимость
    
    material = LibraryMaterial(
        title=data.title,
        description=data.description,
        external_url=data.external_url,
        content=data.content,
        category_id=category_ids[0] if category_ids else None,  # Deprecated, для совместимости
        format=data.format,
        cover_image=data.cover_image,
        is_published=data.is_published,
        is_featured=data.is_featured
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    
    # Добавляем категории через связь many-to-many
    if category_ids:
        categories = db.execute(
            select(LibraryCategory).where(LibraryCategory.id.in_(category_ids))
        ).scalars().all()
        material.categories = list(categories)
        db.commit()
        db.refresh(material)
    
    # Логируем действие и рассылаем через WebSocket
    log_admin_action(db, current_user, 'create', 'material', material.id, material.title, background_tasks)
    
    # Push при создании с публикацией
    if material.is_published:
        try:
            send_push_notification_sync(db, '🆕 ' + material.title[:40], 'Новый материал в библиотеке!', '/library')
        except:
            pass
    
    return material.to_dict(include_content=True)


@router.put("/{material_id}", response_model=Material)
def update_material(
    material_id: int,
    data: MaterialUpdate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Обновить материал (только для админов)"""
    check_admin(current_user)
    
    material = db.execute(
        select(LibraryMaterial)
        .options(selectinload(LibraryMaterial.categories))
        .where(LibraryMaterial.id == material_id)
    ).scalar_one_or_none()
    
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    # Определяем тип действия
    update_data = data.model_dump(exclude_unset=True)
    old_published = material.is_published
    
    print(f"🔄 UPDATE material {material_id}")
    print(f"   Raw data: {update_data}")
    
    # Обрабатываем category_ids отдельно
    category_ids = update_data.pop('category_ids', None)
    print(f"   category_ids: {category_ids}")
    
    # Обновляем обычные поля
    for field, value in update_data.items():
        if field != 'category_id':  # Игнорируем старое поле
            setattr(material, field, value)
    
    # Обновляем категории если переданы
    if category_ids is not None:
        print(f"   Updating categories to: {category_ids}")
        categories = db.execute(
            select(LibraryCategory).where(LibraryCategory.id.in_(category_ids))
        ).scalars().all()
        print(f"   Found categories: {[c.id for c in categories]}")
        material.categories = list(categories)
        # Также обновляем deprecated category_id
        material.category_id = category_ids[0] if category_ids else None
        print(f"   Set category_id to: {material.category_id}")
    else:
        print(f"   category_ids is None, not updating categories")
    
    db.commit()
    
    # Перезагружаем материал с eager loading
    material = db.execute(
        select(LibraryMaterial)
        .options(selectinload(LibraryMaterial.categories))
        .where(LibraryMaterial.id == material_id)
    ).scalar_one()
    print(f"   After reload - categories: {[c.id for c in material.categories]}")
    
    # Логируем действие
    if 'is_published' in update_data and update_data['is_published'] != old_published:
        action = 'publish' if material.is_published else 'unpublish'
    else:
        action = 'edit'
    log_admin_action(db, current_user, action, 'material', material.id, material.title, background_tasks)
    
    return material.to_dict(include_content=True)


@router.delete("/{material_id}")
def delete_material(
    material_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Удалить материал (только для админов)"""
    check_admin(current_user)
    
    material = db.execute(
        select(LibraryMaterial).where(LibraryMaterial.id == material_id)
    ).scalar_one_or_none()
    
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    # Сохраняем данные для лога перед удалением
    material_title = material.title
    material_id_for_log = material.id
    
    db.delete(material)
    
    # Логируем действие
    log_admin_action(db, current_user, 'delete', 'material', material_id_for_log, material_title, background_tasks)
    
    return {"status": "ok", "message": "Материал удалён"}


# ============== УВЕДОМЛЕНИЯ ==============

@router.get("/notifications/my")
def get_my_notifications(
    limit: int = Query(20, ge=1, le=50),
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Получить уведомления пользователя"""
    from sqlalchemy import text
    
    user_id = current_user["user_id"]
    
    # Проверяем, есть ли welcome-уведомление
    has_welcome = db.execute(
        text("SELECT 1 FROM library_notifications WHERE user_id = :user_id AND type = 'welcome' LIMIT 1"),
        {"user_id": user_id}
    ).fetchone()
    
    # Если нет — создаём приветственное уведомление
    if not has_welcome:
        db.execute(
            text("""
            INSERT INTO library_notifications (user_id, type, title, text, is_read)
            VALUES (:user_id, 'welcome', '👋 Добро пожаловать в библиотеку!', 'Рады видеть тебя! Здесь ты найдёшь эксклюзивные идеи для Reels, гайды и стратегии роста.', 0)
            """),
            {"user_id": user_id}
        )
        db.commit()
    
    notifications = db.execute(
        text("""
        SELECT id, type, title, text, link, is_read, created_at
        FROM library_notifications
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
        """),
        {"user_id": user_id, "limit": limit}
    ).fetchall()
    
    result = []
    for n in notifications:
        result.append({
            "id": n[0],
            "type": n[1],
            "title": n[2],
            "text": n[3],
            "external_url": n[4],
            "is_read": bool(n[5]),
            "created_at": n[6]
        })
    
    # Количество непрочитанных
    unread_count = db.execute(
        text("SELECT COUNT(*) FROM library_notifications WHERE user_id = :user_id AND is_read = 0"),
        {"user_id": current_user["user_id"]}
    ).scalar() or 0
    
    return {"notifications": result, "unread_count": unread_count}


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Отметить уведомление как прочитанное"""
    from sqlalchemy import text
    
    db.execute(
        text("UPDATE library_notifications SET is_read = 1 WHERE id = :id AND user_id = :user_id"),
        {"id": notification_id, "user_id": current_user["user_id"]}
    )
    db.commit()
    
    return {"status": "ok"}


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user_with_subscription),
    db: Session = Depends(get_db)
):
    """Отметить все уведомления как прочитанные"""
    from sqlalchemy import text
    
    db.execute(
        text("UPDATE library_notifications SET is_read = 1 WHERE user_id = :user_id"),
        {"user_id": current_user["user_id"]}
    )
    db.commit()
    
    return {"status": "ok"}


@router.get("/feed/recommendations")
def get_recommendations(
    limit: int = 6,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Персональные рекомендации на основе просмотров пользователя.
    Логика: категории просмотренных → похожие материалы которые не смотрел.
    """
    user_id = current_user["user_id"]
    
    # 1. Получаем категории материалов которые пользователь смотрел
    viewed_categories = db.execute(text("""
        SELECT DISTINCT m.category_id 
        FROM library_views v
        JOIN library_materials m ON m.id = v.material_id
        WHERE v.user_id = :user_id AND m.category_id IS NOT NULL
    """), {"user_id": user_id}).fetchall()
    
    category_ids = [c[0] for c in viewed_categories]
    
    # 2. Получаем ID материалов которые пользователь уже смотрел
    viewed_materials = db.execute(text("""
        SELECT DISTINCT material_id FROM library_views WHERE user_id = :user_id
    """), {"user_id": user_id}).fetchall()
    
    viewed_ids = [m[0] for m in viewed_materials]
    
    # 3. Если нет истории - возвращаем популярные
    if not category_ids:
        popular = db.execute(text("""
            SELECT m.id, m.title, m.description, m.cover_image, c.icon, m.external_url, m.category_id, c.name as category_name,
                   (SELECT COUNT(*) FROM library_views WHERE material_id = m.id) as views_count
            FROM library_materials m
            LEFT JOIN library_categories c ON c.id = m.category_id
            WHERE m.is_published = 1
            ORDER BY views_count DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        
        # Оптимизация: добавляем cover_url, убираем base64
        materials_list = [
            add_cover_url({"id": r[0], "title": r[1], "description": r[2], "cover_image": r[3], "icon": r[4], "external_url": r[5], 
             "category_id": r[6], "category_name": r[7], "views": r[8]}) for r in popular
        ]
        return {
            "type": "popular",
            "title": "Популярное",
            "materials": materials_list
        }
    
    # 4. Ищем материалы из тех же категорий, которые пользователь НЕ смотрел
    placeholders = ",".join([f":cat{i}" for i in range(len(category_ids))])
    viewed_placeholders = ",".join([f":viewed{i}" for i in range(len(viewed_ids))]) if viewed_ids else "0"
    
    params = {f"cat{i}": cid for i, cid in enumerate(category_ids)}
    params.update({f"viewed{i}": vid for i, vid in enumerate(viewed_ids)})
    params["limit"] = limit
    
    query = f"""
        SELECT m.id, m.title, m.description, m.cover_image, c.icon, m.external_url, m.category_id, c.name as category_name,
               (SELECT COUNT(*) FROM library_views WHERE material_id = m.id) as views_count
        FROM library_materials m
        LEFT JOIN library_categories c ON c.id = m.category_id
        WHERE m.is_published = 1
          AND m.category_id IN ({placeholders})
          AND m.id NOT IN ({viewed_placeholders})
        ORDER BY views_count DESC
        LIMIT :limit
    """
    
    recommendations = db.execute(text(query), params).fetchall()
    
    # 5. Если мало рекомендаций - добавляем популярные
    if len(recommendations) < limit:
        extra_params = {f"viewed{i}": vid for i, vid in enumerate(viewed_ids)} if viewed_ids else {}
        extra_params["limit"] = limit - len(recommendations)
        extra_viewed = ",".join([f":viewed{i}" for i in range(len(viewed_ids))]) if viewed_ids else "0"
        
        extra = db.execute(text(f"""
            SELECT m.id, m.title, m.description, m.cover_image, c.icon, m.external_url, m.category_id, c.name as category_name,
                   (SELECT COUNT(*) FROM library_views WHERE material_id = m.id) as views_count
            FROM library_materials m
            LEFT JOIN library_categories c ON c.id = m.category_id
            WHERE m.is_published = 1 AND m.id NOT IN ({extra_viewed})
            ORDER BY views_count DESC
            LIMIT :limit
        """), extra_params).fetchall()
        
        existing_ids = {r[0] for r in recommendations}
        for r in extra:
            if r[0] not in existing_ids:
                recommendations.append(r)
    
    # Оптимизация: добавляем cover_url, убираем base64
    materials_list = [
        add_cover_url({"id": r[0], "title": r[1], "description": r[2], "cover_image": r[3], "icon": r[4], "external_url": r[5], 
         "category_id": r[6], "category_name": r[7], "views": r[8]}) for r in recommendations[:limit]
    ]
    return {
        "type": "personalized",
        "title": "Вам понравится",
        "materials": materials_list
    }


# ============================================
# ЭНДПОИНТ ДЛЯ ОБЛОЖКИ (оптимизация загрузки)
# ============================================

from fastapi.responses import Response, RedirectResponse
import base64

@router.get("/{material_id}/cover")
def get_material_cover(
    material_id: int,
    db: Session = Depends(get_db)
):
    """
    Получить обложку материала как изображение.
    Возвращает бинарные данные картинки вместо base64.
    Кэшируется браузером на 1 год.
    """
    material = db.query(LibraryMaterial).filter(LibraryMaterial.id == material_id).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    
    if not material.cover_image:
        raise HTTPException(status_code=404, detail="У материала нет обложки")
    
    cover = material.cover_image
    
    # Если это base64 data URL
    if cover.startswith('data:'):
        try:
            # Формат: data:image/jpeg;base64,/9j/4AAQ...
            header, data = cover.split(',', 1)
            mime_type = header.split(':')[1].split(';')[0]
            image_data = base64.b64decode(data)
            return Response(
                content=image_data, 
                media_type=mime_type,
                headers={"Cache-Control": "public, max-age=31536000"}  # Кэш на 1 год
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка обработки изображения: {str(e)}")
    
    # Если это внешний URL — делаем редирект
    if cover.startswith('http://') or cover.startswith('https://'):
        return RedirectResponse(url=cover, status_code=302)
    
    # Неизвестный формат
    raise HTTPException(status_code=400, detail="Неподдерживаемый формат обложки")
