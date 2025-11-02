"""
Миграция для добавления таблицы уведомлений о смене платежной системы
Добавляет таблицу migration_notifications для отслеживания уведомлений пользователям
"""

import os
import sys
import sqlite3
from datetime import datetime

# Добавляем корневую папку в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def add_migration_notifications_table(db_path="momsclub.db"):
    """
    Добавляет таблицу migration_notifications для отслеживания уведомлений о смене платежной системы
    
    Args:
        db_path (str): Путь к файлу базы данных
    """
    
    print(f"🔄 Начинаем добавление таблицы migration_notifications: {db_path}")
    
    # Подключение к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли уже таблица
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='migration_notifications'")
        table_exists = cursor.fetchone()
        
        if table_exists:
            print("ℹ️  Таблица migration_notifications уже существует")
            return True
            
        print("📋 Создаем таблицу migration_notifications...")
        
        # Создаем таблицу для отслеживания уведомлений о миграции
        cursor.execute("""
            CREATE TABLE migration_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                notification_type VARCHAR(50) NOT NULL DEFAULT 'payment_system_migration',
                is_sent BOOLEAN DEFAULT FALSE,
                sent_at DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        
        # Создаем индексы для быстрого поиска
        cursor.execute("CREATE INDEX idx_migration_notifications_user_id ON migration_notifications(user_id)")
        cursor.execute("CREATE INDEX idx_migration_notifications_type ON migration_notifications(notification_type)")
        cursor.execute("CREATE INDEX idx_migration_notifications_sent ON migration_notifications(is_sent)")
        
        # Сохраняем изменения
        conn.commit()
        
        print("✅ Таблица migration_notifications успешно создана")
        print("✅ Индексы созданы")
        
        # Проверяем структуру созданной таблицы
        cursor.execute("PRAGMA table_info(migration_notifications)")
        columns = cursor.fetchall()
        print("📋 Структура таблицы migration_notifications:")
        for col in columns:
            print(f"   - {col[1]} {col[2]} {'NOT NULL' if col[3] else 'NULL'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при создании таблицы migration_notifications: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def disable_old_autopayments(db_path="momsclub.db"):
    """
    Отключает автопродление и очищает payment_method_id для пользователей со старыми методами ЮКассы
    
    Args:
        db_path (str): Путь к файлу базы данных
    """
    
    print(f"🔄 Начинаем отключение автопродления для пользователей с ЮКасса: {db_path}")
    
    # Подключение к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем количество пользователей с payment_method_id
        cursor.execute("SELECT COUNT(*) FROM users WHERE payment_method_id IS NOT NULL")
        users_with_payment_method = cursor.fetchone()[0]
        
        print(f"📊 Найдено пользователей с платежными методами: {users_with_payment_method}")
        
        if users_with_payment_method == 0:
            print("ℹ️  Пользователей с платежными методами не найдено")
            return True
            
        # Отключаем автопродление для всех пользователей со старыми методами
        cursor.execute("""
            UPDATE users 
            SET is_recurring_active = FALSE 
            WHERE payment_method_id IS NOT NULL
        """)
        
        affected_recurring = cursor.rowcount
        print(f"✅ Отключено автопродление для {affected_recurring} пользователей")
        
        # Очищаем старые платежные методы
        cursor.execute("""
            UPDATE users 
            SET payment_method_id = NULL
            WHERE payment_method_id IS NOT NULL
        """)
        
        affected_payment_methods = cursor.rowcount
        print(f"✅ Очищены платежные методы для {affected_payment_methods} пользователей")
        
        # Сохраняем изменения
        conn.commit()
        
        # Проверяем результат
        cursor.execute("SELECT COUNT(*) FROM users WHERE payment_method_id IS NOT NULL")
        remaining_payment_methods = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_recurring_active = TRUE")
        remaining_recurring = cursor.fetchone()[0]
        
        print(f"📊 После миграции:")
        print(f"   - Пользователей с платежными методами: {remaining_payment_methods}")
        print(f"   - Пользователей с включенным автопродлением: {remaining_recurring}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при отключении автопродления: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("🚀 Запуск миграции уведомлений о смене платежной системы")
    
    # Создаем таблицу уведомлений
    success_table = add_migration_notifications_table()
    
    if success_table:
        # Отключаем старые автопродления
        success_disable = disable_old_autopayments()
        
        if success_disable:
            print("🎉 Миграция успешно завершена!")
            print("💬 Теперь можно запускать систему уведомлений")
        else:
            print("❌ Ошибка при отключении автопродлений")
    else:
        print("❌ Ошибка при создании таблицы уведомлений")
