"""
Миграция БД: Добавление уникального индекса на transaction_id
Дата: 20.11.2025
Задача: CRIT-001 из аудита кода

ВАЖНО: Этот скрипт нужно запустить ПЕРЕД деплоем новой версии кода!
"""

import sqlite3
import uuid
import time
from datetime import datetime


def migrate_transaction_id(db_path='momsclub.db'):
    """
    Миграция payment_logs.transaction_id:
    1. Заполняет NULL значения уникальными ID
    2. Создает уникальный индекс
    
    Args:
        db_path: путь к БД SQLite
    """
    print("=" * 80)
    print("МИГРАЦИЯ БД: transaction_id unique constraint")
    print("=" * 80)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Шаг 1: Проверяем текущее состояние
        print("\n1️⃣ Проверка текущего состояния...")
        cursor.execute("SELECT COUNT(*) FROM payment_logs WHERE transaction_id IS NULL")
        null_count = cursor.fetchone()[0]
        print(f"   Найдено записей с NULL transaction_id: {null_count}")
        
        cursor.execute("SELECT COUNT(*) FROM payment_logs")
        total_count = cursor.fetchone()[0]
        print(f"   Всего записей в payment_logs: {total_count}")
        
        # Шаг 2: Заполняем NULL значения
        if null_count > 0:
            print(f"\n2️⃣ Заполнение {null_count} NULL значений уникальными ID...")
            
            cursor.execute("SELECT id FROM payment_logs WHERE transaction_id IS NULL")
            null_ids = cursor.fetchall()
            
            for (payment_id,) in null_ids:
                # Генерируем уникальный ID в формате legacy_<id>_<timestamp>
                unique_id = f"legacy_{payment_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
                cursor.execute(
                    "UPDATE payment_logs SET transaction_id = ? WHERE id = ?",
                    (unique_id, payment_id)
                )
            
            conn.commit()
            print(f"   ✅ Заполнено {null_count} записей")
        else:
            print("   ✅ NULL значений нет, пропускаем")
        
        # Шаг 3: Проверяем дубликаты
        print("\n3️⃣ Проверка дубликатов transaction_id...")
        cursor.execute("""
            SELECT transaction_id, COUNT(*) as cnt 
            FROM payment_logs 
            GROUP BY transaction_id 
            HAVING cnt > 1
        """)
        duplicates = cursor.fetchall()
        
        if duplicates:
            print(f"   ⚠️  ВНИМАНИЕ! Найдено {len(duplicates)} дубликатов:")
            for trans_id, cnt in duplicates[:10]:  # Показываем первые 10
                print(f"      - {trans_id}: {cnt} раз")
            
            print("\n   🔧 Исправление дубликатов...")
            for trans_id, cnt in duplicates:
                # Оставляем первую запись, остальные обновляем
                cursor.execute(
                    "SELECT id FROM payment_logs WHERE transaction_id = ? ORDER BY id",
                    (trans_id,)
                )
                dup_ids = cursor.fetchall()
                
                # Обновляем все кроме первой
                for i, (dup_id,) in enumerate(dup_ids[1:], 1):
                    new_id = f"{trans_id}_dup{i}_{uuid.uuid4().hex[:8]}"
                    cursor.execute(
                        "UPDATE payment_logs SET transaction_id = ? WHERE id = ?",
                        (new_id, dup_id)
                    )
            
            conn.commit()
            print(f"   ✅ Дубликаты исправлены")
        else:
            print("   ✅ Дубликатов нет")
        
        # Шаг 4: Создаем уникальный индекс
        print("\n4️⃣ Создание уникального индекса...")
        try:
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_logs_transaction_id "
                "ON payment_logs(transaction_id)"
            )
            conn.commit()
            print("   ✅ Уникальный индекс создан")
        except sqlite3.IntegrityError as e:
            print(f"   ❌ ОШИБКА при создании индекса: {e}")
            print("   Возможно, остались дубликаты. Проверьте вручную!")
            raise
        
        # Шаг 5: Финальная проверка
        print("\n5️⃣ Финальная проверка...")
        cursor.execute("SELECT COUNT(*) FROM payment_logs WHERE transaction_id IS NULL")
        final_null_count = cursor.fetchone()[0]
        
        if final_null_count == 0:
            print("   ✅ NULL значений не осталось")
        else:
            print(f"   ❌ ОШИБКА: Осталось {final_null_count} NULL значений!")
            raise Exception("Migration failed: NULL values remain")
        
        # Проверяем индекс
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name='idx_payment_logs_transaction_id'
        """)
        if cursor.fetchone():
            print("   ✅ Индекс успешно создан")
        else:
            print("   ❌ ОШИБКА: Индекс не найден!")
            raise Exception("Migration failed: Index not created")
        
        print("\n" + "=" * 80)
        print("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 80)
        print(f"\nВремя: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Обработано записей: {total_count}")
        print(f"Заполнено NULL: {null_count}")
        print(f"Исправлено дубликатов: {len(duplicates) if duplicates else 0}")
        
    except Exception as e:
        print(f"\n❌ ОШИБКА МИГРАЦИИ: {e}")
        conn.rollback()
        raise
    
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "momsclub.db"
    
    print(f"База данных: {db_path}")
    
    # Спрашиваем подтверждение
    response = input("\n⚠️  Начать миграцию? (yes/no): ")
    if response.lower() != 'yes':
        print("Миграция отменена")
        sys.exit(0)
    
    migrate_transaction_id(db_path)
