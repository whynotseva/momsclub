"""
Batch-обработка для системы лояльности.

Улучшенная версия loyalty_nightly_job с обработкой батчами.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, LoyaltyEvent
from database.crud import get_active_subscription
from loyalty.levels import calc_tenure_days, upgrade_level_if_needed
from loyalty.service import send_choose_benefit_push, send_loyalty_reminders
from database.crud import check_and_grant_badges
from utils.batch_processor import BatchProcessor

logger = logging.getLogger('loyalty')


async def process_single_user_loyalty(session: AsyncSession, user: User) -> dict:
    """
    Обрабатывает одного пользователя в системе лояльности.
    
    Args:
        session: Сессия БД
        user: Пользователь
        
    Returns:
        Словарь с результатами обработки
    """
    result = {
        'user_id': user.id,
        'upgraded': False,
        'push_sent': False,
        'pending_notified': False,
        'has_active_sub': False,
        'current_level': user.current_loyalty_level or 'none',
        'error': None
    }
    
    try:
        # Получаем стаж
        tenure_days = await calc_tenure_days(session, user)
        
        # Проверяем активную подписку
        active_sub = await get_active_subscription(session, user.id)
        result['has_active_sub'] = active_sub is not None
        
        logger.debug(
            f"Обработка user_id={user.id}: стаж={tenure_days} дней, "
            f"уровень={result['current_level']}, подписка={'✅' if result['has_active_sub'] else '❌'}"
        )
        
        # Проверяем и повышаем уровень
        old_level = user.current_loyalty_level or 'none'
        new_level = await upgrade_level_if_needed(session, user)
        
        if new_level:
            result['upgraded'] = True
            result['new_level'] = new_level
            
            logger.info(
                f"⬆️  ПОВЫШЕНИЕ: user_id={user.id}: {old_level} → {new_level} "
                f"(стаж: {tenure_days} дней)"
            )
            
            # Отправляем push если есть активная подписка
            if active_sub:
                await session.refresh(user)
                
                # Импортируем бота (будет передан через контекст)
                from bot import bot
                
                success = await send_choose_benefit_push(
                    bot,
                    session,
                    user,
                    new_level
                )
                
                result['push_sent'] = success
                
                if success:
                    logger.info(f"✅ Push отправлен: user_id={user.id}, level={new_level}")
                else:
                    logger.error(f"❌ Push не отправлен: user_id={user.id}")
        
        # Проверяем pending_loyalty_reward
        await session.refresh(user)
        if (user.pending_loyalty_reward and 
            user.current_loyalty_level and 
            user.current_loyalty_level != 'none'):
            
            # ИСПРАВЛЕНИЕ БАГА: Проверяем АКТУАЛЬНЫЙ рассчитанный уровень
            from loyalty.levels import level_for_days
            actual_level = level_for_days(tenure_days)
            
            if user.current_loyalty_level != actual_level:
                logger.warning(
                    f"⚠️ Несоответствие уровней user_id={user.id}: "
                    f"db={user.current_loyalty_level}, actual={actual_level}, tenure={tenure_days}"
                )
                # Не отправляем push если уровни не совпадают
                result['error'] = f"level_mismatch: db={user.current_loyalty_level}, actual={actual_level}"
            else:
                # Проверяем, не выбирал ли уже бонус
                benefit_check_query = select(LoyaltyEvent.id).where(
                    LoyaltyEvent.user_id == user.id,
                    LoyaltyEvent.kind == 'benefit_chosen',
                    LoyaltyEvent.level == user.current_loyalty_level
                )
                benefit_check_result = await session.execute(benefit_check_query)
                
                if not benefit_check_result.scalar_one_or_none():
                    # Бонус не выбран
                    if active_sub:
                        from bot import bot
                        
                        success = await send_choose_benefit_push(
                            bot,
                            session,
                            user,
                            user.current_loyalty_level
                        )
                        
                        if success:
                            result['pending_notified'] = True
                            logger.info(f"✅ Pending push отправлен: user_id={user.id}")
        
        return result
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"❌ Ошибка обработки user_id={user.id}: {e}", exc_info=True)
        return result


async def process_badges_batch(session: AsyncSession, users: list) -> int:
    """
    Обрабатывает badges для батча пользователей.
    
    Args:
        session: Сессия БД
        users: Список пользователей
        
    Returns:
        Количество выданных badges
    """
    badges_logger = logging.getLogger('badges')
    badges_count = 0
    
    for user in users:
        try:
            await session.refresh(user)
            granted_badges = await check_and_grant_badges(session, user)
            if granted_badges:
                badges_count += len(granted_badges)
                badges_logger.info(f"Выданы badges user_id={user.id}: {granted_badges}")
        except Exception as e:
            badges_logger.error(f"Ошибка badges для user_id={user.id}: {e}")
    
    return badges_count


async def loyalty_nightly_job_batched():
    """
    Улучшенная версия loyalty_nightly_job с batch-обработкой.
    
    Преимущества:
    - Обработка батчами по 50 пользователей
    - При ошибке откатывается только текущий батч
    - Остальные батчи продолжают обрабатываться
    - Детальная статистика по батчам
    """
    
    while True:
        try:
            # Ждём до 08:00 МСК
            now = datetime.now()
            target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
            
            if now >= target_time:
                target_time += timedelta(days=1)
            
            time_to_sleep = (target_time - now).total_seconds()
            logger.info(
                f"⏰ Следующая проверка лояльности в {target_time.strftime('%Y-%m-%d %H:%M:%S')} МСК "
                f"(через {time_to_sleep/3600:.1f} часов)"
            )
            
            await asyncio.sleep(time_to_sleep)
            
            # ========== НАЧАЛО ПРОВЕРКИ ==========
            now = datetime.now()
            logger.info("=" * 80)
            logger.info("🚀 ЗАПУСК BATCH-ОБРАБОТКИ СИСТЕМЫ ЛОЯЛЬНОСТИ")
            logger.info(f"📅 Дата: {now.strftime('%Y-%m-%d %H:%M:%S')} МСК")
            logger.info("=" * 80)
            
            is_monday = now.weekday() == 0
            
            async with AsyncSessionLocal() as session:
                # Получаем всех пользователей
                query = select(User).where(User.first_payment_date.isnot(None))
                result = await session.execute(query)
                users = result.scalars().all()
                
                logger.info(f"👥 Найдено пользователей: {len(users)}")
                
                # Обрабатываем badges батчами
                logger.info("🏆 Обработка badges...")
                badges_count = await process_badges_batch(session, users)
                if badges_count > 0:
                    logger.info(f"✅ Выдано badges: {badges_count}")
                
                # Обрабатываем лояльность батчами
                logger.info("💎 Обработка уровней лояльности...")
                
                processor = BatchProcessor(batch_size=50)
                batch_stats = await processor.process_batch(
                    session=session,
                    items=users,
                    processor_func=process_single_user_loyalty,
                    batch_name="loyalty"
                )
                
                # Собираем статистику
                stats = {
                    'total': len(users),
                    'processed': batch_stats['processed'],
                    'failed': batch_stats['failed'],
                    'upgraded': 0,
                    'push_sent': 0,
                    'pending_notified': 0,
                    'with_active_sub': 0,
                    'by_level': {'none': 0, 'silver': 0, 'gold': 0, 'platinum': 0}
                }
                
                # Подсчитываем детальную статистику
                # (в реальности нужно собирать из результатов process_single_user_loyalty)
                
                # ========== ФИНАЛЬНАЯ СТАТИСТИКА ==========
                logger.info("=" * 80)
                logger.info("📊 ИТОГОВАЯ СТАТИСТИКА")
                logger.info("=" * 80)
                logger.info(f"👥 Всего пользователей: {stats['total']}")
                logger.info(f"✅ Обработано успешно: {stats['processed']}")
                logger.info(f"❌ Ошибок: {stats['failed']}")
                logger.info(f"📦 Батчей успешно: {batch_stats['batches_success']}/{batch_stats['batches_total']}")
                logger.info("=" * 80)
                logger.info("✅ ПРОВЕРКА ЗАВЕРШЕНА")
                logger.info("=" * 80)
                
                # Еженедельные напоминания (понедельник)
                if is_monday:
                    logger.info("🔔 Отправка еженедельных напоминаний...")
                    from bot import bot
                    reminder_stats = await send_loyalty_reminders(bot, session)
                    logger.info(f"📤 Отправлено напоминаний: {reminder_stats['reminders_sent']}")
            
            # Ждём до следующего запуска
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
            
            # Отправляем алерт админам
            try:
                from utils.constants import ADMIN_IDS
                from bot import bot
                
                if ADMIN_IDS:
                    error_message = (
                        f"🚨 <b>Критическая ошибка в системе лояльности!</b>\n\n"
                        f"Ошибка: {str(e)[:500]}"
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, error_message, parse_mode="HTML")
                        except:
                            pass
            except:
                pass
            
            await asyncio.sleep(600)  # 10 минут перед повторной попыткой
