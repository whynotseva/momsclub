"""
Миграция для добавления полей персональных промокодов в таблицу promo_codes
Добавляет поля: user_id, is_personal, auto_generated
"""
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

def add_personal_promo_fields(db_path="momsclub.db"):
    """
    Добавляет поля для персональных промокодов в таблицу promo_codes
    """
    if not os.path.exists(db_path):
        logger.warning(f"База данных {db_path} не найдена")
        print(f"⚠️ База данных {db_path} не найдена")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существуют ли уже поля
        cursor.execute("PRAGMA table_info(promo_codes)")
        columns = [column[1] for column in cursor.fetchall()]
        
        changes_made = False
        
        # Добавляем поле user_id (привязка к пользователю)
        if 'user_id' not in columns:
            cursor.execute("""
                ALTER TABLE promo_codes 
                ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
            """)
            logger.info("Добавлено поле user_id в таблицу promo_codes")
            print("✅ Добавлено поле user_id")
            changes_made = True
        else:
            logger.info("Поле user_id уже существует")
            print("ℹ️ Поле user_id уже существует")
        
        # Добавляем поле is_personal (флаг персонального промокода)
        if 'is_personal' not in columns:
            cursor.execute("""
                ALTER TABLE promo_codes 
                ADD COLUMN is_personal BOOLEAN DEFAULT 0
            """)
            logger.info("Добавлено поле is_personal в таблицу promo_codes")
            print("✅ Добавлено поле is_personal")
            changes_made = True
        else:
            logger.info("Поле is_personal уже существует")
            print("ℹ️ Поле is_personal уже существует")
        
        # Добавляем поле auto_generated (флаг автоматической генерации)
        if 'auto_generated' not in columns:
            cursor.execute("""
                ALTER TABLE promo_codes 
                ADD COLUMN auto_generated BOOLEAN DEFAULT 0
            """)
            logger.info("Добавлено поле auto_generated в таблицу promo_codes")
            print("✅ Добавлено поле auto_generated")
            changes_made = True
        else:
            logger.info("Поле auto_generated уже существует")
            print("ℹ️ Поле auto_generated уже существует")
        
        # Создаем индекс для быстрого поиска персональных промокодов по user_id
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_promo_codes_user_id 
                ON promo_codes(user_id)
            """)
            logger.info("Создан индекс idx_promo_codes_user_id")
            print("✅ Создан индекс для user_id")
        except Exception as e:
            logger.warning(f"Не удалось создать индекс: {e}")
            print(f"⚠️ Не удалось создать индекс: {e}")
        
        conn.commit()
        
        if changes_made:
            logger.info("✅ Миграция add_personal_promo_fields выполнена успешно")
            print("✅ Миграция выполнена успешно")
        else:
            logger.info("ℹ️ Все поля уже существуют, миграция не требуется")
            print("ℹ️ Все поля уже существуют, миграция не требуется")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Ошибка при выполнении миграции add_personal_promo_fields: {e}")
        print(f"❌ Ошибка при выполнении миграции: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    add_personal_promo_fields()

