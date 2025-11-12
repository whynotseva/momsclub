import asyncio
import logging
import os
# Исправление проблемы с aiodns и SelectorEventLoop на Windows
if os.name == "nt":
    # Для Windows требуется явно установить SelectorEventLoop для корректной работы aiodns
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from handlers.webhook_handlers import app as webhook_app
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from config import BOT_TOKEN
from handlers.admin import (
    register_admin_referrals_handlers,
    register_admin_subscriptions_handlers,
    register_admin_promocodes_handlers,
    register_admin_loyalty_handlers,
    register_admin_cancellations_handlers,
    register_admin_users_handlers,
    register_admin_core_handlers,
    register_admin_birthdays_handlers,
    register_admin_admins_handlers,
)
from handlers.user_handlers import register_user_handlers
from handlers.message_handlers import register_message_handlers
from utils.helpers import log_message
from utils.group_manager import GroupManager
from database.crud import (
    get_users_for_birthday_congratulation, 
    update_birthday_gift_year, 
    extend_subscription_days,
    get_user_by_id,
    update_user,
    create_payment_log,
    get_users_for_reminder,
    update_reminder_sent,
    mark_user_as_blocked,
    get_users_for_migration_notification,
    create_migration_notification,
    mark_migration_notification_sent,
    get_users_with_expired_subscriptions_for_reminder,
    get_users_for_milestone_notifications,
    get_subscription_notification,
    create_subscription_notification,
    check_and_grant_badges
)
from database.config import AsyncSessionLocal
from database.models import PaymentLog
from datetime import datetime, timedelta
from utils.constants import ADMIN_IDS, MIGRATION_NOTIFICATION_SETTINGS, MIGRATION_NOTIFICATION_TEXT
import time
from sqlalchemy import update, select, and_

# Настройка логирования с ротацией файлов
from logging.handlers import RotatingFileHandler

# Базовое логирование с ротацией (макс 10MB, 5 бэкапов)
rotating_handler = RotatingFileHandler(
    'bot.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
rotating_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[rotating_handler]
)

# Создаем отдельный логгер для платежей с ротацией
payment_logger = logging.getLogger('payments')
payment_logger.setLevel(logging.DEBUG)
payment_file_handler = RotatingFileHandler(
    'payment_logs.log',
    maxBytes=10*1024*1024,
    backupCount=5,
    encoding='utf-8'
)
payment_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
payment_logger.addHandler(payment_file_handler)

# Создаем отдельный логгер для дней рождения с ротацией
birthday_logger = logging.getLogger('birthdays')
birthday_logger.setLevel(logging.DEBUG)
birthday_file_handler = RotatingFileHandler(
    'birthday_logs.log',
    maxBytes=5*1024*1024,
    backupCount=3,
    encoding='utf-8'
)
birthday_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
birthday_logger.addHandler(birthday_file_handler)

# Создаем отдельный логгер для напоминаний
reminder_logger = logging.getLogger('reminders')
reminder_logger.setLevel(logging.INFO)

# Логгер для системы лояльности с ротацией
loyalty_logger = logging.getLogger('loyalty')
loyalty_logger.setLevel(logging.DEBUG)
loyalty_file_handler = RotatingFileHandler(
    'loyalty_logs.log',
    maxBytes=10*1024*1024,
    backupCount=5,
    encoding='utf-8'
)
loyalty_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
loyalty_logger.addHandler(loyalty_file_handler)

# Консольный хендлер для всех логов
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger('').addHandler(console_handler)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключаем middleware для автоматической синхронизации данных пользователей
from utils.user_sync_middleware import UserSyncMiddleware
dp.update.middleware(UserSyncMiddleware())

# Функция для поздравления пользователей с днем рождения
async def congratulate_birthdays():
    """
    Проверяет и поздравляет пользователей с днем рождения, 
    начисляя им 7 дней к подписке.
    """
    birthday_logger = logging.getLogger('birthdays')
    while True:
        try:
            # Время выполнения - каждый день в 00:01
            now = datetime.now()
            # Вычисляем время до следующего дня 00:01
            tomorrow = now.replace(hour=0, minute=1, second=0, microsecond=0) + timedelta(days=1)
            time_to_sleep = (tomorrow - now).total_seconds()
            
            # Если сейчас примерно 00:01 (с погрешностью 5 минут), выполняем проверку
            if now.hour == 0 and 0 <= now.minute <= 5:
                birthday_logger.info("Начинаем проверку пользователей с днем рождения")
                
                # Создаем экземпляр группового менеджера для отправки сообщений в группу
                group_manager = GroupManager(bot)
                
                async with AsyncSessionLocal() as session:
                    # Получаем список пользователей, у которых сегодня день рождения
                    birthday_users = await get_users_for_birthday_congratulation(session)
                    birthday_logger.info(f"Найдено {len(birthday_users)} пользователей с днем рождения")
                    
                    current_year = datetime.now().year
                    
                    for user in birthday_users:
                        try:
                            # Начисляем 7 дней к подписке
                            success = await extend_subscription_days(
                                session, 
                                user.id, 
                                7, 
                                reason="birthday_gift"
                            )
                            
                            if success:
                                # Отмечаем, что в этом году подарок уже выдан
                                await update_birthday_gift_year(session, user.id, current_year)
                                
                                # Формируем текст поздравления
                                name_to_use = user.username if user.username else user.first_name
                                if not name_to_use:
                                    name_to_use = "Красотка"
                                    
                                # Если есть username, используем его с @, иначе просто имя
                                if user.username:
                                    mention = f"@{user.username}"
                                else:
                                    mention = user.first_name
                                
                                # Текст поздравления в канал
                                congratulation_text = (
                                    f"Красотка {mention}, в этот прекрасный день, день твоего рождения, "
                                    f"мы дарим тебе +7 подарочных дней! С любовью, mom's club 🩷🫂"
                                )
                                
                                # Личное сообщение пользователю
                                personal_message = (
                                    f"🎉 Поздравляем с Днем Рождения, {name_to_use}! 🎂\n\n"
                                    f"В честь этого замечательного дня мы дарим тебе +7 дней к твоей подписке Mom's Club! ✨\n\n"
                                    f"Желаем тебе яркого и счастливого дня! 🩷"
                                )
                                
                                # Отправляем личное сообщение
                                try:
                                    await bot.send_message(user.telegram_id, personal_message)
                                    birthday_logger.info(f"Отправлено личное поздравление пользователю {user.telegram_id}")
                                except Exception as e:
                                    birthday_logger.error(f"Ошибка при отправке личного поздравления пользователю {user.telegram_id}: {e}")
                                
                                # Отправляем сообщение в общий чат группы
                                try:
                                    # Отправляем поздравление в общий чат через GroupManager
                                    result = await group_manager.send_message_to_topic(congratulation_text)
                                    
                                    if result:
                                        # Если отправка в общий чат успешна, сообщаем пользователю
                                        await bot.send_message(user.telegram_id, 
                                                          "Мы также поздравили вас в общем чате канала! 🎉")
                                        birthday_logger.info(f"Отправлено поздравление в общий чат для пользователя {user.telegram_id}")
                                    else:
                                        birthday_logger.error(f"Не удалось отправить поздравление в общий чат для пользователя {user.telegram_id}")
                                except Exception as e:
                                    birthday_logger.error(f"Ошибка при отправке поздравления в общий чат для пользователя {user.telegram_id}: {e}")
                            else:
                                birthday_logger.error(f"Не удалось начислить бонус за ДР пользователю {user.telegram_id}")
                        except Exception as e:
                            birthday_logger.error(f"Ошибка при обработке дня рождения пользователя {user.telegram_id}: {e}")
            
            # Спим до следующей проверки
            await asyncio.sleep(max(time_to_sleep, 60))  # Не менее 60 секунд
            
        except Exception as e:
            birthday_logger.error(f"Ошибка в функции поздравления с днем рождения: {e}")
            # Спим 10 минут перед повторной попыткой
            await asyncio.sleep(600)


