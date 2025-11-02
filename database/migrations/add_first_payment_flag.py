#!/usr/bin/env python3
"""
Миграция для добавления поля is_first_payment_done в таблицу users
"""
import sqlite3
import os
from datetime import datetime

def migrate():
    """Добавляет поле is_first_payment_done в таблицу users"""
    
    db_path = "momsclub.db"
    
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        return False
    
    # Создаем резервную копию
    backup_path = f"momsclub.db.backup_first_payment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    import shutil
    shutil.copy(db_path, backup_path)
    print(f"✅ Резервная копия создана: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли поле
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "is_first_payment_done" in columns:
            print("ℹ️  Поле is_first_payment_done уже существует")
            return True
        
        # Добавляем новое поле
        print("\n🔄 Добавляем поле is_first_payment_done...")
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN is_first_payment_done BOOLEAN DEFAULT 0
        """)
        
        conn.commit()
        print("✅ Поле is_first_payment_done успешно добавлено")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(users)")
        columns_after = [col[1] for col in cursor.fetchall()]
        
        if "is_first_payment_done" in columns_after:
            print("\n✅ Миграция успешно завершена!")
            return True
        else:
            print("\n❌ Поле не было добавлено!")
            return False
            
    except Exception as e:
        print(f"\n❌ Ошибка миграции: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 70)
    print("🔄 МИГРАЦИЯ: Добавление поля is_first_payment_done")
    print("=" * 70)
    
    success = migrate()
    
    if success:
        print("\n✅ Миграция завершена успешно!")
    else:
        print("\n❌ Миграция не удалась!")

