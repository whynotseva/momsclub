"""
Миграция для удаления таблицы admin_action_logs
Удаляет таблицу и все связанные индексы
"""
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

def drop_admin_action_logs_table(db_path="momsclub.db"):
    """
    Удаляет таблицу admin_action_logs и все связанные индексы
    """
    if not os.path.exists(db_path):
        logger.warning(f"База данных {db_path} не найдена")
        print(f"⚠️ База данных {db_path} не найдена")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли таблица
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='admin_action_logs'
        """)
        table_exists = cursor.fetchone()
        
        if not table_exists:
            logger.info("Таблица admin_action_logs не существует, удаление не требуется")
            print("ℹ️ Таблица admin_action_logs не существует, удаление не требуется")
            return
        
        # Получаем количество записей перед удалением
        cursor.execute("SELECT COUNT(*) FROM admin_action_logs")
        count = cursor.fetchone()[0]
        logger.info(f"Найдено {count} записей в таблице admin_action_logs")
        print(f"📊 Найдено {count} записей в таблице admin_action_logs")
        
        # Удаляем индексы
        indexes = [
            "idx_admin_action_logs_admin_telegram_id",
            "idx_admin_action_logs_target_telegram_id",
            "idx_admin_action_logs_action_type",
            "idx_admin_action_logs_created_at"
        ]
        
        for index_name in indexes:
            try:
                cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
                logger.info(f"Индекс {index_name} удален")
            except Exception as e:
                logger.warning(f"Не удалось удалить индекс {index_name}: {e}")
        
        # Удаляем таблицу
        cursor.execute("DROP TABLE IF EXISTS admin_action_logs")
        
        conn.commit()
        logger.info("✅ Таблица admin_action_logs успешно удалена")
        print("✅ Таблица admin_action_logs успешно удалена")
        if count > 0:
            print(f"⚠️ Удалено {count} записей (данные потеряны)")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Ошибка при удалении таблицы admin_action_logs: {e}")
        print(f"❌ Ошибка при удалении таблицы admin_action_logs: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    drop_admin_action_logs_table()