async def run_webhook_server():
    """Запускает FastAPI сервер для вебхуков ЮКассы."""
    config = uvicorn.Config(
        app=webhook_app,
        host="0.0.0.0",  # Слушаем на всех интерфейсах
        port=8000,       # Порт для вебхуков (можно изменить)
        log_level="info"
    )
    server = uvicorn.Server(config)
    logging.info("Запуск сервера вебхуков ЮКассы на порту 8000...")
    try:
        logging.info("FastAPI сервер начинает работу...")
        await server.serve()
    except asyncio.CancelledError:
        logging.info("Сервер вебхуков останавливается.")
        await server.shutdown()
    except Exception as e:
        logging.error(f"Ошибка сервера вебхуков: {e}", exc_info=True)


from loyalty.service import send_choose_benefit_push, send_loyalty_reminders
from loyalty.levels import upgrade_level_if_needed
from database.models import User
from sqlalchemy import select

async def loyalty_nightly_job():
    """
    Утренний крон для системы лояльности: проверяет и повышает уровни,
    отправляет пуши с выбором бонусов.
    Запускается каждый день в 08:00 МСК.
    """
    loyalty_logger = logging.getLogger('loyalty')
    
    while True:
        try:
            # Ждём до ближайшего 08:00 МСК
            now = datetime.now()
            target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
            
            # Если уже прошло 08:00 сегодня, планируем на завтра
            if now >= target_time:
                target_time += timedelta(days=1)
            
            time_to_sleep = (target_time - now).total_seconds()
            loyalty_logger.info(f"⏰ Следующая проверка лояльности в {target_time.strftime('%Y-%m-%d %H:%M:%S')} МСК (через {time_to_sleep/3600:.1f} часов)")
            
            await asyncio.sleep(time_to_sleep)
            
            # ========== НАЧАЛО ПРОВЕРКИ ==========
            now = datetime.now()
            loyalty_logger.info("=" * 80)
            loyalty_logger.info("🚀 ЗАПУСК ПРОВЕРКИ СИСТЕМЫ ЛОЯЛЬНОСТИ")
            loyalty_logger.info(f"📅 Дата и время: {now.strftime('%Y-%m-%d %H:%M:%S')} МСК")
            loyalty_logger.info(f"📆 День недели: {now.strftime('%A')} ({now.weekday()})")
            loyalty_logger.info("=" * 80)
            
            # Проверяем, понедельник ли (weekday() = 0) для отправки напоминаний
            is_monday = now.weekday() == 0
            
            async with AsyncSessionLocal() as session:
                from database.crud import get_active_subscription
                from loyalty.levels import calc_tenure_days
                
                # Получаем всех пользователей с датой первой оплаты (для подсчёта стажа)
                query = select(User).where(
                    User.first_payment_date.isnot(None)
                )
                
                result = await session.execute(query)
                users = result.scalars().all()
                
                loyalty_logger.info(f"👥 Найдено пользователей с first_payment_date: {len(users)}")
                
                # Проверяем и выдаем badges для всех пользователей
                badges_logger = logging.getLogger('badges')
                badges_granted_count = 0
                for user in users:
                    try:
                        await session.refresh(user)
                        granted_badges = await check_and_grant_badges(session, user)
                        if granted_badges:
                            badges_granted_count += len(granted_badges)
                            badges_logger.info(f"Выданы badges пользователю {user.id}: {granted_badges}")
                    except Exception as e:
                        badges_logger.error(f"Ошибка при проверке badges для пользователя {user.id}: {e}")
                
                if badges_granted_count > 0:
                    loyalty_logger.info(f"🏆 Выдано badges: {badges_granted_count}")
                
                # Статистика по уровням
                stats = {
                    'total': len(users),
                    'with_active_sub': 0,
                    'without_active_sub': 0,
                    'upgraded': 0,
                    'pending_notified': 0,
                    'pending_skipped_no_sub': 0,
                    'by_level': {'none': 0, 'silver': 0, 'gold': 0, 'platinum': 0},
                    'errors': 0
                }
                
                upgraded_count = 0
                pending_notified_count = 0
                
                for idx, user in enumerate(users, 1):
                    try:
                        # Получаем стаж и текущий уровень для логирования
                        uid = user.id
                        tenure_days = await calc_tenure_days(session, user)
                        current_level = user.current_loyalty_level or 'none'
                        
                        # Проверяем активную подписку
                        active_sub = await get_active_subscription(session, user.id)
                        has_active_sub = active_sub is not None
                        
                        if has_active_sub:
                            stats['with_active_sub'] += 1
                        else:
                            stats['without_active_sub'] += 1
                        
                        # Подсчитываем статистику по уровням
                        if current_level in stats['by_level']:
                            stats['by_level'][current_level] += 1
                        
                        loyalty_logger.debug(
                            f"[{idx}/{len(users)}] user_id={user.id} (telegram_id={user.telegram_id}): "
                            f"стаж={tenure_days} дней, уровень={current_level}, "
                            f"активная подписка={'✅' if has_active_sub else '❌'}, "
                            f"pending_reward={'✅' if user.pending_loyalty_reward else '❌'}"
                        )
                        
                        # Проверяем и повышаем уровень, если нужно
                        old_level = user.current_loyalty_level or 'none'
                        new_level = await upgrade_level_if_needed(session, user)
                        
                        if new_level:
                            upgraded_count += 1
                            stats['upgraded'] += 1
                            loyalty_logger.info(
                                f"⬆️  ПОВЫШЕНИЕ УРОВНЯ: user_id={user.id} (telegram_id={user.telegram_id}): "
                                f"{old_level} → {new_level} (стаж: {tenure_days} дней)"
                            )
                            
                            # Проверяем наличие активной подписки перед отправкой push
                            active_sub = await get_active_subscription(session, user.id)
                            
                            if active_sub:
                                # Отправляем сообщение с выбором бонуса только если есть активная подписка
                                await session.refresh(user)  # Обновляем объект пользователя
                                
                                loyalty_logger.info(
                                    f"📤 Отправка push для нового уровня: user_id={user.id}, level={new_level}"
                                )
                                
                                success = await send_choose_benefit_push(
                                    bot,
                                    session,
                                    user,
                                    new_level
                                )
                                
                                if success:
                                    loyalty_logger.info(
                                        f"✅ Push отправлен успешно: user_id={user.id}, level={new_level}"
                                    )
                                else:
                                    loyalty_logger.error(
                                        f"❌ Не удалось отправить push: user_id={user.id}, level={new_level}"
                                    )
                            else:
                                loyalty_logger.info(
                                    f"⏭️  Пропуск push (нет активной подписки): user_id={user.id}, "
                                    f"достигнут уровень {new_level}"
                                )
                        
                        # Также проверяем пользователей с pending_loyalty_reward = True
                        # (например, после миграции) - только для АКТУАЛЬНОГО уровня
                        await session.refresh(user)
                        if (user.pending_loyalty_reward and 
                            user.current_loyalty_level and 
                            user.current_loyalty_level != 'none'):
                            
                            # Проверяем, не выбирал ли уже пользователь бонус для ТЕКУЩЕГО уровня
                            from database.models import LoyaltyEvent
                            
                            benefit_check_query = select(LoyaltyEvent.id).where(
                                LoyaltyEvent.user_id == user.id,
                                LoyaltyEvent.kind == 'benefit_chosen',
                                LoyaltyEvent.level == user.current_loyalty_level
                            )
                            benefit_check_result = await session.execute(benefit_check_query)
                            
                            if not benefit_check_result.scalar_one_or_none():
                                # Пользователь еще не выбирал бонус для текущего уровня
                                # Проверяем наличие активной подписки перед отправкой push
                                active_sub = await get_active_subscription(session, user.id)
                                
                                if active_sub:
                                    loyalty_logger.info(
                                        f"📤 Отправка push для pending reward: user_id={user.id}, "
                                        f"уровень={user.current_loyalty_level}"
                                    )
                                    
                                    # P2.3: Оборачиваем отправку push в try/except для обработки ошибок
                                    try:
                                        # Отправляем сообщение с выбором бонуса только для актуального уровня и только при активной подписке
                                        success = await send_choose_benefit_push(
                                            bot,
                                            session,
                                            user,
                                            user.current_loyalty_level
                                        )
                                        
                                        if success:
                                            pending_notified_count += 1
                                            stats['pending_notified'] += 1
                                            loyalty_logger.info(
                                                f"✅ Push отправлен (pending reward): user_id={user.id}, "
                                                f"уровень={user.current_loyalty_level}"
                                            )
                                            # НЕ сбрасываем pending_loyalty_reward здесь - он сбросится только после выбора бонуса пользователем
                                        else:
                                            loyalty_logger.error(
                                                f"❌ Не удалось отправить push (pending reward): user_id={user.id}"
                                            )
                                    except Exception as push_error:
                                        stats['errors'] += 1
                                        loyalty_logger.error(
                                            f"❌ Ошибка при отправке push (pending reward) для user_id={user.id}: {push_error}",
                                            exc_info=True
                                        )
                                else:
                                    stats['pending_skipped_no_sub'] += 1
                                    loyalty_logger.info(
                                        f"⏭️  Пропуск push (pending reward, нет активной подписки): "
                                        f"user_id={user.id}, уровень={user.current_loyalty_level}"
                                    )
                            else:
                                loyalty_logger.debug(
                                    f"ℹ️  Бонус уже выбран для уровня {user.current_loyalty_level}: user_id={user.id}"
                                )
                        
                        # Коммитим изменения по одному пользователю для уменьшения блокировок
                        await session.commit()
                        
                    except Exception as e:
                        stats['errors'] += 1
                        loyalty_logger.error(
                            f"❌ ОШИБКА при обработке user_id={uid}: {e}",
                            exc_info=True
                        )
                        await session.rollback()
                        # Небольшая задержка перед следующей итерацией
                        await asyncio.sleep(0.1)
                
                # ========== ФИНАЛЬНАЯ СТАТИСТИКА ==========
                loyalty_logger.info("=" * 80)
                loyalty_logger.info("📊 ИТОГОВАЯ СТАТИСТИКА ПРОВЕРКИ ЛОЯЛЬНОСТИ")
                loyalty_logger.info("=" * 80)
                loyalty_logger.info(f"👥 Всего пользователей проверено: {stats['total']}")
                loyalty_logger.info(f"✅ С активной подпиской: {stats['with_active_sub']}")
                loyalty_logger.info(f"❌ Без активной подписки: {stats['without_active_sub']}")
                loyalty_logger.info("")
                loyalty_logger.info("📈 Распределение по уровням:")
                loyalty_logger.info(f"   • None: {stats['by_level']['none']}")
                loyalty_logger.info(f"   • Silver: {stats['by_level']['silver']}")
                loyalty_logger.info(f"   • Gold: {stats['by_level']['gold']}")
                loyalty_logger.info(f"   • Platinum: {stats['by_level']['platinum']}")
                loyalty_logger.info("")
                loyalty_logger.info(f"⬆️  Повышено уровней: {stats['upgraded']}")
                loyalty_logger.info(f"📤 Отправлено push-уведомлений (pending rewards): {stats['pending_notified']}")
                loyalty_logger.info(f"⏭️  Пропущено push (нет активной подписки): {stats['pending_skipped_no_sub']}")
                loyalty_logger.info(f"❌ Ошибок при обработке: {stats['errors']}")
                loyalty_logger.info("=" * 80)
                loyalty_logger.info("✅ ПРОВЕРКА ЗАВЕРШЕНА")
                loyalty_logger.info("=" * 80)
                loyalty_logger.info("")
                
                # ========== ЕЖЕНЕДЕЛЬНЫЕ НАПОМИНАНИЯ (каждый понедельник) ==========
                if is_monday:
                    loyalty_logger.info("=" * 80)
                    loyalty_logger.info("🔔 ЗАПУСК ОТПРАВКИ НАПОМИНАНИЙ О БОНУСАХ ЛОЯЛЬНОСТИ")
                    loyalty_logger.info("=" * 80)
                    
                    reminder_stats = await send_loyalty_reminders(bot, session)
                    
                    loyalty_logger.info("=" * 80)
                    loyalty_logger.info("📊 СТАТИСТИКА НАПОМИНАНИЙ")
                    loyalty_logger.info("=" * 80)
                    loyalty_logger.info(f"👥 Всего проверено: {reminder_stats['total_checked']}")
                    loyalty_logger.info(f"✅ С pending_loyalty_reward: {reminder_stats['with_pending']}")
                    loyalty_logger.info(f"✅ С активной подпиской: {reminder_stats['with_active_sub']}")
                    loyalty_logger.info(f"📤 Отправлено напоминаний: {reminder_stats['reminders_sent']}")
                    loyalty_logger.info(f"⏭️  Пропущено (нет подписки): {reminder_stats['skipped_no_sub']}")
                    loyalty_logger.info(f"ℹ️  Уже выбрали бонус: {reminder_stats['already_chosen']}")
                    loyalty_logger.info(f"❌ Ошибок: {reminder_stats['errors']}")
                    loyalty_logger.info("=" * 80)
                    loyalty_logger.info("✅ НАПОМИНАНИЯ ЗАВЕРШЕНЫ")
                    loyalty_logger.info("=" * 80)
                    loyalty_logger.info("")
                else:
                    loyalty_logger.info(f"ℹ️  Сегодня не понедельник - напоминания не отправляются (день недели: {now.strftime('%A')})")
            
            # После выполнения ждём до следующего 08:00 МСК
            await asyncio.sleep(3600)  # Проверяем каждый час, чтобы не пропустить время
            
        except Exception as e:
            loyalty_logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в кроне лояльности: {e}", exc_info=True)
            
            # P2.3: Отправляем алерт админам при критической ошибке
            try:
                from utils.constants import ADMIN_IDS
                if ADMIN_IDS:
                    error_message = (
                        f"🚨 <b>Критическая ошибка в системе лояльности!</b>\n\n"
                        f"Ошибка: {str(e)[:500]}\n\n"
                        f"Проверьте логи бота для деталей."
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, error_message, parse_mode="HTML")
                        except Exception as admin_error:
                            loyalty_logger.error(f"Не удалось отправить алерт админу {admin_id}: {admin_error}")
            except Exception as alert_error:
                loyalty_logger.error(f"Ошибка при отправке алерта админам: {alert_error}")
            
            # Спим 10 минут перед повторной попыткой
            await asyncio.sleep(600)


