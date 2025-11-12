"""
Миграция для добавления поля admin_group в таблицу users
"""
import asyncio
from sqlalchemy import text
from database.config import AsyncSessionLocal
import logging

logger = logging.getLogger(__name__)

async def migrate():
    """Добавляет поле admin_group в таблицу users"""
    logger.info("Начало миграции: добавление поля admin_group")
    
    async with AsyncSessionLocal() as session:
        try:
            # Проверяем, существует ли уже поле admin_group
            check_query = text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('users') 
                WHERE name = 'admin_group'
            """)
            result = await session.execute(check_query)
            count = result.scalar()
            
            if count > 0:
                logger.info("Поле admin_group уже существует, миграция не требуется")
                return
            
            # Добавляем поле admin_group
            alter_query = text("""
                ALTER TABLE users 
                ADD COLUMN admin_group VARCHAR(50) NULL
            """)
            
            await session.execute(alter_query)
            await session.commit()
            
            logger.info("✅ Миграция успешно выполнена: поле admin_group добавлено")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении миграции: {e}")
            await session.rollback()
            raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate())

