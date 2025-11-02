"""
Миграция для добавления колонки email в таблицу users
"""

import sqlite3
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

def run_migration():
    """Выполняет миграцию для добавления колонки email"""
    
    # Путь к базе данных
    db_path = Path(__file__).parent.parent.parent / "momsclub.db"
    
    if not db_path.exists():
        logger.error(f"База данных не найдена: {db_path}")
        return False
    
    try:
        # Подключаемся к базе данных
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже колонка email
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'email' in columns:
            logger.info("Колонка 'email' уже существует в таблице users")
            conn.close()
            return True
        
        # Добавляем колонку email
        logger.info("Добавляем колонку 'email' в таблицу users...")
        cursor.execute("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
        
        # Подтверждаем изменения
        conn.commit()
        logger.info("Колонка 'email' успешно добавлена")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(users)")
        columns_after = [column[1] for column in cursor.fetchall()]
        
        if 'email' in columns_after:
            logger.info("Миграция выполнена успешно")
            result = True
        else:
            logger.error("Ошибка: колонка 'email' не была добавлена")
            result = False
            
        conn.close()
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении миграции: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    success = run_migration()
    if success:
        print("✅ Миграция выполнена успешно")
    else:
        print("❌ Ошибка при выполнении миграции")