async def run_loyalty_check_once():
    """
    Однократный ручной запуск проверки системы лояльности.
    Повторяет основную логику daily-крона без ожиданий.
    """
    loyalty_logger = logging.getLogger('loyalty')
    try:
        now = datetime.now()
        loyalty_logger.info("=" * 80)
        loyalty_logger.info("🚀 РУЧНОЙ ЗАПУСК ПРОВЕРКИ СИСТЕМЫ ЛОЯЛЬНОСТИ")
        loyalty_logger.info(f"📅 Дата и время: {now.strftime('%Y-%m-%d %H:%M:%S')} МСК")
        loyalty_logger.info(f"📆 День недели: {now.strftime('%A')} ({now.weekday()})")
        loyalty_logger.info("=" * 80)

        is_monday = now.weekday() == 0

        async with AsyncSessionLocal() as session:
            from database.crud import get_active_subscription
            from loyalty.levels import calc_tenure_days

            # Пользователи с first_payment_date
            query = select(User).where(
                User.first_payment_date.isnot(None)
            )
            result = await session.execute(query)
            users = result.scalars().all()

            loyalty_logger.info(f"👥 Найдено пользователей с first_payment_date: {len(users)}")

            stats = {
                'total': len(users),
                'with_active_sub': 0,
                'without_active_sub': 0,
                'upgraded': 0,
                'pending_notified': 0,
                'pending_skipped_no_sub': 0,
                'by_level': {'none': 0, 'silver': 0, 'gold': 0, 'platinum': 0},
                'errors': 0
            }

            for idx, user in enumerate(users, 1):
                try:
                    uid = user.id
                    tenure_days = await calc_tenure_days(session, user)
                    current_level = user.current_loyalty_level or 'none'

                    active_sub = await get_active_subscription(session, user.id)
                    has_active_sub = active_sub is not None
                    if has_active_sub:
                        stats['with_active_sub'] += 1
                    else:
                        stats['without_active_sub'] += 1

                    if current_level in stats['by_level']:
                        stats['by_level'][current_level] += 1

                    loyalty_logger.debug(
                        f"[{idx}/{len(users)}] user_id={user.id} (telegram_id={user.telegram_id}): "
                        f"стаж={tenure_days} дней, уровень={current_level}, "
                        f"активная подписка={'✅' if has_active_sub else '❌'}, "
                        f"pending_reward={'✅' if user.pending_loyalty_reward else '❌'}"
                    )

                    # Повышение уровня
                    old_level = user.current_loyalty_level or 'none'
                    new_level = await upgrade_level_if_needed(session, user)

                    if new_level:
                        stats['upgraded'] += 1
                        loyalty_logger.info(
                            f"⬆️  ПОВЫШЕНИЕ УРОВНЯ: user_id={user.id} (telegram_id={user.telegram_id}): "
                            f"{old_level} → {new_level} (стаж: {tenure_days} дней)"
                        )

                        # Отправка push при активной подписке
                        active_sub = await get_active_subscription(session, user.id)
                        if active_sub:
                            await session.refresh(user)
                            loyalty_logger.info(
                                f"📤 Отправка push для нового уровня: user_id={user.id}, level={new_level}"
                            )
                            success = await send_choose_benefit_push(
                                bot,
                                session,
                                user,
                                new_level
                            )
                            if success:
                                loyalty_logger.info(
                                    f"✅ Push отправлен успешно: user_id={user.id}, level={new_level}"
                                )
                            else:
                                loyalty_logger.error(
                                    f"❌ Не удалось отправить push: user_id={user.id}, level={new_level}"
                                )
                        else:
                            loyalty_logger.info(
                                f"⏭️  Пропуск push (нет активной подписки): user_id={user.id}, "
                                f"достигнут уровень {new_level}"
                            )

                    # Pending reward для текущего уровня
                    await session.refresh(user)
                    if (
                        user.pending_loyalty_reward and
                        user.current_loyalty_level and
                        user.current_loyalty_level != 'none'
                    ):
                        from database.models import LoyaltyEvent
                        benefit_check_query = select(LoyaltyEvent.id).where(
                            LoyaltyEvent.user_id == user.id,
                            LoyaltyEvent.kind == 'benefit_chosen',
                            LoyaltyEvent.level == user.current_loyalty_level
                        )
                        benefit_check_result = await session.execute(benefit_check_query)

                        if not benefit_check_result.scalar_one_or_none():
                            active_sub = await get_active_subscription(session, user.id)
                            if active_sub:
                                loyalty_logger.info(
                                    f"📤 Отправка push для pending reward: user_id={user.id}, "
                                    f"уровень={user.current_loyalty_level}"
                                )
                                try:
                                    success = await send_choose_benefit_push(
                                        bot,
                                        session,
                                        user,
                                        user.current_loyalty_level
                                    )
                                    if success:
                                        stats['pending_notified'] += 1
                                        loyalty_logger.info(
                                            f"✅ Push отправлен (pending reward): user_id={user.id}, "
                                            f"уровень={user.current_loyalty_level}"
                                        )
                                    else:
                                        loyalty_logger.error(
                                            f"❌ Не удалось отправить push (pending reward): user_id={user.id}"
                                        )
                                except Exception as push_error:
                                    stats['errors'] += 1
                                    loyalty_logger.error(
                                        f"❌ Ошибка при отправке push (pending reward) для user_id={user.id}: {push_error}",
                                        exc_info=True
                                    )
                            else:
                                stats['pending_skipped_no_sub'] += 1
                                loyalty_logger.info(
                                    f"⏭️  Пропуск push (pending reward, нет активной подписки): "
                                    f"user_id={user.id}, уровень={user.current_loyalty_level}"
                                )
                        else:
                            loyalty_logger.debug(
                                f"ℹ️  Бонус уже выбран для уровня {user.current_loyalty_level}: user_id={user.id}"
                            )

                    await session.commit()

                except Exception as e:
                    stats['errors'] += 1
                    loyalty_logger.error(
                        f"❌ ОШИБКА при обработке user_id={uid}: {e}",
                        exc_info=True
                    )
                    await session.rollback()
                    await asyncio.sleep(0.1)

            # Итоговая статистика
            loyalty_logger.info("=" * 80)
            loyalty_logger.info("📊 ИТОГОВАЯ СТАТИСТИКА ПРОВЕРКИ ЛОЯЛЬНОСТИ (ручной запуск)")
            loyalty_logger.info("=" * 80)
            loyalty_logger.info(f"👥 Всего пользователей проверено: {stats['total']}")
            loyalty_logger.info(f"✅ С активной подпиской: {stats['with_active_sub']}")
            loyalty_logger.info(f"❌ Без активной подписки: {stats['without_active_sub']}")
            loyalty_logger.info("")
            loyalty_logger.info("📈 Распределение по уровням:")
            loyalty_logger.info(f"   • None: {stats['by_level']['none']}")
            loyalty_logger.info(f"   • Silver: {stats['by_level']['silver']}")
            loyalty_logger.info(f"   • Gold: {stats['by_level']['gold']}")
            loyalty_logger.info(f"   • Platinum: {stats['by_level']['platinum']}")
            loyalty_logger.info("")
            loyalty_logger.info(f"⬆️  Повышено уровней: {stats['upgraded']}")
            loyalty_logger.info(f"📤 Отправлено push-уведомлений (pending rewards): {stats['pending_notified']}")
            loyalty_logger.info(f"⏭️  Пропущено push (нет активной подписки): {stats['pending_skipped_no_sub']}")
            loyalty_logger.info(f"❌ Ошибок при обработке: {stats['errors']}")
            loyalty_logger.info("=" * 80)

            # Еженедельные напоминания (если понедельник)
            if is_monday:
                loyalty_logger.info("=" * 80)
                loyalty_logger.info("🔔 ЗАПУСК ОТПРАВКИ НАПОМИНАНИЙ О БОНУСАХ ЛОЯЛЬНОСТИ (ручной запуск)")
                loyalty_logger.info("=" * 80)
                reminder_stats = await send_loyalty_reminders(bot, session)
                loyalty_logger.info("=" * 80)
                loyalty_logger.info("📊 СТАТИСТИКА НАПОМИНАНИЙ")
                loyalty_logger.info("=" * 80)
                loyalty_logger.info(f"👥 Всего проверено: {reminder_stats['total_checked']}")
                loyalty_logger.info(f"✅ С pending_loyalty_reward: {reminder_stats['with_pending']}")
                loyalty_logger.info(f"✅ С активной подпиской: {reminder_stats['with_active_sub']}")
                loyalty_logger.info(f"📤 Отправлено напоминаний: {reminder_stats['reminders_sent']}")
                loyalty_logger.info(f"⏭️  Пропущено (нет подписки): {reminder_stats['skipped_no_sub']}")
                loyalty_logger.info(f"ℹ️  Уже выбрали бонус: {reminder_stats['already_chosen']}")
                loyalty_logger.info(f"❌ Ошибок: {reminder_stats['errors']}")
                loyalty_logger.info("=" * 80)
                loyalty_logger.info("✅ НАПОМИНАНИЯ ЗАВЕРШЕНЫ")
            else:
                loyalty_logger.info(f"ℹ️  Сегодня не понедельник - напоминания не отправляются (день недели: {now.strftime('%A')})")

            loyalty_logger.info("✅ РУЧНАЯ ПРОВЕРКА ЗАВЕРШЕНА")

    except Exception as e:
        loyalty_logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в ручном запуске лояльности: {e}", exc_info=True)


