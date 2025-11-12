"""
Миграция базы данных: Замена ЮКассы на Prodamus
Выполняет:
1. Переименование yookassa_payment_method_id в payment_method_id
2. Добавление subscription_id в таблицу subscriptions
3. Добавление prodamus_order_id в таблицу payment_logs
"""

import os
import sys
import sqlite3
from datetime import datetime

# Добавляем корневую папку в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def migrate_database(db_path="momsclub.db"):
    """
    Выполняет миграцию базы данных для перехода с ЮКассы на Prodamus
    
    Args:
        db_path (str): Путь к файлу базы данных
    """
    
    print(f"🔄 Начинаем миграцию базы данных: {db_path}")
    
    # Создаем резервную копию
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    try:
        # Копируем БД для резерва
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Создана резервная копия: {backup_path}")
    except Exception as e:
        print(f"⚠️  Не удалось создать резервную копию: {e}")
        response = input("Продолжить без резервной копии? (y/N): ")
        if response.lower() != 'y':
            print("❌ Миграция отменена")
            return False
    
    # Подключение к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("📋 Начинаем выполнение миграций...")
        
        # 1. Проверяем существование поля yookassa_payment_method_id
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'yookassa_payment_method_id' in columns:
            print("🔄 Переименовываем yookassa_payment_method_id в payment_method_id...")
            
            # SQLite не поддерживает переименование колонок напрямую, используем временную таблицу
            cursor.execute("""
                CREATE TABLE users_new AS 
                SELECT 
                    id, telegram_id, username, first_name, last_name, is_active,
                    referrer_id, referral_code, welcome_sent, created_at, updated_at,
                    birthday, birthday_gift_year, 
                    yookassa_payment_method_id as payment_method_id,
                    is_recurring_active, phone, reminder_sent, is_blocked
                FROM users
            """)
            
            cursor.execute("DROP TABLE users")
            cursor.execute("ALTER TABLE users_new RENAME TO users")
            
            # Восстанавливаем индексы и ограничения
            cursor.execute("CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id)")
            cursor.execute("CREATE UNIQUE INDEX idx_users_referral_code ON users(referral_code)")
            
            print("✅ Поле переименовано: yookassa_payment_method_id → payment_method_id")
        else:
            print("ℹ️  Поле yookassa_payment_method_id не найдено, возможно уже переименовано")
        
        # 2. Добавляем subscription_id в таблицу subscriptions
        cursor.execute("PRAGMA table_info(subscriptions)")
        sub_columns = [col[1] for col in cursor.fetchall()]
        
        if 'subscription_id' not in sub_columns:
            print("🔄 Добавляем поле subscription_id в таблицу subscriptions...")
            cursor.execute("ALTER TABLE subscriptions ADD COLUMN subscription_id VARCHAR(255)")
            print("✅ Поле subscription_id добавлено")
        else:
            print("ℹ️  Поле subscription_id уже существует")
        
        # 3. Добавляем prodamus_order_id в таблицу payment_logs
        cursor.execute("PRAGMA table_info(payment_logs)")
        payment_columns = [col[1] for col in cursor.fetchall()]
        
        if 'prodamus_order_id' not in payment_columns:
            print("🔄 Добавляем поле prodamus_order_id в таблицу payment_logs...")
            cursor.execute("ALTER TABLE payment_logs ADD COLUMN prodamus_order_id VARCHAR(255)")
            print("✅ Поле prodamus_order_id добавлено")
        else:
            print("ℹ️  Поле prodamus_order_id уже существует")
        
        # 4. Проверяем что все изменения применились
        print("🔍 Проверяем результаты миграции...")
        
        cursor.execute("PRAGMA table_info(users)")
        user_columns_after = [col[1] for col in cursor.fetchall()]
        
        cursor.execute("PRAGMA table_info(subscriptions)")
        sub_columns_after = [col[1] for col in cursor.fetchall()]
        
        cursor.execute("PRAGMA table_info(payment_logs)")
        payment_columns_after = [col[1] for col in cursor.fetchall()]
        
        # Проверки
        checks = [
            ('payment_method_id в users', 'payment_method_id' in user_columns_after),
            ('yookassa_payment_method_id удалено', 'yookassa_payment_method_id' not in user_columns_after),
            ('subscription_id в subscriptions', 'subscription_id' in sub_columns_after),
            ('prodamus_order_id в payment_logs', 'prodamus_order_id' in payment_columns_after)
        ]
        
        all_passed = True
        for check_name, check_result in checks:
            status = "✅" if check_result else "❌"
            print(f"{status} {check_name}")
            if not check_result:
                all_passed = False
        
        if all_passed:
            # Сохраняем изменения
            conn.commit()
            print("🎉 Миграция успешно завершена!")
            print(f"📊 Резервная копия сохранена в: {backup_path}")
            return True
        else:
            print("❌ Миграция не была завершена из-за ошибок")
            conn.rollback()
            return False
            
    except Exception as e:
        print(f"❌ Ошибка во время миграции: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def rollback_migration(db_path="momsclub.db"):
    """
    Откат миграции из резервной копии
    """
    import glob
    
    # Ищем последнюю резервную копию
    backup_files = glob.glob(f"{db_path}.backup_*")
    if not backup_files:
        print("❌ Резервные копии не найдены")
        return False
    
    latest_backup = max(backup_files)
    
    print(f"🔄 Восстанавливаем из резервной копии: {latest_backup}")
    
    try:
        import shutil
        shutil.copy2(latest_backup, db_path)
        print("✅ База данных восстановлена из резервной копии")
        return True
    except Exception as e:
        print(f"❌ Ошибка при восстановлении: {e}")
        return False

if __name__ == "__main__":
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback_migration()
    else:
        migrate_database()
