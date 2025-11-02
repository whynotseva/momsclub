import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv
from database.models import Base
from database.config import DATABASE_URL
import sqlite3
import logging
from sqlalchemy import text

# Загружаем переменные окружения
load_dotenv()

# Настраиваем логирование
logger = logging.getLogger(__name__)

# Создаем движок для асинхронного подключения
engine = create_async_engine(DATABASE_URL)

async def add_columns_for_autorenewal():
    """
    Добавляет колонки для автопродления в таблицу subscriptions
    """
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(subscriptions)"))
        columns = result.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'next_retry_attempt_at' not in column_names:
            await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN next_retry_attempt_at DATETIME"))
            
        if 'autopayment_fail_count' not in column_names:
            await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN autopayment_fail_count INTEGER DEFAULT 0"))
            
        if 'renewal_price' not in column_names:
            await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN renewal_price INTEGER"))
            
        if 'renewal_duration_days' not in column_names:
            await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN renewal_duration_days INTEGER"))

async def add_subscription_notification_table():
    """
    Добавляет таблицу для отслеживания отправленных уведомлений
    """
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='subscription_notifications'"))
        table_exists = bool(result.fetchone())
        
        if not table_exists:
            await conn.execute(text("""
                CREATE TABLE subscription_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id INTEGER NOT NULL,
                    notification_type VARCHAR(50) NOT NULL,
                    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
                    UNIQUE(subscription_id, notification_type)
                )
            """))

async def create_tables():
    """Создает все таблицы в базе данных и выполняет дополнительные миграции."""
    # Создаем все таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Выполняем дополнительные миграции
    await add_columns_for_autorenewal()
    await add_subscription_notification_table()
    await add_reminder_sent_column()
    await add_is_blocked_column()
    print("База данных и все требуемые таблицы созданы.")

def alter_users_table():
    """Изменяет структуру таблицы users, добавляя новые колонки"""
    try:
        # Получаем путь к базе данных из DATABASE_URL
        db_path = DATABASE_URL.replace('sqlite+aiosqlite:///', '')
        
        # Прямое подключение к SQLite для выполнения ALTER TABLE
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, существуют ли уже колонки
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Добавляем колонку birthday, если она не существует
        if 'birthday' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN birthday DATE")
            logger.info("Колонка 'birthday' добавлена в таблицу users")
        
        # Добавляем колонку birthday_gift_year, если она не существует
        if 'birthday_gift_year' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN birthday_gift_year INTEGER")
            logger.info("Колонка 'birthday_gift_year' добавлена в таблицу users")
        
        # Сохраняем изменения и закрываем соединение
        conn.commit()
        conn.close()
        
        print("Таблица users успешно обновлена")
        return True
    except Exception as e:
        logger.error(f"Ошибка при изменении таблицы users: {e}")
        print(f"Ошибка при изменении таблицы users: {e}")
        return False

async def add_reminder_sent_column():
    """
    Добавляет колонку reminder_sent в таблицу users,
    если она еще не существует.
    """
    async with engine.begin() as conn:
        # Проверяем, существует ли уже колонка reminder_sent в таблице users
        result = await conn.execute(text("PRAGMA table_info(users)"))
        columns = result.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'reminder_sent' not in column_names:
            print("Добавление колонки reminder_sent в таблицу users...")
            await conn.execute(text("ALTER TABLE users ADD COLUMN reminder_sent BOOLEAN DEFAULT 0"))
            print("Колонка reminder_sent успешно добавлена")
        else:
            print("Колонка reminder_sent уже существует в таблице users")

async def add_is_blocked_column():
    """
    Добавляет колонку is_blocked в таблицу users,
    если она еще не существует.
    """
    async with engine.begin() as conn:
        # Проверяем, существует ли уже колонка is_blocked в таблице users
        result = await conn.execute(text("PRAGMA table_info(users)"))
        columns = result.fetchall()
        column_names = [column[1] for column in columns]
        
        if 'is_blocked' not in column_names:
            print("Добавление колонки is_blocked в таблицу users...")
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_blocked BOOLEAN DEFAULT 0"))
            print("Колонка is_blocked успешно добавлена")
        else:
            print("Колонка is_blocked уже существует в таблице users")

async def main(alter=False):
    """Основная функция для инициализации базы данных"""
    await create_tables()
    
    # Если указан флаг alter, также изменяем существующие таблицы
    if alter:
        alter_users_table()
    
    print("База данных SQLite инициализирована")

if __name__ == "__main__":
    # Если скрипт запущен напрямую, выполняем создание таблиц и изменение структуры
    asyncio.run(main(alter=True)) 