async def send_payment_reminders():
    """
    Проверяет и отправляет напоминания пользователям, 
    которые зарегистрировались, но не оплатили подписку.
    """
    reminder_logger = logging.getLogger('reminders')
    reminder_logger.info("Запуск задачи отправки напоминаний об оплате")
    
    # Пути к фотографиям для напоминания
    reminder_photos = [
        os.path.join(os.getcwd(), "media/reminders/1.jpg"),
        os.path.join(os.getcwd(), "media/reminders/2.jpg"),
        os.path.join(os.getcwd(), "media/reminders/3.jpg"),
        os.path.join(os.getcwd(), "media/reminders/4.jpg"),
        os.path.join(os.getcwd(), "media/reminders/5.jpg"),
        os.path.join(os.getcwd(), "media/reminders/6.jpg")
    ]

    reminder_logger.info(f"Рабочая директория: {os.getcwd()}")

    # Проверка наличия фотографий и логирование результатов
    for photo_path in reminder_photos:
        exists = os.path.exists(photo_path)
        reminder_logger.info(f"Проверка фото {photo_path}: {'существует' if exists else 'НЕ НАЙДЕН'}")

    photos_exist = all(os.path.exists(photo) for photo in reminder_photos)
    reminder_logger.info(f"Общий результат проверки фотографий: {photos_exist}")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Получаем пользователей для отправки напоминания
                # Возвращаем стандартное значение 1 час вместо 1 минуты
                users = await get_users_for_reminder(session, hours_threshold=1)
                reminder_logger.info(f"Найдено {len(users)} пользователей для отправки напоминания")
                
                for user in users:
                    try:
                        # Создаем инлайн-клавиатуру с кнопками
                        keyboard = types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text="💓 Присоединиться к Mom's Club 💓", callback_data="subscribe")],
                                [types.InlineKeyboardButton(text="Написать Полине 💓", url="https://t.me/polinadmitrenkoo")]
                            ]
                        )
                        
                        # Текст напоминания
                        reminder_text = (
                            "Красотка, вижу, ты заглянула в клуб — и это уже крутой шаг! 💗\n\n"
                            "Но, похоже, пока не решилась присоединиться. Всё ок, выбор важный, и я рядом, чтобы помочь "
                            "тебе разобраться 😌\n\n"
                            "💬 Почитай отзывы наших участниц — они честно рассказывают, как клуб помог им меняться и "
                            "расти.\n\n"
                            "Если остались вопросы — пиши, я всегда на связи 🙌\n\n"
                            "🎀 Готова присоединиться и прокачивать себя вместе с нами?\n\n"
                            "Оформи подписку ниже 👇"
                        )
                        
                        if photos_exist:
                            # Если фотографии есть, отправляем их группой
                            reminder_logger.info(f"Начинаем отправку фотографий пользователю {user.telegram_id}")
                            media_group = []
                            
                            # Добавляем все 6 фотографий без подписи
                            for photo_path in reminder_photos:
                                if os.path.exists(photo_path):
                                    reminder_logger.info(f"Добавляем фото {photo_path} в медиагруппу")
                                    media_group.append(
                                        types.InputMediaPhoto(
                                            media=types.FSInputFile(photo_path),
                                            caption=None
                                        )
                                    )
                                else:
                                    reminder_logger.error(f"Файл {photo_path} не существует, пропускаем")
                            
                            if media_group:
                                try:
                                    # Отправляем группу фотографий
                                    reminder_logger.info(f"Отправляем медиагруппу из {len(media_group)} фото пользователю {user.telegram_id}")
                                    await bot.send_media_group(user.telegram_id, media=media_group)
                                    reminder_logger.info(f"Медиагруппа успешно отправлена пользователю {user.telegram_id}")
                                except Exception as e:
                                    reminder_logger.error(f"Ошибка при отправке медиагруппы пользователю {user.telegram_id}: {e}")
                                    # Проверяем, заблокировал ли пользователь бота при отправке медиа
                                    if 'bot was blocked by the user' in str(e) or 'USER_IS_BLOCKED' in str(e):
                                        # Отмечаем пользователя как заблокировавшего бота
                                        await mark_user_as_blocked(session, user.id)
                                        reminder_logger.info(f"Пользователь {user.telegram_id} отмечен как заблокировавший бота при отправке медиа")
                                        continue  # Переходим к следующему пользователю
                                    # Если не заблокирован, пробуем отправить только текст
                                    reminder_logger.info(f"Отправляем только текст без фото из-за ошибки")
                                    await bot.send_message(
                                        user.telegram_id,
                                        reminder_text,
                                        reply_markup=keyboard
                                    )
                                    continue  # Переходим к следующему пользователю
                                
                                # Сразу после фотографий отправляем текст с кнопками
                                reminder_logger.info(f"Отправляем текст с кнопками после медиагруппы")
                                await bot.send_message(
                                    user.telegram_id,
                                    reminder_text,
                                    reply_markup=keyboard
                                )
                            else:
                                # Если список медиафайлов пустой, отправляем только текст
                                reminder_logger.warning(f"Список медиафайлов пуст, отправляем только текст")
                                await bot.send_message(
                                    user.telegram_id,
                                    reminder_text,
                                    reply_markup=keyboard
                                )
                        else:
                            # Если фотографий нет, отправляем обычное сообщение
                            reminder_logger.info(f"Фотографии не найдены, отправляем только текст")
                            await bot.send_message(
                                user.telegram_id,
                                reminder_text,
                                reply_markup=keyboard
                            )
                        
                        # Обновляем статус отправки напоминания
                        await update_reminder_sent(session, user.id, True)
                        reminder_logger.info(f"Напоминание отправлено пользователю {user.telegram_id}")
                    
                    except Exception as e:
                        reminder_logger.error(f"Ошибка при отправке напоминания пользователю {user.telegram_id}: {e}")
                        # Проверяем, заблокировал ли пользователь бота
                        if 'bot was blocked by the user' in str(e) or 'USER_IS_BLOCKED' in str(e):
                            # Отмечаем пользователя как заблокировавшего бота
                            await mark_user_as_blocked(session, user.id)
                            reminder_logger.info(f"Пользователь {user.telegram_id} отмечен как заблокировавший бота")
            
            # Меняем интервал проверки с тестовых 30 секунд на 30 минут
            await asyncio.sleep(30 * 60)
            
        except Exception as e:
            reminder_logger.error(f"Ошибка в функции отправки напоминаний: {e}")
            # В случае ошибки ждем 5 минут перед повторной попыткой
            await asyncio.sleep(5 * 60)


