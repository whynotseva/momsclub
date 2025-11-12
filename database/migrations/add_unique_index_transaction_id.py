"""
Миграция: Добавление UNIQUE индекса на payment_logs.transaction_id
Это обеспечивает идемпотентность обработки вебхуков.
"""
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

def migrate_add_unique_index_transaction_id(db_path="momsclub.db"):
    """
    Добавляет UNIQUE индекс на payment_logs.transaction_id.
    Перед созданием индекса проверяет, нет ли дубликатов.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, нет ли дубликатов transaction_id (кроме NULL)
        cursor.execute("""
            SELECT transaction_id, COUNT(*) as cnt
            FROM payment_logs
            WHERE transaction_id IS NOT NULL
            GROUP BY transaction_id
            HAVING cnt > 1
        """)
        duplicates = cursor.fetchall()
        
        if duplicates:
            logger.warning(f"Найдено {len(duplicates)} дубликатов transaction_id!")
            for tx_id, count in duplicates[:10]:  # Показываем первые 10
                logger.warning(f"  transaction_id={tx_id}, количество: {count}")
            logger.warning("Перед созданием UNIQUE индекса необходимо устранить дубликаты!")
            logger.warning("Можно оставить только самую последнюю запись для каждого transaction_id")
            conn.close()
            return False
        
        # Проверяем, существует ли уже индекс
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' 
            AND name='idx_payment_logs_transaction_id'
        """)
        existing_index = cursor.fetchone()
        
        if existing_index:
            logger.info("Индекс idx_payment_logs_transaction_id уже существует")
            conn.close()
            return True
        
        # Создаем UNIQUE индекс
        logger.info("Создание UNIQUE индекса на payment_logs.transaction_id...")
        cursor.execute("""
            CREATE UNIQUE INDEX idx_payment_logs_transaction_id 
            ON payment_logs(transaction_id) 
            WHERE transaction_id IS NOT NULL
        """)
        
        conn.commit()
        logger.info("✅ UNIQUE индекс успешно создан на payment_logs.transaction_id")
        
        conn.close()
        return True
        
    except sqlite3.OperationalError as e:
        if "UNIQUE constraint failed" in str(e):
            logger.error("Ошибка: обнаружены дубликаты transaction_id. Устраните их перед созданием индекса.")
        else:
            logger.error(f"Ошибка SQLite при создании индекса: {e}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при создании индекса: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Определяем путь к БД
    db_path = os.getenv("DB_PATH", "momsclub.db")
    if not os.path.exists(db_path):
        logger.error(f"База данных не найдена: {db_path}")
        exit(1)
    
    success = migrate_add_unique_index_transaction_id(db_path)
    exit(0 if success else 1)

