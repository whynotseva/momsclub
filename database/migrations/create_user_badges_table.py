"""
Миграция для создания таблицы user_badges (достижения пользователей)
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)

def create_user_badges_table(db_path="momsclub.db"):
    """
    Создает таблицу user_badges для хранения достижений пользователей
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Создаем таблицу user_badges
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                badge_type VARCHAR(50) NOT NULL,
                earned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, badge_type)
            )
        """)
        
        # Создаем индекс для быстрого поиска badges пользователя
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_badges_user_id 
            ON user_badges(user_id)
        """)
        
        # Создаем индекс для быстрого поиска по типу badge
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_badges_type 
            ON user_badges(badge_type)
        """)
        
        conn.commit()
        logger.info("✅ Таблица user_badges создана успешно")
        print("✅ Таблица user_badges создана успешно")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Ошибка при создании таблицы user_badges: {e}")
        print(f"❌ Ошибка при создании таблицы user_badges: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    create_user_badges_table()

