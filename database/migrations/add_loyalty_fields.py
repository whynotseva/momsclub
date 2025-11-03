"""
Миграция: добавление полей лояльности в таблицы users и subscriptions
Создание таблицы loyalty_events
"""
import asyncio
import logging
import os
import shutil
from datetime import datetime
from sqlalchemy import text
from database.config import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def add_loyalty_fields():
    """Добавляет поля лояльности в БД"""
    # Создаем резервную копию БД (для SQLite)
    from database.config import DATABASE_PATH
    db_path = DATABASE_PATH
    if db_path and os.path.exists(db_path):
        backup_path = f"{db_path}.backup_loyalty_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy2(db_path, backup_path)
            logger.info(f"✅ Создана резервная копия: {backup_path}")
        except Exception as e:
            logger.warning(f"⚠️  Не удалось создать резервную копию: {e}")
    
    async with engine.begin() as conn:
        try:
            # Функция для безопасного добавления колонки (SQLite не поддерживает IF NOT EXISTS)
            async def add_column_if_not_exists(table_name, column_name, column_def):
                try:
                    await conn.execute(text(f"""
                        ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}
                    """))
                    logger.info(f"✅ Добавлено поле {column_name} в {table_name}")
                    return True
                except Exception as e:
                    if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                        logger.debug(f"Поле {column_name} в {table_name} уже существует, пропускаю")
                        return False
                    raise
            
            # Добавляем поля в таблицу users
            await add_column_if_not_exists("users", "first_payment_date", "DATETIME NULL")
            await add_column_if_not_exists("users", "current_loyalty_level", "TEXT DEFAULT 'none'")
            await add_column_if_not_exists("users", "one_time_discount_percent", "INTEGER DEFAULT 0")
            await add_column_if_not_exists("users", "lifetime_discount_percent", "INTEGER DEFAULT 0")
            await add_column_if_not_exists("users", "pending_loyalty_reward", "INTEGER DEFAULT 0")
            await add_column_if_not_exists("users", "gift_due", "INTEGER DEFAULT 0")
            
            # Добавляем поля в таблицу subscriptions (опционально для аудита)
            await add_column_if_not_exists("subscriptions", "loyalty_applied_level", "TEXT NULL")
            await add_column_if_not_exists("subscriptions", "loyalty_discount_percent", "INTEGER DEFAULT 0")
            
            # Создаем таблицу loyalty_events
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS loyalty_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    level TEXT,
                    payload TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """))
            logger.info("✅ Создана таблица loyalty_events")
            
            # Создаем индекс для быстрого поиска
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_loyalty_events_user_id ON loyalty_events(user_id)
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_loyalty_events_kind ON loyalty_events(kind)
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_loyalty_events_created_at ON loyalty_events(created_at)
            """))
            logger.info("✅ Созданы индексы для loyalty_events")
            
            # Обновляем CHECK constraint для current_loyalty_level (SQLite не поддерживает ALTER COLUMN, поэтому пересоздаем)
            # Но для SQLite это сложно, оставляем как есть - валидация на уровне приложения
            
            logger.info("✅ Миграция полей завершена, начинаем обновление данных...")
            
            # Обновляем first_payment_date для существующих пользователей на основе истории платежей
            await update_first_payment_dates(conn)
            
            # Рассчитываем и устанавливаем уровни лояльности для всех пользователей
            await calculate_loyalty_levels(conn)
            
            # Помечаем пользователей, которым нужно выбрать бонус
            await mark_users_for_benefit_selection(conn)
            
            logger.info("✅ Миграция лояльности завершена успешно")
            logger.info("📌 ВАЖНО: После перезапуска бота ночной крон отправит push-уведомления пользователям с уровнями для выбора бонусов")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении миграции: {e}", exc_info=True)
            raise


async def update_first_payment_dates(conn):
    """Обновляет first_payment_date для всех пользователей на основе первой успешной оплаты"""
    logger.info("🔄 Обновление дат первых оплат...")
    
    # Находим первую успешную оплату для каждого пользователя
    result = await conn.execute(text("""
        SELECT 
            user_id,
            MIN(created_at) as first_payment_date
        FROM payment_logs
        WHERE status = 'success' AND (is_confirmed = 1 OR is_confirmed IS NULL)
        GROUP BY user_id
    """))
    
    updates = result.fetchall()
    updated_count = 0
    
    for user_id, first_payment_date in updates:
        # Обновляем first_payment_date только если оно еще не установлено
        await conn.execute(text("""
            UPDATE users 
            SET first_payment_date = :first_payment_date
            WHERE id = :user_id 
            AND (first_payment_date IS NULL OR first_payment_date = '')
        """), {"user_id": user_id, "first_payment_date": first_payment_date})
        
        updated_count += 1
    
    logger.info(f"✅ Обновлено first_payment_date из платежей для {updated_count} пользователей")
    
    # Также проверяем первую подписку, если платежей нет
    result2 = await conn.execute(text("""
        SELECT 
            u.id as user_id,
            MIN(s.start_date) as first_subscription_date
        FROM users u
        INNER JOIN subscriptions s ON s.user_id = u.id
        WHERE u.first_payment_date IS NULL OR u.first_payment_date = ''
        GROUP BY u.id
    """))
    
    subscription_updates = result2.fetchall()
    sub_updated_count = 0
    
    for user_id, first_subscription_date in subscription_updates:
        await conn.execute(text("""
            UPDATE users 
            SET first_payment_date = :first_payment_date
            WHERE id = :user_id
        """), {"user_id": user_id, "first_payment_date": first_subscription_date})
        sub_updated_count += 1
    
    if sub_updated_count > 0:
        logger.info(f"✅ Установлено first_payment_date из подписок для {sub_updated_count} пользователей")


