"""
Миграция для создания таблицы заявок на отмену автопродления
"""

import sqlite3
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

def run_migration():
    """Выполняет миграцию для создания таблицы autorenewal_cancellation_requests"""
    
    # Путь к базе данных
    db_path = Path(__file__).parent.parent.parent / "momsclub.db"
    
    if not db_path.exists():
        logger.error(f"База данных не найдена: {db_path}")
        return False
    
    try:
        # Подключаемся к базе данных
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже таблица
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='autorenewal_cancellation_requests'
        """)
        
        if cursor.fetchone():
            logger.info("Таблица 'autorenewal_cancellation_requests' уже существует")
            conn.close()
            return True
        
        # Создаем таблицу
        logger.info("Создаем таблицу 'autorenewal_cancellation_requests'...")
        cursor.execute("""
            CREATE TABLE autorenewal_cancellation_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                contacted_at DATETIME,
                reviewed_at DATETIME,
                reviewed_by INTEGER,
                admin_notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        
        # Подтверждаем изменения
        conn.commit()
        logger.info("Таблица 'autorenewal_cancellation_requests' успешно создана")
        
        # Проверяем результат
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='autorenewal_cancellation_requests'
        """)
        
        if cursor.fetchone():
            logger.info("Миграция выполнена успешно")
            result = True
        else:
            logger.error("Ошибка: таблица 'autorenewal_cancellation_requests' не была создана")
            result = False
            
        conn.close()
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении миграции: {e}", exc_info=True)
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

