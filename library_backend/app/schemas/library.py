"""
Pydantic схемы для библиотеки
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================
# КАТЕГОРИИ
# ============================================

class CategoryBase(BaseModel):
    """Базовая схема категории"""
    name: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = None
    position: int = 0


class CategoryCreate(CategoryBase):
    """Создание категории"""
    pass


class CategoryUpdate(BaseModel):
    """Обновление категории"""
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    position: Optional[int] = None


class Category(CategoryBase):
    """Категория (ответ)"""
    id: int
    created_at: datetime
    materials_count: int = 0
    
    class Config:
        from_attributes = True


# ============================================
# ТЕГИ
# ============================================

class TagBase(BaseModel):
    """Базовая схема тега"""
    name: str
    slug: str
    category: Optional[str] = None  # 'format', 'niche', 'topic', 'trend'


class TagCreate(TagBase):
    """Создание тега"""
    pass


class Tag(TagBase):
    """Тег (ответ)"""
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============================================
# ВЛОЖЕНИЯ
# ============================================

class AttachmentBase(BaseModel):
    """Базовая схема вложения"""
    type: str  # 'pdf', 'video', 'image', 'link', 'audio'
    url: str
    title: Optional[str] = None
    file_size: Optional[int] = None


class AttachmentCreate(AttachmentBase):
    """Создание вложения"""
    material_id: int


class Attachment(AttachmentBase):
    """Вложение (ответ)"""
    id: int
    material_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============================================
# МАТЕРИАЛЫ
# ============================================

class MaterialBase(BaseModel):
    """Базовая схема материала"""
    title: str
    description: Optional[str] = None
    content: Optional[str] = None
    external_url: Optional[str] = None  # Ссылка на Notion/Telegram/YouTube
    category_id: Optional[int] = None  # Deprecated, используй category_ids
    category_ids: Optional[List[int]] = []  # Новое: массив ID категорий
    format: str  # 'reels', 'post', 'story', 'guide', 'podcast', 'challenge', 'template'
    level: Optional[str] = None  # 'beginner', 'intermediate', 'advanced'
    duration: Optional[int] = None
    topic: Optional[str] = None
    niche: Optional[str] = None
    viral_score: Optional[int] = Field(None, ge=1, le=10)
    author: Optional[str] = None
    cover_image: Optional[str] = None
    is_published: bool = True
    is_featured: bool = False


class MaterialCreate(MaterialBase):
    """Создание материала"""
    tag_ids: Optional[List[int]] = []


class MaterialUpdate(BaseModel):
    """Обновление материала"""
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    external_url: Optional[str] = None
    category_id: Optional[int] = None  # Deprecated
    category_ids: Optional[List[int]] = None  # Новое: массив ID категорий
    format: Optional[str] = None
    level: Optional[str] = None
    duration: Optional[int] = None
    topic: Optional[str] = None
    niche: Optional[str] = None
    viral_score: Optional[int] = Field(None, ge=1, le=10)
    author: Optional[str] = None
    cover_image: Optional[str] = None
    is_published: Optional[bool] = None
    is_featured: Optional[bool] = None
    tag_ids: Optional[List[int]] = None


class MaterialListItem(BaseModel):
    """Материал в списке (краткая информация)"""
    id: int
    title: str
    description: Optional[str] = None
    external_url: Optional[str] = None
    category_id: Optional[int] = None  # Deprecated
    category: Optional[Category] = None  # Deprecated, первая категория
    category_ids: List[int] = []  # Новое: массив ID категорий
    categories: List[Category] = []  # Новое: массив категорий
    format: str
    level: Optional[str] = None
    duration: Optional[int] = None
    viral_score: Optional[int] = None
    cover_image: Optional[str] = None
    cover_url: Optional[str] = None  # URL для оптимизированной загрузки обложки
    is_featured: bool
    is_published: bool = True
    views: int
    created_at: datetime
    tags: List[Tag] = []
    favorites_count: int = 0  # Количество лайков
    
    class Config:
        from_attributes = True


class Material(MaterialListItem):
    """Материал (полная информация)"""
    content: Optional[str] = None
    topic: Optional[str] = None
    niche: Optional[str] = None
    author: Optional[str] = None
    is_published: bool
    updated_at: datetime
    attachments: List[Attachment] = []
    favorites_count: int = 0
    
    class Config:
        from_attributes = True


# ============================================
# ИЗБРАННОЕ
# ============================================

class FavoriteCreate(BaseModel):
    """Добавление в избранное"""
    material_id: int


class Favorite(BaseModel):
    """Избранное (ответ)"""
    id: int
    user_id: int
    material_id: int
    created_at: datetime
    material: Optional[MaterialListItem] = None
    
    class Config:
        from_attributes = True


# ============================================
# ПРОСМОТРЫ
# ============================================

class ViewCreate(BaseModel):
    """Запись просмотра"""
    material_id: int
    duration_seconds: Optional[int] = None


class View(BaseModel):
    """Просмотр (ответ)"""
    id: int
    material_id: int
    user_id: int
    viewed_at: datetime
    duration_seconds: Optional[int] = None
    
    class Config:
        from_attributes = True


# ============================================
# ФИЛЬТРЫ И ПАГИНАЦИЯ
# ============================================

class MaterialFilters(BaseModel):
    """Фильтры для материалов"""
    search: Optional[str] = None
    category_id: Optional[int] = None
    format: Optional[str] = None
    level: Optional[str] = None
    topic: Optional[str] = None
    niche: Optional[str] = None
    is_featured: Optional[bool] = None
    tag_ids: Optional[List[int]] = None


class PaginatedResponse(BaseModel):
    """Пагинированный ответ"""
    items: List[MaterialListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
