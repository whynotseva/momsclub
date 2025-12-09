"""
Сервис для персональных рекомендаций материалов.
"""

import logging
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.material_service import add_cover_url

logger = logging.getLogger(__name__)


class RecommendationService:
    """Сервис персональных рекомендаций на основе истории просмотров"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_recommendations(self, user_id: int, limit: int = 6) -> Dict[str, Any]:
        """
        Получить персональные рекомендации.
        
        Логика:
        1. Берём категории просмотренных материалов
        2. Ищем похожие материалы которые пользователь НЕ смотрел
        3. Если мало — добавляем популярные
        
        Returns:
            dict с type, title, materials
        """
        # 1. Получаем категории просмотренных материалов
        viewed_categories = self.db.execute(text("""
            SELECT DISTINCT m.category_id 
            FROM library_views v
            JOIN library_materials m ON m.id = v.material_id
            WHERE v.user_id = :user_id AND m.category_id IS NOT NULL
        """), {"user_id": user_id}).fetchall()
        
        category_ids = [c[0] for c in viewed_categories]
        
        # 2. Получаем ID просмотренных материалов
        viewed_materials = self.db.execute(text("""
            SELECT DISTINCT material_id FROM library_views WHERE user_id = :user_id
        """), {"user_id": user_id}).fetchall()
        
        viewed_ids = [m[0] for m in viewed_materials]
        
        # 3. Если нет истории — возвращаем популярные
        if not category_ids:
            return self._get_popular_recommendations(limit)
        
        # 4. Ищем материалы из тех же категорий, которые НЕ смотрели
        recommendations = self._get_category_recommendations(category_ids, viewed_ids, limit)
        
        # 5. Если мало — добавляем популярные
        if len(recommendations) < limit:
            extra = self._get_extra_popular(viewed_ids, limit - len(recommendations))
            existing_ids = {r["id"] for r in recommendations}
            for item in extra:
                if item["id"] not in existing_ids:
                    recommendations.append(item)
        
        return {
            "type": "personalized",
            "title": "Вам понравится",
            "materials": recommendations[:limit]
        }
    
    def _get_popular_recommendations(self, limit: int) -> Dict[str, Any]:
        """Получить популярные материалы (fallback)"""
        popular = self.db.execute(text("""
            SELECT m.id, m.title, m.description, m.cover_image, c.icon, 
                   m.external_url, m.category_id, c.name as category_name,
                   (SELECT COUNT(*) FROM library_views WHERE material_id = m.id) as views_count
            FROM library_materials m
            LEFT JOIN library_categories c ON c.id = m.category_id
            WHERE m.is_published = 1
            ORDER BY views_count DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
        
        materials = [self._row_to_dict(r) for r in popular]
        
        return {
            "type": "popular",
            "title": "Популярное",
            "materials": materials
        }
    
    def _get_category_recommendations(
        self, 
        category_ids: List[int], 
        viewed_ids: List[int], 
        limit: int
    ) -> List[dict]:
        """Получить рекомендации из тех же категорий"""
        placeholders = ",".join([f":cat{i}" for i in range(len(category_ids))])
        viewed_placeholders = ",".join([f":viewed{i}" for i in range(len(viewed_ids))]) if viewed_ids else "0"
        
        params = {f"cat{i}": cid for i, cid in enumerate(category_ids)}
        params.update({f"viewed{i}": vid for i, vid in enumerate(viewed_ids)})
        params["limit"] = limit
        
        query = f"""
            SELECT m.id, m.title, m.description, m.cover_image, c.icon, 
                   m.external_url, m.category_id, c.name as category_name,
                   (SELECT COUNT(*) FROM library_views WHERE material_id = m.id) as views_count
            FROM library_materials m
            LEFT JOIN library_categories c ON c.id = m.category_id
            WHERE m.is_published = 1
              AND m.category_id IN ({placeholders})
              AND m.id NOT IN ({viewed_placeholders})
            ORDER BY views_count DESC
            LIMIT :limit
        """
        
        results = self.db.execute(text(query), params).fetchall()
        return [self._row_to_dict(r) for r in results]
    
    def _get_extra_popular(self, viewed_ids: List[int], limit: int) -> List[dict]:
        """Получить дополнительные популярные материалы"""
        params = {f"viewed{i}": vid for i, vid in enumerate(viewed_ids)} if viewed_ids else {}
        params["limit"] = limit
        viewed_placeholders = ",".join([f":viewed{i}" for i in range(len(viewed_ids))]) if viewed_ids else "0"
        
        results = self.db.execute(text(f"""
            SELECT m.id, m.title, m.description, m.cover_image, c.icon, 
                   m.external_url, m.category_id, c.name as category_name,
                   (SELECT COUNT(*) FROM library_views WHERE material_id = m.id) as views_count
            FROM library_materials m
            LEFT JOIN library_categories c ON c.id = m.category_id
            WHERE m.is_published = 1 AND m.id NOT IN ({viewed_placeholders})
            ORDER BY views_count DESC
            LIMIT :limit
        """), params).fetchall()
        
        return [self._row_to_dict(r) for r in results]
    
    def _row_to_dict(self, row) -> dict:
        """Конвертировать строку в dict с cover_url"""
        return add_cover_url({
            "id": row[0], 
            "title": row[1], 
            "description": row[2], 
            "cover_image": row[3], 
            "icon": row[4], 
            "external_url": row[5],
            "category_id": row[6], 
            "category_name": row[7], 
            "views": row[8]
        })