async def send_expired_subscription_reminders():
    """
    Отправляет уведомления пользователям, у которых подписка истекла 3 дня назад
    ("мы скучаем" - возврат пользователей)
    """
    expired_logger = logging.getLogger('expired_reminders')
    expired_logger.info("Запуск задачи отправки уведомлений об истекших подписках")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Получаем пользователей с истекшими подписками (3 дня назад)
                users_with_subs = await get_users_with_expired_subscriptions_for_reminder(session, days_after_expiration=3)
                expired_logger.info(f"Найдено {len(users_with_subs)} пользователей с истекшими подписками для напоминания")
                
                for user, subscription in users_with_subs:
                    try:
                        keyboard = types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text="💓 Вернуться в Mom's Club", callback_data="subscribe")],
                                [types.InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
                            ]
                        )
                        
                        message_text = (
                            "💔 Красотка, мы скучаем по тебе!\n\n"
                            "Твоя подписка в Mom's Club закончилась 3 дня назад, и без тебя в чате не так тепло 😔\n\n"
                            "Помни — здесь всегда ждут:\n\n"
                            "✨ Поддержка от таких же мам\n\n"
                            "💕 Атмосфера, где можно быть собой\n\n"
                            "🎀 Материалы, что вдохновляют\n\n"
                            "Вернись, красотка, твое место — с нами 💖\n\n"
                            "Твоя Полина и команда Mom's Club 🩷"
                        )
                        
                        await bot.send_message(
                            user.telegram_id,
                            message_text,
                            reply_markup=keyboard
                        )
                        
                        # Отмечаем, что уведомление отправлено
                        await create_subscription_notification(session, subscription.id, 'expired_reminder_3days')
                        expired_logger.info(f"Уведомление 'мы скучаем' отправлено пользователю {user.telegram_id}")
                    
                    except Exception as e:
                        expired_logger.error(f"Ошибка при отправке уведомления пользователю {user.telegram_id}: {e}")
                        if 'bot was blocked by the user' in str(e) or 'USER_IS_BLOCKED' in str(e):
                            await mark_user_as_blocked(session, user.id)
                            expired_logger.info(f"Пользователь {user.telegram_id} отмечен как заблокировавший бота")
            
            # Проверяем раз в день
            await asyncio.sleep(24 * 60 * 60)
            
        except Exception as e:
            expired_logger.error(f"Ошибка в функции отправки уведомлений об истекших подписках: {e}")
            await asyncio.sleep(60 * 60)  # Ждем час при ошибке


