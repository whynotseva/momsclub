#!/usr/bin/env python3
"""
Миграция для исправления Primary Key в таблице users
"""
import sqlite3
import os
from datetime import datetime
import shutil

def migrate():
    """Исправляет Primary Key в таблице users"""
    
    db_path = "momsclub.db"
    
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        return False
    
    # Создаем резервную копию
    backup_path = f"momsclub.db.backup_pk_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(db_path, backup_path)
    print(f"✅ Резервная копия создана: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем текущую структуру
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        print("\n🔄 Исправляем Primary Key в таблице users...")
        print("⚠️  ВНИМАНИЕ: Это критическая операция!")
        
        # Не можем изменить PRIMARY KEY напрямую в SQLite
        # Нужно пересоздать таблицу
        
        # Создаем временную таблицу с правильной структурой
        cursor.execute("""
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                is_active INTEGER DEFAULT 1,
                referrer_id INTEGER,
                referral_code TEXT UNIQUE,
                welcome_sent INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                birthday TEXT,
                birthday_gift_year INTEGER,
                yookassa_payment_method_id TEXT,
                is_recurring_active INTEGER DEFAULT 0,
                phone TEXT,
                email TEXT,
                reminder_sent INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                is_first_payment_done INTEGER DEFAULT 0
            )
        """)
        
        # Копируем данные
        cursor.execute("""
            INSERT INTO users_new SELECT * FROM users
        """)
        
        # Удаляем старую таблицу
        cursor.execute("DROP TABLE users")
        
        # Переименовываем новую таблицу
        cursor.execute("ALTER TABLE users_new RENAME TO users")
        
        conn.commit()
        print("✅ Primary Key исправлен!")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(users)")
        pk_info = cursor.fetchall()
        pk_columns = [col for col in pk_info if col[5] == 1]
        
        if len(pk_columns) == 1 and pk_columns[0][1] == 'id':
            print("\n✅ Миграция успешно завершена!")
            return True
        else:
            print("\n❌ Primary Key не установлен!")
            return False
            
    except Exception as e:
        print(f"\n❌ Ошибка миграции: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 70)
    print("🔧 МИГРАЦИЯ: Исправление Primary Key")
    print("=" * 70)
    
    success = migrate()
    
    if success:
        print("\n✅ Миграция завершена успешно!")
    else:
        print("\n❌ Миграция не удалась!")

