#!/usr/bin/env python3
"""
Тестовый скрипт для проверки исправлений greenlet в системе лояльности.
Запускает однократную проверку loyalty без ожидания 08:00 МСК.
"""

import asyncio
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger('loyalty_test')

async def test_loyalty_check():
    """
    Тестовый запуск проверки лояльности для выявления greenlet ошибок.
    """
    from config import BOT_TOKEN
    from aiogram import Bot
    from database.config import AsyncSessionLocal
    from database.crud import get_active_subscription, check_and_grant_badges
    from database.models import User
    from loyalty.levels import calc_tenure_days, upgrade_level_if_needed
    from loyalty.service import send_choose_benefit_push
    from sqlalchemy import select
    from database.models import LoyaltyEvent
    
    logger.info("=" * 80)
    logger.info("🧪 ТЕСТОВЫЙ ЗАПУСК ПРОВЕРКИ ЛОЯЛЬНОСТИ")
    logger.info(f"📅 Дата и время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    
    bot = Bot(token=BOT_TOKEN)
    
    try:
        async with AsyncSessionLocal() as session:
            # Получаем несколько пользователей для тестирования (ограничим 5 пользователями)
            query = select(User).where(
                User.first_payment_date.isnot(None)
            ).limit(5)
            
            result = await session.execute(query)
            users = result.scalars().all()
            
            logger.info(f"👥 Найдено пользователей для теста: {len(users)}")
            
            # КРИТИЧНО: Сохраняем ВСЕ атрибуты ВСЕХ пользователей ДО начала обработки
            # Это защищает от greenlet ошибок после commit в цикле
            users_data = []
            for user in users:
                users_data.append({
                    'user_object': user,
                    'user_id': user.id,
                    'user_telegram_id': user.telegram_id,
                    'current_loyalty_level': user.current_loyalty_level,
                    'pending_loyalty_reward': user.pending_loyalty_reward
                })
            
            # Статистика
            stats = {
                'total': len(users_data),
                'badges_granted': 0,
                'errors': 0,
                'success': 0
            }
            
            # Тестируем обработку каждого пользователя
            for idx, user_data in enumerate(users_data, 1):
                # Используем сохраненные данные
                user = user_data['user_object']
                user_id = user_data['user_id']
                user_telegram_id = user_data['user_telegram_id']
                current_loyalty_level = user_data['current_loyalty_level']
                pending_loyalty_reward = user_data['pending_loyalty_reward']
                
                try:
                    logger.info(f"\n--- [{idx}/{len(users)}] Обработка user_id={user_id} (telegram_id={user_telegram_id}) ---")
                    
                    # 1. Проверка badges
                    logger.info(f"  🏆 Проверка badges для user_id={user_id}...")
                    granted_badges = await check_and_grant_badges(session, user)
                    if granted_badges:
                        stats['badges_granted'] += len(granted_badges)
                        logger.info(f"  ✅ Выданы badges: {granted_badges}")
                    else:
                        logger.info(f"  ℹ️  Новых badges нет")
                    
                    # 2. Проверка стажа и уровня
                    tenure_days = await calc_tenure_days(session, user)
                    logger.info(f"  📊 Стаж: {tenure_days} дней, уровень: {current_loyalty_level or 'none'}")
                    
                    # 3. Проверка активной подписки
                    active_sub = await get_active_subscription(session, user_id)
                    logger.info(f"  🔔 Активная подписка: {'✅ Да' if active_sub else '❌ Нет'}")
                    
                    # 4. Проверка повышения уровня
                    old_level = current_loyalty_level or 'none'
                    new_level = await upgrade_level_if_needed(session, user)
                    
                    if new_level:
                        logger.info(f"  ⬆️  ПОВЫШЕНИЕ: {old_level} → {new_level}")
                    
                    # 5. Проверка pending_loyalty_reward
                    if pending_loyalty_reward and current_loyalty_level and current_loyalty_level != 'none':
                        benefit_check_query = select(LoyaltyEvent.id).where(
                            LoyaltyEvent.user_id == user_id,
                            LoyaltyEvent.kind == 'benefit_chosen',
                            LoyaltyEvent.level == current_loyalty_level
                        )
                        benefit_check_result = await session.execute(benefit_check_query)
                        
                        if not benefit_check_result.scalar_one_or_none():
                            logger.info(f"  🎁 Pending reward: ДА (уровень {current_loyalty_level})")
                        else:
                            logger.info(f"  ℹ️  Бонус уже выбран для уровня {current_loyalty_level}")
                    
                    # Коммитим изменения
                    await session.commit()
                    stats['success'] += 1
                    logger.info(f"  ✅ Успешно обработан user_id={user_id}")
                    
                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"  ❌ ОШИБКА для user_id={user_id}: {e}", exc_info=True)
                    await session.rollback()
            
            # Итоговая статистика
            logger.info("=" * 80)
            logger.info("📊 ИТОГОВАЯ СТАТИСТИКА ТЕСТА")
            logger.info("=" * 80)
            logger.info(f"👥 Всего обработано: {stats['total']}")
            logger.info(f"✅ Успешно: {stats['success']}")
            logger.info(f"🏆 Badges выдано: {stats['badges_granted']}")
            logger.info(f"❌ Ошибок: {stats['errors']}")
            logger.info("=" * 80)
            
            if stats['errors'] == 0:
                logger.info("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Greenlet ошибок НЕТ!")
            else:
                logger.error("❌ ЕСТЬ ОШИБКИ! Проверьте логи выше.")
            
            logger.info("=" * 80)
            
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА В ТЕСТЕ: {e}", exc_info=True)
    
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(test_loyalty_check())