async def send_milestone_notifications():
    """
    Отправляет milestone-уведомления пользователям, достигшим 100, 180 или 365 дней стажа
    """
    milestone_logger = logging.getLogger('milestones')
    milestone_logger.info("Запуск задачи отправки milestone-уведомлений")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Получаем пользователей для milestone-уведомлений
                users_for_notification = await get_users_for_milestone_notifications(session)
                milestone_logger.info(f"Найдено {len(users_for_notification)} пользователей для milestone-уведомлений")
                
                for user, milestone_days in users_for_notification:
                    try:
                        # Получаем последнюю активную подписку
                        from database.models import Subscription
                        from sqlalchemy import select
                        sub_query = select(Subscription).where(
                            and_(
                                Subscription.user_id == user.id,
                                Subscription.is_active == True
                            )
                        ).order_by(Subscription.end_date.desc()).limit(1)
                        sub_result = await session.execute(sub_query)
                        subscription = sub_result.scalar_one_or_none()
                        
                        if not subscription:
                            continue
                        
                        # Формируем текст в зависимости от достижения
                        achievement_texts = {
                            100: (
                                "🎉 Красотка, поздравляю тебя! 🎉\n\n"
                                "Ты с нами уже целых 100 дней! Это настоящий праздник, и я невероятно горжусь тобой! 💖\n\n"
                                "За это время ты стала не просто участницей, а настоящей частью нашего уютного сообщества мам. "
                                "Ты делишься опытом, поддерживаешь других девочек и продолжаешь расти вместе с нами.\n\n"
                                "Спасибо, что выбрала Mom's Club и доверила нам свое время и энергию. "
                                "Ты делаешь наше сообщество особенным! 🩷\n\n"
                                "Продолжай в том же духе, красотка! Мы всегда рядом, чтобы поддержать тебя на этом пути! ✨"
                            ),
                            180: (
                                "🌟 Невероятно, красотка! 🌟\n\n"
                                "Ты с нами уже полгода — целых 180 дней вместе! Это особенный момент, и я хочу сказать тебе, как это важно для меня! 💕\n\n"
                                "За эти месяцы ты стала настоящей частью нашей семьи. Ты не просто участница — ты часть сердца Mom's Club. "
                                "Твоя активность, поддержка других мам и желание расти вдохновляют всех нас.\n\n"
                                "Мы видим, как ты меняешься, развиваешься и становишься еще более уверенной в себе. "
                                "Это невероятно ценно, и я горжусь тобой! 🎀\n\n"
                                "Спасибо за твою преданность и доверие. Продолжай сиять, красотка! Мы всегда рядом! ✨"
                            ),
                            365: (
                                "🏆 КРАСОТКА, ЭТО НЕВЕРОЯТНО! 🏆\n\n"
                                "Ты с нами уже целый год — 365 дней вместе! Это не просто цифра, это настоящее достижение! 💍\n\n"
                                "За этот год ты прошла долгий путь. Ты стала неотъемлемой частью Mom's Club, "
                                "настоящей опорой для других мам и примером того, как можно расти, развиваться и оставаться собой.\n\n"
                                "Ты видела, как меняется клуб, как растет наше сообщество, и ты была частью этого пути. "
                                "Твоя преданность, поддержка и активность делают Mom's Club особенным местом.\n\n"
                                "Спасибо за этот год вместе, за твое доверие и за то, что ты выбрала нас. "
                                "Ты — настоящая жемчужина нашего клуба! 🩷\n\n"
                                "Продолжай сиять, красотка! Мы всегда рядом, чтобы поддержать тебя на каждом шагу! ✨💖"
                            )
                        }
                        
                        message_text = achievement_texts.get(milestone_days, f"🎉 Поздравляем! Ты с нами уже {milestone_days} дней! 🎉")
                        
                        keyboard = types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
                            ]
                        )
                        
                        await bot.send_message(
                            user.telegram_id,
                            message_text,
                            reply_markup=keyboard
                        )
                        
                        # Отмечаем, что уведомление отправлено
                        notification_type = f'milestone_{milestone_days}_days'
                        await create_subscription_notification(session, subscription.id, notification_type)
                        milestone_logger.info(f"Milestone-уведомление ({milestone_days} дней) отправлено пользователю {user.telegram_id}")
                    
                    except Exception as e:
                        milestone_logger.error(f"Ошибка при отправке milestone-уведомления пользователю {user.telegram_id}: {e}")
                        if 'bot was blocked by the user' in str(e) or 'USER_IS_BLOCKED' in str(e):
                            await mark_user_as_blocked(session, user.id)
                            milestone_logger.info(f"Пользователь {user.telegram_id} отмечен как заблокировавший бота")
            
            # Проверяем раз в день
            await asyncio.sleep(24 * 60 * 60)
            
        except Exception as e:
            milestone_logger.error(f"Ошибка в функции отправки milestone-уведомлений: {e}")
            await asyncio.sleep(60 * 60)  # Ждем час при ошибке


