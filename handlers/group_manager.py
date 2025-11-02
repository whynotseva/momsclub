import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, types
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from database.config import AsyncSessionLocal
from database.crud import get_all_expired_subscriptions, get_expiring_soon_subscriptions, get_user_by_id, deactivate_subscription, get_user_by_telegram_id, has_active_subscription, has_welcome_sent, mark_welcome_sent, create_subscription_notification
from utils.constants import CLUB_GROUP_ID, NOTIFICATION_DAYS_BEFORE, CLUB_CHANNEL_URL, SUBSCRIPTION_PRICE, CLUB_GROUP_TOPIC_ID, SUBSCRIPTION_DAYS, SUBSCRIPTION_PRICE_2MONTHS, SUBSCRIPTION_PRICE_3MONTHS, ADMIN_IDS
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройка логирования
logger = logging.getLogger(__name__)

class GroupManager:
    """
    Класс для управления участниками закрытой группы
    """
    def __init__(self, bot: Bot):
        self.bot = bot
        self.group_id = CLUB_GROUP_ID
        self.topic_id = CLUB_GROUP_TOPIC_ID
        logger.info(f"Инициализирован GroupManager для группы {self.group_id}, тема {self.topic_id}")

    async def is_member(self, user_id: int) -> bool:
        """
        Проверяет, является ли пользователь участником группы
        """
        try:
            member = await self.bot.get_chat_member(self.group_id, user_id)
            is_member = member.status not in ["left", "kicked"]
            logger.info(f"Проверка членства пользователя {user_id}: {is_member}")
            return is_member
        except Exception as e:
            logger.error(f"Ошибка при проверке членства пользователя {user_id}: {e}")
            return False

    async def kick_user(self, user_id: int) -> bool:
        """
        Исключает пользователя из группы
        """
        try:
            # Пробуем исключить участника
            await self.bot.ban_chat_member(self.group_id, user_id)
            # Сразу разбаниваем, чтобы пользователь мог вернуться, если продлит подписку
            await self.bot.unban_chat_member(self.group_id, user_id, only_if_banned=True)
            logger.info(f"Пользователь {user_id} исключен из группы {self.group_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при исключении пользователя {user_id}: {e}")
            return False

    async def check_expired_subscriptions(self):
        """
        Проверяет истекшие подписки и исключает пользователей из группы
        """
        logger.info("--- Запущена проверка check_expired_subscriptions ---")
        kicked_in_this_run = 0
        errors_in_this_run = 0
        kicked_users = []  # Список для сбора информации о выкинутых пользователях
        
        async with AsyncSessionLocal() as session:
            try:
                expired_subs = await get_all_expired_subscriptions(session)
                logger.info(f"Найдено {len(expired_subs)} истекших подписок (is_active=True, end_date <= now)")
            except Exception as e:
                logger.error(f"Ошибка при вызове get_all_expired_subscriptions: {e}", exc_info=True)
                return

            for sub in expired_subs:
                logger.debug(f"Обработка истекшей подписки ID: {sub.id}, User ID: {sub.user_id}, End date: {sub.end_date}")
                user = None
                try:
                    user = await get_user_by_id(session, sub.user_id)
                    if not user:
                        logger.warning(f"Пользователь с ID {sub.user_id} для подписки {sub.id} не найден в БД. Пропускаем.")
                        continue
                    
                    logger.debug(f"Найден пользователь: TG_ID={user.telegram_id}, DB_ID={user.id}")

                    # Проверяем, является ли он участником группы
                    logger.debug(f"Проверка членства для TG_ID={user.telegram_id}...")
                    is_member = await self.is_member(user.telegram_id)
                    logger.info(f"Результат проверки членства для TG_ID={user.telegram_id}: {is_member}")
                    
                    if is_member:
                        logger.info(f"Пользователь TG_ID={user.telegram_id} является участником группы. Попытка исключения...")
                        # Если да, исключаем его
                        kicked = await self.kick_user(user.telegram_id)
                        logger.info(f"Результат kick_user для TG_ID={user.telegram_id}: {kicked}")
                        
                        if kicked:
                            kicked_in_this_run += 1
                            
                            # Добавляем пользователя в список выкинутых для уведомления админам
                            user_info = {
                                "telegram_id": user.telegram_id,
                                "username": user.username,
                                "first_name": user.first_name,
                                "last_name": user.last_name,
                                "subscription_end": sub.end_date
                            }
                            kicked_users.append(user_info)
                            
                            # Деактивируем подписку в базе, если еще активна
                            if sub.is_active:
                                logger.debug(f"Деактивация подписки ID: {sub.id} для TG_ID={user.telegram_id}")
                                await deactivate_subscription(session, sub.id)
                                logger.info(f"Подписка ID: {sub.id} деактивирована.")
                                
                            # Отправляем уведомление об исключении
                            try:
                                # --- Новый текст ---
                                if user.is_recurring_active and user.yookassa_payment_method_id:
                                    msg = (
                                        "💖 Mom's Club напоминает! 💖\n\n"
                                        "Ваша подписка завершилась, но у вас включено автопродление.\n"
                                        "В течение суток будет предпринята попытка автоматического списания оплаты для продления доступа к клубу.\n\n"
                                        "Если хотите отменить автопродление — сделайте это в личном кабинете."
                                    )
                                else:
                                    msg = (
                                        "💔 Подписка в Mom's Club завершилась 💔\n\n"
                                        "Доступ к клубу временно приостановлен. Чтобы снова быть с нами — продлите подписку, нажав на кнопку ниже!\n\n"
                                        "Мы всегда рады видеть вас в нашем уютном клубе мам! 💖"
                                    )
                                keyboard = InlineKeyboardMarkup(
                                    inline_keyboard=[
                                        [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="renew_subscription")]
                                    ]
                                )
                                await self.bot.send_message(
                                    user.telegram_id,
                                    msg,
                                    reply_markup=keyboard
                                )
                                logger.info(f"Отправлено уведомление пользователю {user.telegram_id} об исключении")
                            except Exception as e_notify:
                                logger.error(f"Ошибка при отправке уведомления об исключении пользователю {user.telegram_id}: {e_notify}")
                                errors_in_this_run += 1 # Считаем как ошибку
                        else:
                            logger.error(f"Не удалось исключить пользователя TG_ID={user.telegram_id} (kick_user вернул False)")
                            errors_in_this_run += 1
                    else:
                        logger.info(f"Пользователь TG_ID={user.telegram_id} уже не является участником группы.")
                        # Если пользователь уже не в группе, просто деактивируем подписку
                        if sub.is_active:
                            logger.debug(f"Деактивация подписки {sub.id} для пользователя {user.telegram_id} (не в группе)")
                            await deactivate_subscription(session, sub.id)
                            logger.info(f"Подписка ID: {sub.id} деактивирована (пользователь не в группе).")
                           
                except Exception as e_user_loop:
                    logger.error(f"Непредвиденная ошибка при обработке подписки ID={sub.id} для пользователя user.id={sub.user_id}: {e_user_loop}", exc_info=True)
                    errors_in_this_run += 1
                    if user: # Логируем TG_ID если успели получить пользователя
                        logger.error(f"Ошибка произошла при обработке пользователя TG_ID={user.telegram_id}")
        
        # Отправляем уведомление админам о выкинутых пользователях, если они есть
        if kicked_users and ADMIN_IDS:
            try:
                # Формируем список пользователей для уведомления
                users_list = ""
                for i, user_info in enumerate(kicked_users, 1):
                    username = f"@{user_info['username']}" if user_info['username'] else "нет username"
                    name = f"{user_info['first_name'] or ''} {user_info['last_name'] or ''}".strip() or "Без имени"
                    end_date = user_info['subscription_end'].strftime("%d.%m.%Y")
                    users_list += f"{i}. {name} ({username}), ID: {user_info['telegram_id']}, подписка до: {end_date}\n"
                
                # Формируем и отправляем уведомление для админов
                admin_message = (
                    f"⚠️ <b>Автоматическое исключение пользователей</b>\n\n"
                    f"Следующие пользователи были исключены из группы из-за истекшей подписки:\n\n"
                    f"{users_list}\n"
                    f"Всего исключено: {kicked_in_this_run}"
                )
                
                for admin_id in ADMIN_IDS:
                    try:
                        await self.bot.send_message(admin_id, admin_message, parse_mode="HTML")
                    except Exception as e_admin:
                        logger.error(f"Ошибка при отправке уведомления админу {admin_id} о исключенных пользователях: {e_admin}")
            except Exception as e_notify:
                logger.error(f"Ошибка при формировании/отправке уведомления админам об исключенных пользователях: {e_notify}")
                        
        logger.info(f"--- Проверка check_expired_subscriptions завершена. Исключено: {kicked_in_this_run}, Ошибок: {errors_in_this_run} ---")

    async def notify_expiring_subscriptions(self):
        """
        Уведомляет пользователей о скором окончании подписки
        """
        logger.info(f"Запущена проверка подписок, истекающих в ближайшие {NOTIFICATION_DAYS_BEFORE} дней")
        async with AsyncSessionLocal() as session:
            expiring_subs = await get_expiring_soon_subscriptions(session, NOTIFICATION_DAYS_BEFORE)
            logger.info(f"Найдено {len(expiring_subs)} подписок, истекающих скоро")

            for sub in expiring_subs:
                user = await get_user_by_id(session, sub.user_id)
                if user:
                    try:
                        end_date = sub.end_date.strftime("%d.%m.%Y")
                        days_left = (sub.end_date - datetime.now()).days
                        if days_left == 0:
                            notification_type = 'expiration_today'
                            time_text = "сегодня"
                        elif days_left == 1:
                            notification_type = 'expiration_tomorrow'
                            time_text = "завтра"
                        else:
                            notification_type = f'expiration_{days_left}_days'
                            time_text = f"через {days_left} дней"

                        # --- Новый текст ---
                        if user.is_recurring_active and user.payment_method_id:
                            # Автопродление включено
                            msg = (
                                "💖 Mom's Club напоминает! 💖\n\n"
                                f"Ваша подписка заканчивается {time_text} ({end_date}).\n"
                                "Завтра с вашей карты автоматически спишется оплата, чтобы вы не потеряли доступ к клубу и всем материалам.\n\n"
                                "Если хотите отменить автопродление — сделайте это в личном кабинете."
                            )
                        else:
                            # Автопродление выключено
                            msg = (
                                f"💔 Подписка в Mom's Club заканчивается {time_text} ({end_date})\n\n"
                                "Доступ к клубу будет приостановлен. Чтобы снова быть с нами — продлите подписку, нажав на кнопку ниже!\n\n"
                                "Мы всегда рады видеть вас в нашем уютном клубе мам! 💖"
                            )
                        keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text="💳 Продлить подписку", callback_data="renew_subscription")]
                            ]
                        )
                        await self.bot.send_message(
                            user.telegram_id,
                            msg,
                            reply_markup=keyboard
                        )
                        logger.info(f"Отправлено уведомление пользователю {user.telegram_id} о скором окончании подписки (тип: {notification_type})")
                        await create_subscription_notification(session, sub.id, notification_type)
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления пользователю {user.telegram_id}: {e}")

    async def start_monitoring(self):
        """
        Запускает периодический мониторинг подписок
        """
        logger.info("Запущен мониторинг подписок")
        while True:
            try:
                # Проверяем истекшие подписки
                await self.check_expired_subscriptions()
                
                # Уведомляем о подписках, которые скоро истекут
                await self.notify_expiring_subscriptions()
                
                # Ждем 1 час перед следующей проверкой
                await asyncio.sleep(3600)  # 1 час (ВОЗВРАЩЕНО НА ПРОДАШКЕН)
            except Exception as e:
                logger.error(f"Ошибка в процессе мониторинга: {e}")
                # Ждем 5 минут при ошибке
                await asyncio.sleep(300)
                
    async def send_message_to_topic(self, message_text: str, topic_id: int = None):
        """
        Отправляет сообщение в конкретную тему группы
        
        Args:
            message_text (str): Текст сообщения для отправки
            topic_id (int, optional): ID темы. Если None, используется ID темы из настроек.
            
        Returns:
            bool: True если сообщение успешно отправлено, False в случае ошибки
        """
        try:
            # Если topic_id не указан, используем значение из класса
            if topic_id is None:
                topic_id = self.topic_id
                
            # Отправляем сообщение с указанием message_thread_id для конкретной темы
            await self.bot.send_message(
                chat_id=self.group_id,
                text=message_text,
                message_thread_id=topic_id
            )
            logger.info(f"Сообщение успешно отправлено в группу {self.group_id}, тема {topic_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения в группу {self.group_id}, тему {topic_id}: {e}")
            return False
            
    async def get_group_topics(self):
        """
        Получает список всех тем в группе
        
        Returns:
            list: Список тем в группе или None в случае ошибки
        """
        try:
            # Получаем информацию о форуме
            forum_info = await self.bot.get_forum_topics(chat_id=self.group_id)
            logger.info(f"Получен список тем в группе {self.group_id}: {forum_info}")
            return forum_info
        except Exception as e:
            logger.error(f"Ошибка при получении списка тем группы {self.group_id}: {e}")
            return None
            
    async def welcome_user_to_group(self, user_id: int):
        """
        Отправляет приветственное сообщение пользователю в группе (в определенную тему)
        
        Args:
            user_id (int): Telegram ID пользователя
            
        Returns:
            bool: True если сообщение успешно отправлено, False в случае ошибки
        """
        try:
            async with AsyncSessionLocal() as session:
                user = await get_user_by_id(session, user_id)
                if not user:
                    logger.error(f"Пользователь с ID {user_id} не найден при отправке приветствия")
                    return False
                
                # Проверяем, отправлялось ли уже приветствие
                welcome_already_sent = await has_welcome_sent(session, user.id)
                if welcome_already_sent:
                    logger.info(f"Приветственное сообщение для пользователя {user.telegram_id} уже было отправлено ранее")
                    return False
                    
                # Формируем упоминание пользователя с @username, если username есть
                if user.username:
                    user_mention = f"@{user.username}"
                else:
                    user_mention = user.first_name or "Новый участник"
                    
                # Формируем приветственное сообщение с упоминанием
                welcome_text = (
                    f"{user_mention} привет, красотка, добро пожаловать в клуб 🩷\n"
                    f"Ознакомься со всеми закрепленными постами в чатах и знакомься с девочками "
                    f"(рассказывай о себе и оставляй ссылку на блог)"
                )
                
                # Отправляем сообщение в нужную тему
                result = await self.send_message_to_topic(welcome_text)
                
                if result:
                    logger.info(f"Приветственное сообщение отправлено пользователю {user.telegram_id} в группе")
                    
                    # Отмечаем, что приветствие отправлено
                    await mark_welcome_sent(session, user.id)
                    
                    return True
                else:
                    logger.error(f"Не удалось отправить приветственное сообщение пользователю {user.telegram_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"Ошибка при отправке приветственного сообщения пользователю {user_id}: {e}")
            return False

    def register_join_handler(self, router):
        """
        Регистрирует обработчик события присоединения к группе
        
        Args:
            router: Роутер, к которому будет привязан обработчик
        """
        @router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
        async def on_user_join(event: types.ChatMemberUpdated):
            # Проверяем, что это событие из нашей группы
            if event.chat.id != self.group_id:
                return
                
            user_id = event.new_chat_member.user.id
            username = event.new_chat_member.user.username
            first_name = event.new_chat_member.user.first_name
            
            logger.info(f"Пользователь {user_id} (@{username}) присоединился к группе {self.group_id}")
            
            # Проверяем, есть ли у пользователя активная подписка
            async with AsyncSessionLocal() as session:
                # Получаем пользователя по Telegram ID
                user = await get_user_by_telegram_id(session, user_id)
                
                if not user:
                    logger.warning(f"Пользователь {user_id} не найден в базе данных")
                    return
                    
                # Проверяем наличие активной подписки
                has_subscription = await has_active_subscription(session, user.id)
                
                if has_subscription:
                    # Проверяем, отправлялось ли уже приветствие пользователю
                    welcome_already_sent = await has_welcome_sent(session, user.id)
                    
                    if not welcome_already_sent:
                        # Если приветствие еще не отправлялось, отправляем его
                        await self.welcome_user_to_group(user.id)
                    else:
                        logger.info(f"Приветствие для пользователя {user_id} уже было отправлено ранее")
                else:
                    logger.warning(f"Пользователь {user_id} присоединился к группе без активной подписки")
                    # Кикаем пользователя, так как у него нет активной подписки
                    await self.kick_user(user_id)
                    
        logger.info("Обработчик события присоединения к группе зарегистрирован") 