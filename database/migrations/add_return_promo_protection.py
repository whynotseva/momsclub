"""
Миграция: Добавление полей защиты от злоупотребления промокодами возврата

Дата: 18.11.2025
Автор: System

Описание:
- Добавляет поля return_promo_count и last_return_promo_date в таблицу users
- Защита от злоупотребления: максимум 3 промокода, минимум 90 дней между ними
"""

import sqlite3
import sys
import os
from datetime import datetime

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'momsclub.db')


def run_migration():
    """Выполняет миграцию базы данных"""
    print(f"🔄 Начало миграции: добавление полей защиты от злоупотребления промокодами возврата")
    print(f"📂 База данных: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print(f"❌ Ошибка: файл базы данных не найден: {DB_PATH}")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Проверяем, существуют ли уже поля
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        fields_to_add = []
        
        if 'return_promo_count' not in columns:
            fields_to_add.append(('return_promo_count', 'INTEGER DEFAULT 0'))
            print("  ➕ Будет добавлено поле: return_promo_count")
        else:
            print("  ✓ Поле return_promo_count уже существует")
        
        if 'last_return_promo_date' not in columns:
            fields_to_add.append(('last_return_promo_date', 'DATETIME'))
            print("  ➕ Будет добавлено поле: last_return_promo_date")
        else:
            print("  ✓ Поле last_return_promo_date уже существует")
        
        # Добавляем поля, если нужно
        if fields_to_add:
            for field_name, field_type in fields_to_add:
                sql = f"ALTER TABLE users ADD COLUMN {field_name} {field_type}"
                print(f"  🔧 Выполняется: {sql}")
                cursor.execute(sql)
            
            conn.commit()
            print(f"✅ Миграция успешно выполнена! Добавлено полей: {len(fields_to_add)}")
        else:
            print("✅ Все поля уже существуют, миграция не требуется")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(users)")
        columns_after = [column[1] for column in cursor.fetchall()]
        
        if 'return_promo_count' in columns_after and 'last_return_promo_date' in columns_after:
            print("✅ Проверка: все поля успешно добавлены")
            
            # Показываем статистику
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            print(f"📊 Всего пользователей в БД: {user_count}")
            
            return True
        else:
            print("❌ Ошибка: не все поля были добавлены")
            return False
        
    except sqlite3.Error as e:
        print(f"❌ Ошибка SQLite: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False
    finally:
        if conn:
            conn.close()
            print("🔒 Соединение с БД закрыто")


if __name__ == "__main__":
    print("=" * 70)
    print("МИГРАЦИЯ: Защита от злоупотребления промокодами возврата")
    print("=" * 70)
    print()
    
    success = run_migration()
    
    print()
    print("=" * 70)
    if success:
        print("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
    else:
        print("❌ МИГРАЦИЯ ЗАВЕРШЕНА С ОШИБКАМИ")
    print("=" * 70)
    
    sys.exit(0 if success else 1)
