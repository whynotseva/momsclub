"""
Миграция: Дополнительные индексы для оптимизации производительности (Неделя 3)

Добавляет индексы для:
- Быстрого поиска по transaction_id (идемпотентность платежей)
- Оптимизации запросов лояльности
- Ускорения поиска по датам рождения
- Оптимизации автопродлений
"""

import sqlite3
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_advanced_indexes(db_path="momsclub.db"):
    """
    Добавляет дополнительные индексы для оптимизации.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("=" * 70)
        print("🚀 ДОБАВЛЕНИЕ РАСШИРЕННЫХ ИНДЕКСОВ (НЕДЕЛЯ 3)")
        print("=" * 70)
        print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # Новые индексы для Недели 3
        indexes = [
            # 1. Индекс для идемпотентности платежей (transaction_id)
            (
                "idx_payment_logs_transaction",
                "CREATE INDEX IF NOT EXISTS idx_payment_logs_transaction ON payment_logs(transaction_id, status, is_confirmed)",
                "Ускоряет проверку дубликатов платежей"
            ),
            
            # 2. Индекс для поиска по subscription_id в payment_logs
            (
                "idx_payment_logs_subscription",
                "CREATE INDEX IF NOT EXISTS idx_payment_logs_subscription ON payment_logs(subscription_id)",
                "Связь платежей с подписками"
            ),
            
            # 3. Композитный индекс для лояльности
            (
                "idx_users_loyalty",
                "CREATE INDEX IF NOT EXISTS idx_users_loyalty ON users(current_loyalty_level, pending_loyalty_reward, first_payment_date)",
                "Оптимизация запросов системы лояльности"
            ),
            
            # 4. Индекс для дней рождения (месяц-день)
            (
                "idx_users_birthday",
                "CREATE INDEX IF NOT EXISTS idx_users_birthday ON users(birthday)",
                "Быстрый поиск именинников"
            ),
            
            # 5. Индекс для автопродлений
            (
                "idx_subscriptions_autopay",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_autopay ON subscriptions(next_retry_attempt_at, is_active)",
                "Оптимизация автопродлений"
            ),
            
            # 6. Индекс для реферальной системы
            (
                "idx_users_referrer",
                "CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)",
                "Быстрый поиск рефералов"
            ),
            
            # 7. Индекс для created_at в payment_logs (статистика)
            (
                "idx_payment_logs_created",
                "CREATE INDEX IF NOT EXISTS idx_payment_logs_created ON payment_logs(created_at, status)",
                "Статистика платежей по датам"
            ),
            
            # 8. Индекс для loyalty_events по уровню
            (
                "idx_loyalty_events_level",
                "CREATE INDEX IF NOT EXISTS idx_loyalty_events_level ON loyalty_events(user_id, level, kind, created_at)",
                "Оптимизация истории лояльности"
            ),
        ]
        
        created_count = 0
        existing_count = 0
        
        for idx_name, idx_sql, description in indexes:
            try:
                cursor.execute(idx_sql)
                logger.info(f"✅ Индекс {idx_name} создан")
                print(f"✅ {idx_name}")
                print(f"   └─ {description}")
                created_count += 1
            except sqlite3.OperationalError as e:
                if "already exists" in str(e):
                    logger.info(f"ℹ️  Индекс {idx_name} уже существует")
                    print(f"ℹ️  {idx_name} (уже существует)")
                    print(f"   └─ {description}")
                    existing_count += 1
                else:
                    raise
        
        conn.commit()
        
        # Анализируем БД для обновления статистики
        print("\n" + "=" * 70)
        print("🔄 АНАЛИЗ БАЗЫ ДАННЫХ...")
        print("=" * 70)
        cursor.execute("ANALYZE")
        conn.commit()
        print("✅ Статистика БД обновлена")
        
        # Показываем статистику
        print("\n" + "=" * 70)
        print("📊 СТАТИСТИКА ИНДЕКСОВ")
        print("=" * 70)
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name")
        all_indexes = cursor.fetchall()
        
        print(f"Всего индексов: {len(all_indexes)}")
        print(f"Создано новых: {created_count}")
        print(f"Уже существовало: {existing_count}")
        print("\nПолный список индексов:")
        for idx in all_indexes:
            print(f"  • {idx[0]}")
        
        # Показываем размер БД
        cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
        db_size = cursor.fetchone()[0]
        print(f"\nРазмер БД: {db_size / 1024 / 1024:.2f} MB")
        
        # Показываем количество записей в таблицах
        print("\nКоличество записей:")
        for table in ['users', 'subscriptions', 'payment_logs', 'loyalty_events']:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  • {table}: {count:,}")
        
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
        print("=" * 70)
        print("\n💡 Рекомендации:")
        print("  1. Перезапустите бота для применения изменений")
        print("  2. Мониторьте производительность запросов")
        print("  3. При необходимости запустите VACUUM для оптимизации")
        print("\n")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании индексов: {e}", exc_info=True)
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    # Определяем путь к БД
    db_path = os.getenv("DB_PATH", "momsclub.db")
    if not os.path.exists(db_path):
        logger.error(f"База данных не найдена: {db_path}")
        print(f"❌ БД не найдена: {db_path}")
        print(f"Ищем в: {os.path.abspath(db_path)}")
        exit(1)
    
    print(f"📂 Путь к БД: {os.path.abspath(db_path)}\n")
    
    success = add_advanced_indexes(db_path)
    exit(0 if success else 1)
