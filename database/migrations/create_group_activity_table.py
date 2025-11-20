"""
Миграция для создания таблицы group_activity
Отслеживает активность пользователей в группе (количество сообщений, последняя активность)
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)

def create_group_activity_table(db_path="momsclub.db"):
    """
    Создает таблицу group_activity для отслеживания активности пользователей в группе
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Создаем таблицу group_activity
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                message_count INTEGER DEFAULT 0,
                last_activity DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Создаем индексы
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_activity_user_id 
            ON group_activity(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_activity_last_activity 
            ON group_activity(last_activity)
        """)
        
        conn.commit()
        logger.info("✅ Таблица group_activity создана успешно")
        print("✅ Таблица group_activity создана успешно")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Ошибка при создании таблицы group_activity: {e}")
        print(f"❌ Ошибка при создании таблицы group_activity: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    create_group_activity_table()

