"""
Миграция для реферальной системы 2.0
Добавляет:
- Новые поля в User (referral_balance, total_referrals_paid, total_earned_referral)
- Таблицу referral_rewards (история наград)
- Таблицу withdrawal_requests (заявки на вывод)
"""

import asyncio
from sqlalchemy.sql import text
from database.config import engine
import logging

logger = logging.getLogger(__name__)

async def upgrade():
    """Применение миграции"""
    async with engine.begin() as conn:
        logger.info("Начало миграции referral_system_v2...")
        
        # 1. Добавляем новые колонки в users
        # SQLite не поддерживает IF NOT EXISTS в ALTER TABLE, поэтому обрабатываем ошибки
        logger.info("Добавление новых колонок в таблицу users...")
        
        try:
            await conn.execute(text("""
                ALTER TABLE users ADD COLUMN referral_balance INTEGER DEFAULT 0;
            """))
            logger.info("✅ Колонка referral_balance добавлена")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                logger.info("⚠️  Колонка referral_balance уже существует")
            else:
                raise
        
        try:
            await conn.execute(text("""
                ALTER TABLE users ADD COLUMN total_referrals_paid INTEGER DEFAULT 0;
            """))
            logger.info("✅ Колонка total_referrals_paid добавлена")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                logger.info("⚠️  Колонка total_referrals_paid уже существует")
            else:
                raise
        
        try:
            await conn.execute(text("""
                ALTER TABLE users ADD COLUMN total_earned_referral INTEGER DEFAULT 0;
            """))
            logger.info("✅ Колонка total_earned_referral добавлена")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                logger.info("⚠️  Колонка total_earned_referral уже существует")
            else:
                raise
        
        # 2. Создаем таблицу referral_rewards
        logger.info("Создание таблицы referral_rewards...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS referral_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referee_id INTEGER NOT NULL,
                payment_amount INTEGER NOT NULL,
                reward_type TEXT NOT NULL,
                reward_amount INTEGER NOT NULL,
                loyalty_level TEXT,
                bonus_percent INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (referee_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """))
        logger.info("✅ Таблица referral_rewards создана")
        
        # 3. Создаем индексы для referral_rewards
        logger.info("Создание индексов для referral_rewards...")
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_referral_rewards_referrer 
            ON referral_rewards(referrer_id);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_referral_rewards_referee 
            ON referral_rewards(referee_id);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_referral_rewards_created 
            ON referral_rewards(created_at);
        """))
        logger.info("✅ Индексы для referral_rewards созданы")
        
        # 4. Создаем таблицу withdrawal_requests
        logger.info("Создание таблицы withdrawal_requests...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                payment_details TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                processed_by_admin_id INTEGER,
                admin_comment TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (processed_by_admin_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """))
        logger.info("✅ Таблица withdrawal_requests создана")
        
        # 5. Создаем индексы для withdrawal_requests
        logger.info("Создание индексов для withdrawal_requests...")
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user 
            ON withdrawal_requests(user_id);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_status 
            ON withdrawal_requests(status);
        """))
        
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_created 
            ON withdrawal_requests(created_at);
        """))
        logger.info("✅ Индексы для withdrawal_requests созданы")
        
        logger.info("✅ Миграция referral_system_v2 успешно применена!")

async def downgrade():
    """Откат миграции"""
    async with engine.begin() as conn:
        logger.info("Начало отката миграции referral_system_v2...")
        
        # Удаляем таблицы в обратном порядке
        await conn.execute(text("DROP TABLE IF EXISTS withdrawal_requests CASCADE;"))
        logger.info("✅ Таблица withdrawal_requests удалена")
        
        await conn.execute(text("DROP TABLE IF EXISTS referral_rewards CASCADE;"))
        logger.info("✅ Таблица referral_rewards удалена")
        
        # Удаляем колонки из users
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS referral_balance;"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS total_referrals_paid;"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS total_earned_referral;"))
        logger.info("✅ Колонки из users удалены")
        
        logger.info("✅ Откат миграции referral_system_v2 выполнен!")

if __name__ == "__main__":
    print("🚀 Запуск миграции referral_system_v2...")
    asyncio.run(upgrade())
    print("✅ Миграция завершена!")
