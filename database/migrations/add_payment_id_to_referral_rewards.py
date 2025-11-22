"""
Миграция: Добавление поля payment_id в таблицу referral_rewards
Необходимо для отслеживания наград за конкретные платежи (Реферальная система 3.0)
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
from sqlalchemy import text
from database.config import AsyncSessionLocal, engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def upgrade():
    """Применить миграцию"""
    async with engine.begin() as conn:
        # Проверяем, существует ли поле
        result = await conn.execute(
            text("PRAGMA table_info(referral_rewards)")
        )
        columns = [row[1] for row in result.fetchall()]
        
        if 'payment_id' in columns:
            logger.info("Поле payment_id уже существует, пропускаем")
            return
        
        logger.info("Добавляем поле payment_id в таблицу referral_rewards...")
        
        # Добавляем колонку payment_id
        await conn.execute(text(
            "ALTER TABLE referral_rewards ADD COLUMN payment_id INTEGER"
        ))
        
        logger.info("✅ Поле payment_id добавлено")


async def downgrade():
    """Откатить миграцию"""
    async with engine.begin() as conn:
        logger.info("⚠️ SQLite не поддерживает DROP COLUMN. Нужно пересоздать таблицу.")
        logger.info("Откат миграции не поддерживается.")


async def main():
    """Точка входа"""
    logger.info("=" * 60)
    logger.info("МИГРАЦИЯ: Добавление payment_id в referral_rewards")
    logger.info("=" * 60)
    
    await upgrade()
    
    logger.info("=" * 60)
    logger.info("МИГРАЦИЯ ЗАВЕРШЕНА")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