async def calculate_loyalty_levels(conn):
    """Рассчитывает и устанавливает уровни лояльности для всех пользователей на основе стажа"""
    logger.info("🔄 Расчёт уровней лояльности...")
    
    # Используем прямую логику без импорта модулей (избегаем проблем с циклическими импортами)
    # Пороги: Silver=90, Gold=180, Platinum=365
    
    # Получаем всех пользователей с first_payment_date
    result = await conn.execute(text("""
        SELECT 
            id,
            first_payment_date,
            COALESCE(current_loyalty_level, 'none') as current_level
        FROM users
        WHERE first_payment_date IS NOT NULL AND first_payment_date != ''
    """))
    
    users = result.fetchall()
    updated_count = 0
    level_stats = {'none': 0, 'silver': 0, 'gold': 0, 'platinum': 0}
    
    for user_id, first_payment_date, current_level in users:
        # Рассчитываем стаж в днях через SQL
        tenure_result = await conn.execute(text("""
            SELECT CAST(julianday('now') - julianday(:first_date) AS INTEGER) as days
        """), {"first_date": first_payment_date})
        
        tenure_row = tenure_result.fetchone()
        if not tenure_row:
            continue
        
        tenure_days = tenure_row[0] if tenure_row[0] is not None else 0
        
        # Определяем уровень по порогам
        if tenure_days >= 365:
            new_level = 'platinum'
        elif tenure_days >= 180:
            new_level = 'gold'
        elif tenure_days >= 90:
            new_level = 'silver'
        else:
            new_level = 'none'
        
        # Обновляем только если уровень изменился
        if current_level != new_level:
            await conn.execute(text("""
                UPDATE users 
                SET current_loyalty_level = :level
                WHERE id = :user_id
            """), {"user_id": user_id, "level": new_level})
            updated_count += 1
            level_stats[new_level] = level_stats.get(new_level, 0) + 1
            logger.debug(f"User {user_id}: стаж {tenure_days} дней → уровень {current_level} → {new_level}")
        else:
            # Считаем статистику и для существующих
            level_stats[new_level] = level_stats.get(new_level, 0) + 1
    
    logger.info(f"✅ Обновлено уровней лояльности для {updated_count} пользователей")
    logger.info(f"📊 Статистика уровней: none={level_stats['none']}, silver={level_stats['silver']}, gold={level_stats['gold']}, platinum={level_stats['platinum']}")


async def mark_users_for_benefit_selection(conn):
    """
    Помечает пользователей с уровнями лояльности, которым нужно выбрать бонус.
    Проверяет только ТЕКУЩИЙ уровень пользователя - если для него еще не выбран бонус,
    помечает пользователя для получения одного push-уведомления.
    """
    logger.info("🔄 Проверка пользователей, которым нужно выбрать бонус...")
    
    # Находим пользователей с уровнями > 'none', которые еще не выбирали бонус для их ТЕКУЩЕГО уровня
    result = await conn.execute(text("""
        SELECT DISTINCT u.id, u.current_loyalty_level, u.telegram_id
        FROM users u
        LEFT JOIN loyalty_events le ON (
            le.user_id = u.id 
            AND le.kind = 'benefit_chosen' 
            AND le.level = u.current_loyalty_level
        )
        WHERE u.current_loyalty_level IS NOT NULL 
        AND u.current_loyalty_level != 'none'
        AND u.current_loyalty_level != ''
        AND le.id IS NULL
    """))
    
    users_to_notify = result.fetchall()
    marked_count = 0
    
    for user_id, current_level, telegram_id in users_to_notify:
        # Создаем событие level_up для истории (если его еще нет)
        level_up_check = await conn.execute(text("""
            SELECT id FROM loyalty_events 
            WHERE user_id = :user_id 
            AND kind = 'level_up' 
            AND level = :level
            LIMIT 1
        """), {"user_id": user_id, "level": current_level})
        
        if not level_up_check.fetchone():
            # Создаем событие level_up для истории
            await conn.execute(text("""
                INSERT INTO loyalty_events (user_id, kind, level, payload, created_at)
                VALUES (:user_id, 'level_up', :level, :payload, datetime('now'))
            """), {
                "user_id": user_id,
                "level": current_level,
                "payload": '{"migrated": true}'
            })
        
        # Устанавливаем флаг ожидания выбора бонуса (только для текущего уровня)
        await conn.execute(text("""
            UPDATE users 
            SET pending_loyalty_reward = 1
            WHERE id = :user_id
        """), {"user_id": user_id})
        
        marked_count += 1
        logger.debug(f"User {user_id} (telegram_id={telegram_id}): текущий уровень {current_level}, помечен для выбора бонуса")
    
    logger.info(f"✅ Помечено {marked_count} пользователей для получения push-уведомления о выборе бонуса")
    logger.info("💡 Ночной крон отправит push-уведомления только для АКТУАЛЬНОГО уровня после перезапуска бота")

if __name__ == "__main__":
    asyncio.run(add_loyalty_fields())

