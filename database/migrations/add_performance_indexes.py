"""
Миграция: Добавление индексов для повышения производительности БД
Индексы улучшают скорость запросов при росте количества пользователей
"""
import sqlite3
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_performance_indexes(db_path="momsclub.db"):
    """
    Добавляет индексы для оптимизации запросов.
    Безопасно: индексы создаются только если их еще нет (IF NOT EXISTS).
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("=" * 60)
        print("🚀 ДОБАВЛЕНИЕ ИНДЕКСОВ ПРОИЗВОДИТЕЛЬНОСТИ")
        print("=" * 60)
        
        indexes = [
            # Индекс на username для быстрого поиска пользователей
            ("idx_users_username", "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"),
            
            # Индекс на first_payment_date для расчетов лояльности
            ("idx_users_first_payment", "CREATE INDEX IF NOT EXISTS idx_users_first_payment ON users(first_payment_date)"),
            
            # Композитный индекс для поиска активных подписок
            ("idx_subscriptions_active", "CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(user_id, is_active, end_date)"),
            
            # Индекс для истории платежей пользователя
            ("idx_payment_logs_user", "CREATE INDEX IF NOT EXISTS idx_payment_logs_user ON payment_logs(user_id, status)"),
            
            # Индекс для событий лояльности
            ("idx_loyalty_events_user", "CREATE INDEX IF NOT EXISTS idx_loyalty_events_user ON loyalty_events(user_id, kind)"),
            
            # Индекс для промокодов (уже есть, но проверим)
            ("idx_promo_codes_code", "CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes(code)"),
        ]
        
        for idx_name, idx_sql in indexes:
            try:
                cursor.execute(idx_sql)
                logger.info(f"✅ Индекс {idx_name} создан")
                print(f"✅ {idx_name}")
            except sqlite3.OperationalError as e:
                if "already exists" in str(e):
                    logger.info(f"ℹ️  Индекс {idx_name} уже существует")
                    print(f"ℹ️  {idx_name} (уже существует)")
                else:
                    raise
        
        conn.commit()
        
        # Показываем статистику
        print("\n" + "=" * 60)
        print("📊 СТАТИСТИКА ИНДЕКСОВ")
        print("=" * 60)
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name")
        all_indexes = cursor.fetchall()
        
        print(f"Всего индексов: {len(all_indexes)}")
        for idx in all_indexes:
            print(f"  • {idx[0]}")
        
        conn.close()
        
        print("\n" + "=" * 60)
        print("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
        print("=" * 60)
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании индексов: {e}")
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    # Определяем путь к БД
    db_path = os.getenv("DB_PATH", "momsclub.db")
    if not os.path.exists(db_path):
        logger.error(f"База данных не найдена: {db_path}")
        print(f"❌ БД не найдена: {db_path}")
        exit(1)
    
    success = add_performance_indexes(db_path)
    exit(0 if success else 1)

