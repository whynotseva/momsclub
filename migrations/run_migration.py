"""
Скрипт для выполнения миграции: добавление таблицы group_activity_log
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.config import engine, Base
from database.models import GroupActivityLog
from sqlalchemy import text


async def run_migration():
    """Выполняет миграцию для добавления таблицы group_activity_log"""
    
    print("🔄 Начинаем миграцию...")
    
    async with engine.begin() as conn:
        # Проверяем, существует ли таблица (SQLite синтаксис)
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='group_activity_log'"
        ))
        table_exists = result.scalar()
        
        if table_exists:
            print("✅ Таблица group_activity_log уже существует")
            return
        
        print("📝 Создаём таблицу group_activity_log...")
        
        # Создаём таблицу через SQLAlchemy
        await conn.run_sync(Base.metadata.create_all, tables=[GroupActivityLog.__table__])
        
        print("✅ Таблица group_activity_log успешно создана")
        print("✅ Индексы созданы автоматически")
    
    print("🎉 Миграция завершена успешно!")


if __name__ == "__main__":
    asyncio.run(run_migration())