async def send_migration_notifications():
    """
    Отправляет уведомления о возврате на ЮКасy всем пользователям.
    Начисляет 3 бонусных дня за неудобство.
    """
    migration_logger = logging.getLogger('migration_notifications')
    migration_logger.info("Запуск задачи отправки миграционных уведомлений (возврат на ЮКасy)")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Получаем пользователей для отправки миграционного уведомления
                users = await get_users_for_migration_notification(
                    session, 
                    notification_window_days=MIGRATION_NOTIFICATION_SETTINGS['notification_window_days']
                )
                migration_logger.info(f"Найдено {len(users)} пользователей для отправки миграционного уведомления")
                
                for user in users:
                    try:
                        # Проверяем, не отправляли ли уже уведомление этому пользователю
                        from database.models import MigrationNotification
                        
                        existing_notification_query = select(MigrationNotification).where(
                            MigrationNotification.user_id == user.id,
                            MigrationNotification.notification_type == 'payment_system_migration'
                        )
                        existing_notification = await session.execute(existing_notification_query)
                        if existing_notification.fetchone():
                            migration_logger.info(f"Уведомление пользователю {user.telegram_id} уже отправлялось, пропускаем")
                            continue
                        
                        # Получаем активную подписку пользователя для даты окончания
                        from database.crud import get_active_subscription
                        from datetime import datetime, timedelta
                        
                        active_sub = await get_active_subscription(session, user.id)
                        
                        # НАЧИСЛЯЕМ 3 БОНУСНЫХ ДНЯ ЗА НЕУДОБСТВО
                        if active_sub and active_sub.end_date:
                            # Добавляем 3 дня
                            active_sub.end_date = active_sub.end_date + timedelta(days=3)
                            active_sub.updated_at = datetime.now()
                            session.add(active_sub)
                            await session.commit()
                            end_date_formatted = active_sub.end_date.strftime('%d.%m.%Y')
                            migration_logger.info(f"Добавлено 3 бонусных дня пользователю {user.telegram_id}. Новая дата: {end_date_formatted}")
                        else:
                            # Если нет активной подписки, используем текущую дату + 7 дней
                            end_date_formatted = (datetime.now() + timedelta(days=7)).strftime('%d.%m.%Y')
                            migration_logger.info(f"Пользователь {user.telegram_id} не имеет активной подписки")
                        
                        # Создаем инлайн-клавиатуру с кнопкой продления
                        keyboard = types.InlineKeyboardMarkup(
                            inline_keyboard=[
                                [types.InlineKeyboardButton(
                                    text="💳 Настроить новую оплату", 
                                    callback_data="migrate_subscribe"
                                )],
                                [types.InlineKeyboardButton(
                                    text="💬 Связаться с поддержкой", 
                                    url="https://t.me/polinadmitrenkoo"
                                )]
                            ]
                        )
                        
                        # Форматируем текст уведомления с датой окончания подписки
                        formatted_text = MIGRATION_NOTIFICATION_TEXT.format(end_date=end_date_formatted)
                        
                        # Отправляем уведомление
                        await bot.send_message(
                            chat_id=user.telegram_id,
                            text=formatted_text,
                            reply_markup=keyboard,
                            parse_mode='HTML'
                        )
                        
                        # Записываем уведомление в базу данных
                        await create_migration_notification(
                            session, 
                            user.id, 
                            'payment_system_migration'
                        )
                        await mark_migration_notification_sent(session, user.id, 'payment_system_migration')
                        
                        migration_logger.info(f"Миграционное уведомление отправлено пользователю {user.telegram_id}")
                        
                        # Небольшая пауза между отправками для избежания лимитов Telegram
                        await asyncio.sleep(1)
                    
                    except Exception as e:
                        migration_logger.error(f"Ошибка при отправке миграционного уведомления пользователю {user.telegram_id}: {e}")
                        # Проверяем, заблокировал ли пользователь бота
                        if 'bot was blocked by the user' in str(e) or 'USER_IS_BLOCKED' in str(e):
                            await mark_user_as_blocked(session, user.id)
                            migration_logger.info(f"Пользователь {user.telegram_id} отмечен как заблокировавший бота")
            
            # Проверяем каждые 12 часов согласно настройкам
            check_interval_hours = MIGRATION_NOTIFICATION_SETTINGS['check_interval_hours']
            await asyncio.sleep(check_interval_hours * 60 * 60)
            
        except Exception as e:
            migration_logger.error(f"Ошибка в функции отправки миграционных уведомлений: {e}")
            # В случае ошибки ждем 1 час перед повторной попыткой
            await asyncio.sleep(60 * 60)


