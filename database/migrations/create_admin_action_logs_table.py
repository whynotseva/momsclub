"""
Миграция для создания таблицы admin_action_logs
Логирует действия администраторов для аудита
"""
import sqlite3
import logging

logger = logging.getLogger(__name__)

def create_admin_action_logs_table(db_path="momsclub.db"):
    """
    Создает таблицу admin_action_logs для логирования действий администраторов
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Создаем таблицу admin_action_logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                admin_telegram_id INTEGER NOT NULL,
                action_type VARCHAR(100) NOT NULL,
                target_user_id INTEGER,
                target_telegram_id INTEGER,
                details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        
        # Создаем индексы
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_action_logs_admin_telegram_id 
            ON admin_action_logs(admin_telegram_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_action_logs_target_telegram_id 
            ON admin_action_logs(target_telegram_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_action_logs_action_type 
            ON admin_action_logs(action_type)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_action_logs_created_at 
            ON admin_action_logs(created_at)
        """)
        
        conn.commit()
        logger.info("✅ Таблица admin_action_logs создана успешно")
        print("✅ Таблица admin_action_logs создана успешно")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Ошибка при создании таблицы admin_action_logs: {e}")
        print(f"❌ Ошибка при создании таблицы admin_action_logs: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    create_admin_action_logs_table()

