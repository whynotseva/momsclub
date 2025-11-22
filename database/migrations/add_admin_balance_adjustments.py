"""
Миграция: Добавление таблицы admin_balance_adjustments
Для логирования ручных начислений/списаний баланса админом
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
from sqlalchemy import text
from database.config import AsyncSessionLocal, engine
from database.models import Base, AdminBalanceAdjustment
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upgrade():
    """Применить миграцию"""
    async with engine.begin() as conn:
        # Проверяем, существует ли таблица
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_balance_adjustments'")
        )
        if result.fetchone():
            logger.info("Таблица admin_balance_adjustments уже существует, пропускаем")
            return
        
        logger.info("Создаём таблицу admin_balance_adjustments...")
        
        # Создаём таблицу
        await conn.run_sync(Base.metadata.tables['admin_balance_adjustments'].create)
        
        logger.info("✅ Таблица admin_balance_adjustments создана")


async def downgrade():
    """Откатить миграцию"""
    async with engine.begin() as conn:
        logger.info("Удаляем таблицу admin_balance_adjustments...")
        await conn.execute(text("DROP TABLE IF EXISTS admin_balance_adjustments"))
        logger.info("✅ Таблица admin_balance_adjustments удалена")


async def main():
    """Точка входа"""
    logger.info("=" * 60)
    logger.info("МИГРАЦИЯ: Добавление таблицы admin_balance_adjustments")
    logger.info("=" * 60)
    
    await upgrade()
    
    logger.info("=" * 60)
    logger.info("МИГРАЦИЯ ЗАВЕРШЕНА")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