async def send_scheduled_messages():
    """
    Проверяет и отправляет запланированные сообщения пользователям.
    """
    messages_logger = logging.getLogger('messages')
    messages_logger.info("Запуск задачи отправки запланированных сообщений")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                from database.crud import get_scheduled_messages_for_sending, get_unsent_recipients, update_recipient_status, mark_scheduled_message_as_sent
                
                # Получаем сообщения, которые пора отправить
                scheduled_messages = await get_scheduled_messages_for_sending(session)
                messages_logger.info(f"Найдено {len(scheduled_messages)} запланированных сообщений для отправки")
                
                for message in scheduled_messages:
                    # Получаем получателей, которым еще не отправлено сообщение
                    recipients = await get_unsent_recipients(session, message.id)
                    messages_logger.info(f"Сообщение ID {message.id}: {len(recipients)} получателей для отправки")
                    
                    for recipient in recipients:
                        try:
                            user_id = recipient.user.telegram_id
                            
                            # Если формат "Plain", то не используем parse_mode
                            parse_mode = None if message.format == "Plain" else message.format
                            
                            # Отправляем сообщение в зависимости от типа медиа
                            if message.media_type == "photo" and message.media_file_id:
                                await bot.send_photo(
                                    chat_id=user_id,
                                    photo=message.media_file_id,
                                    caption=message.text,
                                    parse_mode=parse_mode
                                )
                            elif message.media_type == "video" and message.media_file_id:
                                await bot.send_video(
                                    chat_id=user_id,
                                    video=message.media_file_id,
                                    caption=message.text,
                                    parse_mode=parse_mode
                                )
                            elif message.media_type == "videocircle" and message.media_file_id:
                                # Для видео-кружка текст отправляем отдельно
                                await bot.send_video_note(
                                    chat_id=user_id,
                                    video_note=message.media_file_id
                                )
                                if message.text:
                                    await bot.send_message(
                                        chat_id=user_id,
                                        text=message.text,
                                        parse_mode=parse_mode
                                    )
                            else:
                                # Только текст
                                await bot.send_message(
                                    chat_id=user_id,
                                    text=message.text,
                                    parse_mode=parse_mode
                                )
                            
                            # Обновляем статус отправки для получателя
                            await update_recipient_status(session, recipient.id, True)
                            messages_logger.info(f"Сообщение успешно отправлено пользователю {user_id}")
                            
                        except Exception as e:
                            error_message = str(e)
                            messages_logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
                            
                            # Упрощаем сообщение об ошибке для записи в базу
                            if "bot was blocked" in error_message:
                                error_description = "Пользователь заблокировал бота"
                            elif "chat not found" in error_message:
                                error_description = "Чат с пользователем не найден"
                            elif "user is deactivated" in error_message:
                                error_description = "Аккаунт пользователя деактивирован"
                            else:
                                error_description = error_message
                            
                            # Обновляем статус с ошибкой
                            await update_recipient_status(session, recipient.id, False, error_description)
                    
                    # Проверяем, всем ли отправлены сообщения
                    remaining_recipients = await get_unsent_recipients(session, message.id)
                    if not remaining_recipients:
                        # Если всем получателям отправлено сообщение, помечаем его как отправленное
                        await mark_scheduled_message_as_sent(session, message.id)
                        messages_logger.info(f"Запланированное сообщение ID {message.id} полностью отправлено")
            
            # Проверяем раз в минуту
            await asyncio.sleep(60)
            
        except Exception as e:
            messages_logger.error(f"Ошибка в функции отправки запланированных сообщений: {e}")
            # В случае ошибки ждем 5 минут перед повторной попыткой
            await asyncio.sleep(300)


# Точка входа в приложение
async def main():
    # Регистрация обработчиков
    # Важно сначала зарегистрировать админские обработчики,
    # чтобы они имели приоритет перед пользовательскими
    # Базовое меню админки и общие колбэки
    register_admin_core_handlers(dp)
    # Модуль реферальных связей админки
    register_admin_referrals_handlers(dp)
    # Модуль сроков подписок
    register_admin_subscriptions_handlers(dp)
    # Модуль промокодов
    register_admin_promocodes_handlers(dp)
    # Модуль рассылки сообщений удалён из админки по требованиям
    # ВАЖНО: Модуль поиска и карточки пользователя регистрируем ПЕРЕД лояльностью,
    # чтобы обработчики admin_user_info имели приоритет над обработчиками лояльности
    register_admin_users_handlers(dp)
    # Модуль системы лояльности
    register_admin_loyalty_handlers(dp)
    # Модуль заявок на отмену автопродления
    register_admin_cancellations_handlers(dp)
    # Модуль дней рождения пользователей
    register_admin_birthdays_handlers(dp)
    # Модуль управления админами (регистрируем ПЕРЕД core, чтобы обработчики имели приоритет)
    register_admin_admins_handlers(dp)
    register_user_handlers(dp)
    register_message_handlers(dp)
    
    # Создаем и запускаем менеджер группы
    group_manager = GroupManager(bot)
    
    # Регистрируем обработчик присоединения пользователей к группе
    group_manager.register_join_handler(dp)
    
    # Запускаем мониторинг подписок
    asyncio.create_task(group_manager.start_monitoring())
    
    # Запускаем задачу для поздравления с днем рождения
    asyncio.create_task(congratulate_birthdays())

    # Запускаем задачу для отправки напоминаний
    asyncio.create_task(send_payment_reminders())
    
    # Запускаем ночной крон для системы лояльности
    asyncio.create_task(loyalty_nightly_job())
    
    # Миграционные уведомления включены (возврат на ЮКасy с бонусом 3 дня)
    asyncio.create_task(send_migration_notifications())
    
    # Запускаем задачу для отправки уведомлений об истекших подписках ("мы скучаем")
    asyncio.create_task(send_expired_subscription_reminders())
    
    # Запускаем задачу для отправки milestone-уведомлений (100, 180, 365 дней)
    asyncio.create_task(send_milestone_notifications())
    
    # Запускаем задачу для отправки запланированных сообщений
    asyncio.create_task(send_scheduled_messages())
    
    # Запускаем сервер вебхуков ЮКассы
    webhook_server_task = asyncio.create_task(run_webhook_server())

    # Пропускаем накопившиеся апдейты и запускаем polling
    try:
        await bot.delete_webhook(drop_pending_updates=True) # Это для aiogram, чтобы он не пытался использовать вебхук
        logging.info("Aiogram бот запускается в режиме polling...")
        await dp.start_polling(bot)
    finally:
        logging.info("Останавливаем сервер вебхуков...")
        webhook_server_task.cancel() 
        # Дожидаемся завершения всех задач, включая автопродление
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logging.info("Все фоновые задачи остановлены.")


if __name__ == "__main__":
    try:
        logging.info("Бот запущен")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Получен сигнал остановки, завершаю работу...")
        # Явное завершение работы диспетчера не всегда требуется в aiogram 3+, 
        # так как asyncio.run() должен обрабатывать завершение задач.
        # Однако, если проблемы с Unclosed session сохраняются, можно попробовать:
        # loop = asyncio.get_running_loop()
        # tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task(loop)]
        # [task.cancel() for task in tasks]
        # await asyncio.gather(*tasks, return_exceptions=True)
        # await dp.storage.close() # Если используется хранилище
        # await dp.fsm.storage.close() # Если используется FSM хранилище
        # await bot.session.close() # Закрытие сессии бота
        logging.info("Бот остановлен")
    except Exception as e:
        logging.error(f"Непредвиденная ошибка: {e}", exc_info=True)