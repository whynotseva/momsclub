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
from handlers.admin_handlers import register_admin_handlers
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
    mark_migration_notification_sent
)
from database.config import AsyncSessionLocal
from database.models import PaymentLog
from datetime import datetime, timedelta
from utils.constants import ADMIN_IDS, MIGRATION_NOTIFICATION_SETTINGS, MIGRATION_NOTIFICATION_TEXT
import time
from sqlalchemy import update, select

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot.log',
    filemode='a'
)

# Создаем отдельный логгер для платежей
payment_logger = logging.getLogger('payments')
payment_logger.setLevel(logging.DEBUG)

# Добавим файловый хендлер для платежных логов
payment_file_handler = logging.FileHandler('payment_logs.log')
payment_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
payment_logger.addHandler(payment_file_handler)

# Создаем отдельный логгер для дней рождения
birthday_logger = logging.getLogger('birthdays')
birthday_logger.setLevel(logging.DEBUG)

# Добавляем файловый хендлер для логов дней рождения
birthday_file_handler = logging.FileHandler('birthday_logs.log')
birthday_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
birthday_logger.addHandler(birthday_file_handler)

# Создаем отдельный логгер для напоминаний
reminder_logger = logging.getLogger('reminders')
reminder_logger.setLevel(logging.INFO)
# Можно добавить отдельный файловый хендлер, если нужно
# reminder_file_handler = logging.FileHandler('reminder_logs.log')
# reminder_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
# reminder_logger.addHandler(reminder_file_handler)

# Консольный хендлер для всех логов
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger('').addHandler(console_handler)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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


async def send_migration_notifications():
    """
    ОТКЛЮЧЕНО: Функция использовалась для миграции с ЮКассы на Prodamus.
    Теперь система работает на ЮКассе, уведомления не требуются.
    """
    return  # Функция отключена
    migration_logger = logging.getLogger('migration_notifications')
    migration_logger.info("Запуск задачи отправки миграционных уведомлений")
    
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
                        
                        # Получаем активную подписку пользователя для даты окончания
                        from database.crud import get_active_subscription
                        active_sub = await get_active_subscription(session, user.id)
                        
                        if active_sub and active_sub.end_date:
                            end_date_formatted = active_sub.end_date.strftime('%d.%m.%Y')
                        else:
                            # Если нет активной подписки, используем текущую дату + 7 дней
                            from datetime import datetime, timedelta
                            end_date_formatted = (datetime.now() + timedelta(days=7)).strftime('%d.%m.%Y')
                        
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
    register_admin_handlers(dp)
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
    
    # Миграционные уведомления отключены (возврат на ЮКассу)
    # asyncio.create_task(send_migration_notifications())
    
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