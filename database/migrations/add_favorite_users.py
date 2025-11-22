"""
Миграция для добавления таблицы избранных пользователей
Добавляет таблицу favorite_users для возможности админам закреплять важных пользователей
"""

import os
import sys
import sqlite3

# Добавляем корневую папку в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def add_favorite_users_table(db_path="momsclub.db"):
    """
    Добавляет таблицу favorite_users для избранных пользователей админов
    
    Args:
        db_path (str): Путь к файлу базы данных
    """
    
    print(f"🔄 Начинаем добавление таблицы favorite_users: {db_path}")
    
    # Подключение к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли уже таблица
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='favorite_users'")
        table_exists = cursor.fetchone()
        
        if table_exists:
            print("ℹ️  Таблица favorite_users уже существует")
            return True
            
        print("📋 Создаем таблицу favorite_users...")
        
        # Создаем таблицу для избранных пользователей
        cursor.execute("""
            CREATE TABLE favorite_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_telegram_id INTEGER NOT NULL,
                user_telegram_id INTEGER NOT NULL,
                note TEXT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(admin_telegram_id, user_telegram_id)
            )
        """)
        
        # Создаем индексы для быстрого поиска
        cursor.execute("CREATE INDEX idx_favorite_users_admin ON favorite_users(admin_telegram_id)")
        cursor.execute("CREATE INDEX idx_favorite_users_user ON favorite_users(user_telegram_id)")
        
        # Сохраняем изменения
        conn.commit()
        
        print("✅ Таблица favorite_users успешно создана")
        print("✅ Индексы созданы")
        
        # Проверяем структуру созданной таблицы
        cursor.execute("PRAGMA table_info(favorite_users)")
        columns = cursor.fetchall()
        print("📋 Структура таблицы favorite_users:")
        for col in columns:
            print(f"   - {col[1]} {col[2]} {'NOT NULL' if col[3] else 'NULL'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при создании таблицы favorite_users: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("🚀 Запуск миграции для добавления избранных пользователей")
    
    # Создаем таблицу
    success = add_favorite_users_table()
    
    if success:
        print("🎉 Миграция успешно завершена!")
        print("⭐ Теперь админы могут добавлять пользователей в избранное")
    else:
        print("❌ Ошибка при создании таблицы")
