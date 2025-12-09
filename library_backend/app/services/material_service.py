"""
Сервис для работы с материалами библиотеки.
Содержит бизнес-логику, отделённую от роутов API.
"""

import logging
from typing import List, Optional, Dict, Any
from math import ceil
from datetime import datetime

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, or_, text

from app.models.library_models import (
    LibraryMaterial, LibraryCategory, LibraryView, 
    LibraryFavorite, AdminActivityLog
)

# Логгер
logger = logging.getLogger(__name__)

# Константы
ADMIN_IDS = [534740911, 44054166]  # Полина и Всеволод
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


def check_admin(user: dict) -> bool:
    """Проверка что пользователь админ"""
    return user.get("telegram_id") in ADMIN_IDS


class MaterialService:
    """Сервис для работы с материалами"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_materials(
        self,
        search: Optional[str] = None,
        category_id: Optional[int] = None,
        format: Optional[str] = None,
        level: Optional[str] = None,
        topic: Optional[str] = None,
        niche: Optional[str] = None,
        is_featured: Optional[bool] = None,
        include_drafts: bool = False,
        is_admin: bool = False,
        page: int = 1,
        page_size: int = 10000,
        sort: str = "created_desc"
    ) -> Dict[str, Any]:
        """
        Получить список материалов с фильтрацией и пагинацией.
        
        Returns:
            dict с items, total, page, page_size, total_pages
        """
        # Базовый запрос с eager loading
        query = select(LibraryMaterial).options(
            selectinload(LibraryMaterial.categories),
            selectinload(LibraryMaterial.favorites)
        )
        
        # Фильтр по публикации
        if not (include_drafts and is_admin):
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
        total = self.db.execute(total_query).scalar()
        
        # Сортировка
        sort_map = {
            "created_desc": LibraryMaterial.created_at.desc(),
            "created_asc": LibraryMaterial.created_at.asc(),
            "views_desc": LibraryMaterial.views.desc(),
            "title_asc": LibraryMaterial.title.asc(),
        }
        if sort in sort_map:
            query = query.order_by(sort_map[sort])
        
        # Пагинация
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        # Выполняем запрос
        materials = self.db.execute(query).scalars().all()
        
        # Конвертируем и добавляем cover_url
        items = [add_cover_url(m.to_dict()) for m in materials]
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if total > 0 else 0
        }
    
    def get_material_by_id(self, material_id: int, include_content: bool = True) -> Optional[dict]:
        """Получить материал по ID"""
        material = self.db.execute(
            select(LibraryMaterial)
            .options(selectinload(LibraryMaterial.categories))
            .where(
                LibraryMaterial.id == material_id,
                LibraryMaterial.is_published == True
            )
        ).scalar_one_or_none()
        
        if not material:
            return None
        
        return material.to_dict(include_content=include_content)
    
    def record_view(self, material_id: int, user_id: int, duration_seconds: Optional[int] = None) -> bool:
        """Записать просмотр материала"""
        material = self.db.execute(
            select(LibraryMaterial).where(LibraryMaterial.id == material_id)
        ).scalar_one_or_none()
        
        if not material:
            logger.warning(f"Material {material_id} not found for view recording")
            return False
        
        # Создаём запись просмотра
        view = LibraryView(
            material_id=material_id,
            user_id=user_id,
            duration_seconds=duration_seconds
        )
        self.db.add(view)
        
        # Увеличиваем счётчик
        material.views += 1
        
        self.db.commit()
        logger.debug(f"View recorded: material={material_id}, user={user_id}")
        return True
    
    def get_featured(self, limit: int = 10) -> List[dict]:
        """Получить избранные материалы (Выбор Полины)"""
        materials = self.db.execute(
            select(LibraryMaterial)
            .where(
                LibraryMaterial.is_published == True,
                LibraryMaterial.is_featured == True
            )
            .order_by(LibraryMaterial.created_at.desc())
            .limit(limit)
        ).scalars().all()
        
        return [add_cover_url(m.to_dict()) for m in materials]
    
    def get_popular(self, limit: int = 10) -> List[dict]:
        """Получить популярные материалы"""
        materials = self.db.execute(
            select(LibraryMaterial)
            .where(LibraryMaterial.is_published == True)
            .order_by(LibraryMaterial.views.desc())
            .limit(limit)
        ).scalars().all()
        
        return [add_cover_url(m.to_dict()) for m in materials]


def log_admin_action(
    db: Session, 
    user: dict, 
    action: str, 
    entity_type: str,
    entity_id: int = None, 
    entity_title: str = None,
    background_tasks = None
):
    """Записывает действие админа в лог и рассылает через WebSocket"""
    from app.api.websocket import broadcast_admin_action
    
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
    
    logger.info(f"Admin action: {admin_name} {action} {entity_type} #{entity_id} '{entity_title}'")
    
    # Рассылаем через WebSocket
    if background_tasks:
        background_tasks.add_task(
            broadcast_admin_action,
            log_entry.to_dict()
        )
