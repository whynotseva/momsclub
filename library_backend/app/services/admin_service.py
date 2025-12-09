"""
Сервис для админ-функций библиотеки.
"""

import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.models.library_models import (
    LibraryMaterial, LibraryCategory, LibraryView, LibraryFavorite
)

logger = logging.getLogger(__name__)


# Список админов
ADMIN_IDS = [534740911, 44054166]


def is_admin(telegram_id: int) -> bool:
    """Проверка что пользователь админ"""
    return telegram_id in ADMIN_IDS


class AdminService:
    """Сервис для админ-функций"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику библиотеки"""
        
        # Количество материалов
        materials_count = self.db.scalar(
            select(func.count(LibraryMaterial.id))
        ) or 0
        
        # Количество опубликованных
        published_count = self.db.scalar(
            select(func.count(LibraryMaterial.id))
            .where(LibraryMaterial.is_published == True)
        ) or 0
        
        # Количество просмотров
        views_count = self.db.scalar(
            select(func.count(LibraryView.id))
        ) or 0
        
        # Количество в избранном
        favorites_count = self.db.scalar(
            select(func.count(LibraryFavorite.id))
        ) or 0
        
        # Количество категорий
        categories_count = self.db.scalar(
            select(func.count(LibraryCategory.id))
        ) or 0
        
        return {
            "materials": {
                "total": materials_count,
                "published": published_count,
                "drafts": materials_count - published_count
            },
            "views_total": views_count,
            "favorites_total": favorites_count,
            "categories_total": categories_count
        }
    
    def get_materials_list(
        self,
        page: int = 1,
        limit: int = 20,
        category_id: int = None,
        is_published: bool = None,
        search: str = None
    ):
        """Получить список материалов для админки"""
        query = select(LibraryMaterial).order_by(LibraryMaterial.created_at.desc())
        
        if category_id:
            query = query.where(LibraryMaterial.category_id == category_id)
        
        if is_published is not None:
            query = query.where(LibraryMaterial.is_published == is_published)
        
        if search:
            query = query.where(LibraryMaterial.title.ilike(f"%{search}%"))
        
        query = query.offset((page - 1) * limit).limit(limit)
        
        result = self.db.execute(query)
        return result.scalars().all()
