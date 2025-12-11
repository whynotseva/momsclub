from sqlalchemy import select, func, update, and_, or_, exists, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, case, desc
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, date
from database.models import User, Subscription, PaymentLog, PromoCode, UserPromoCode, SubscriptionNotification, MessageTemplate, ScheduledMessage, ScheduledMessageRecipient, AutorenewalCancellationRequest, UserBadge, LoyaltyEvent, MigrationNotification, GroupActivity, FavoriteUser
from utils.constants import RETURN_PROMO_CONFIG
import random
import string
import logging
from typing import Optional, List, Tuple
from utils.constants import ADMIN_IDS
from sqlalchemy.exc import IntegrityError
from database.config import get_db

# Получаем логгер на уровне модуля
logger = logging.getLogger(__name__)

# Функции для работы с пользователями
async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int):
    """Получает пользователя по Telegram ID"""
    query = select(User).where(User.telegram_id == telegram_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def get_user_by_id(db: AsyncSession, user_id: int):
    """Получает пользователя по ID в базе данных"""
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def create_user(db: AsyncSession, telegram_id: int, username: str = None, first_name: str = None, last_name: str = None, phone: str = None):
    """Создает нового пользователя"""
    now = datetime.now()
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        created_at=now,  # Явно устанавливаем created_at при создании
        updated_at=now   # Явно устанавливаем updated_at при создании
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"Создан новый пользователь: telegram_id={telegram_id}, username={username}, created_at={now}")
    return user

async def sync_user_data(db: AsyncSession, user: User, username: str = None, first_name: str = None, last_name: str = None, phone: str = None):
    """
    Синхронизирует данные пользователя с актуальными данными из Telegram.
    Обновляет только те поля, которые изменились.
    
    Args:
        db: Сессия базы данных
        user: Объект пользователя, который нужно обновить
        username: Новый username из Telegram
        first_name: Новое имя пользователя
        last_name: Новая фамилия пользователя
        phone: Новый телефон пользователя
        
    Returns:
        Обновленный объект пользователя
    """
    updates = {}
    
    # Проверяем, изменился ли username
    if username is not None and user.username != username:
        updates['username'] = username
        logger.info(f"Обновляем username пользователя ID {user.id} с '{user.username}' на '{username}'")
    
    # Проверяем, изменилось ли имя
    if first_name is not None and user.first_name != first_name:
        updates['first_name'] = first_name
    
    # Проверяем, изменилась ли фамилия
    if last_name is not None and user.last_name != last_name:
        updates['last_name'] = last_name
    
    # Проверяем, изменился ли телефон
    if phone is not None and user.phone != phone:
        updates['phone'] = phone
    
    # Если есть изменения, обновляем пользователя
    if updates:
        query = update(User).where(User.id == user.id).values(**updates)
        await db.execute(query)
        await db.commit()
        await db.refresh(user)
        logger.info(f"Данные пользователя ID {user.id} (TG ID: {user.telegram_id}) обновлены")
    
    return user

async def get_or_create_user(db: AsyncSession, telegram_id: int, username: str = None, first_name: str = None, last_name: str = None, phone: str = None):
    """Получает существующего пользователя или создает нового"""
    user = await get_user_by_telegram_id(db, telegram_id)
    
    if not user:
        user = await create_user(db, telegram_id, username, first_name, last_name, phone)
    else:
        # Если пользователь существует, синхронизируем его данные
        user = await sync_user_data(db, user, username, first_name, last_name, phone)
    
    return user

async def update_user(db: AsyncSession, telegram_id: int, **kwargs):
    """Обновляет данные пользователя"""
    query = update(User).where(User.telegram_id == telegram_id).values(**kwargs)
    await db.execute(query)
    await db.commit()
    
    return await get_user_by_telegram_id(db, telegram_id)

async def set_user_birthday(db: AsyncSession, user_id: int, birthday: date):
    """Устанавливает или обновляет дату рождения пользователя."""
    try:
        query = update(User).where(User.id == user_id).values(birthday=birthday)
        await db.execute(query)
        await db.commit()
        logger.info(f"Дата рождения {birthday} установлена для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при установке даты рождения для пользователя {user_id}: {e}")
        return False

async def get_users_for_birthday_congratulation(db: AsyncSession) -> List[User]:
    """Получает список пользователей с активной подпиской, у которых сегодня ДР 
       и подарок в этом году еще не выдан."""
    today = datetime.now().date()
    current_year = today.year

    # Выбираем пользователей, у которых:
    # 1. Есть дата рождения (User.birthday IS NOT NULL)
    # 2. Месяц и день рождения совпадают с сегодняшним (strftime('%m-%d', User.birthday) == today.strftime('%m-%d'))
    # 3. Год выдачи подарка не равен текущему году ИЛИ год выдачи подарка IS NULL (User.birthday_gift_year != current_year OR User.birthday_gift_year IS NULL)
    # 4. Есть хотя бы одна активная подписка (EXISTS (SELECT 1 FROM subscriptions WHERE subscriptions.user_id = users.id AND subscriptions.is_active = TRUE AND subscriptions.end_date > NOW()))
    
    # Подзапрос для проверки активной подписки
    active_sub_exists = (
        select(Subscription.id)
        .where(
            Subscription.user_id == User.id,
            Subscription.is_active == True,
            Subscription.end_date > func.now() # func.now() для сравнения с DateTime полем
        )
        .exists()
    )

    query = (
        select(User)
        .where(
            User.birthday.isnot(None),
            func.strftime('%m-%d', User.birthday) == today.strftime('%m-%d'),
            or_(
                User.birthday_gift_year != current_year,
                User.birthday_gift_year.is_(None)
            ),
            active_sub_exists
        )
    )
    
    result = await db.execute(query)
    users = result.scalars().all()
    logger.info(f"Найдено {len(users)} пользователей для поздравления с ДР сегодня ({today.strftime('%d.%m')})")
    return users

async def update_birthday_gift_year(db: AsyncSession, user_id: int, year: int):
    """Обновляет год, в котором был выдан подарок на ДР."""
    try:
        query = update(User).where(User.id == user_id).values(birthday_gift_year=year)
        await db.execute(query)
        await db.commit()
        logger.info(f"Год подарка на ДР ({year}) обновлен для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при обновлении года подарка на ДР для пользователя {user_id}: {e}")
        return False

# Функции для работы с подписками
async def create_subscription(db: AsyncSession, 
                              user_id: int, 
                              end_date: datetime, 
                              price: int, 
                              payment_id: str = None,
                              renewal_price: Optional[int] = None,
                              renewal_duration_days: Optional[int] = None,
                              subscription_id: Optional[str] = None):
    """Создает новую подписку для пользователя, ПРОВЕРЯЯ наличие активной."""
    # Проверяем, нет ли уже активной подписки
    existing_active_sub = await get_active_subscription(db, user_id)
    if existing_active_sub:
        logger.warning(f"Попытка создать новую активную подписку для user_id={user_id}, хотя активная (ID: {existing_active_sub.id}) уже существует.")
        # Если активная подписка уже существует, не создаем новую, а возвращаем существующую.
        # Это поведение может потребовать пересмотра в зависимости от бизнес-логики.
        # Возможно, стоит обновить существующую, если параметры новой более выгодны или актуальны.
        return existing_active_sub

    # ВАЖНО: Деактивируем все старые подписки пользователя перед созданием новой
    # Это предотвращает дублирование и повторные списания при автопродлении
    deactivate_query = (
        update(Subscription)
        .where(
            and_(
                Subscription.user_id == user_id,
                Subscription.is_active == True
            )
        )
        .values(is_active=False)
    )
    result = await db.execute(deactivate_query)
    if result.rowcount > 0:
        logger.info(f"Деактивировано {result.rowcount} старых подписок для user_id={user_id} перед созданием новой")

    subscription = Subscription(
        user_id=user_id,
        end_date=end_date,
        price=price, # Цена этого конкретного создания/платежа
        payment_id=payment_id,
        is_active=True,
        renewal_price=renewal_price, # Цена для будущего автопродления
        renewal_duration_days=renewal_duration_days, # Длительность для будущего автопродления
        subscription_id=subscription_id # Добавляем subscription_id для Prodamus
    )
    
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription

async def get_active_subscription(db: AsyncSession, user_id: int):
    """Получает активную подписку пользователя"""
    now = datetime.now()
    query = (
        select(Subscription)
        .where(
            and_(
                Subscription.user_id == user_id,
                Subscription.is_active == True,
                Subscription.end_date > now
            )
        )
        .order_by(Subscription.end_date.desc())
        .limit(1)
    )
    
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def get_subscription_by_subscription_id(db: AsyncSession, subscription_id: str):
    """Получает подписку по subscription_id от Prodamus"""
    query = select(Subscription).where(Subscription.subscription_id == subscription_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def deactivate_expired_subscriptions(db: AsyncSession):
    """Деактивирует истекшие подписки"""
    now = datetime.now()
    query = (
        update(Subscription)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date <= now
            )
        )
        .values(is_active=False)
    )
    
    await db.execute(query)
    await db.commit()

async def extend_subscription(db: AsyncSession, 
                              user_id: int, 
                              days: int, 
                              price: int, 
                              payment_id: str = None,
                              renewal_price: Optional[int] = None, # Цена этого платежа, станет ценой автопродления
                              renewal_duration_days: Optional[int] = None, # Длительность этого платежа, станет длительностью автопродления
                              subscription_id: Optional[str] = None # Добавляем subscription_id для Prodamus
                              ):
    """Продлевает подписку пользователя или создает новую, обновляя данные для автопродления."""
    active_subscription = await get_active_subscription(db, user_id)
    
    # Если renewal_price или renewal_duration_days не переданы явно,
    # используем price и days текущего платежа как основу для будущего автопродления.
    # Это важно, чтобы автопродление шло по условиям последнего оплаченного тарифа.
    actual_renewal_price = renewal_price if renewal_price is not None else price
    actual_renewal_duration_days = renewal_duration_days if renewal_duration_days is not None else days

    if active_subscription:
        # ПРОВЕРЯЕМ: если это миграция с Prodamus (есть subscription_id), 
        # а у существующей подписки НЕТ subscription_id, то это безопасная миграция
        is_safe_migration = (
            subscription_id is not None and 
            active_subscription.subscription_id is None
        )
        
        if is_safe_migration:
            # Безопасная миграция: обновляем старую подписку без subscription_id
            logger.info(f"Выполняется миграция подписки ID {active_subscription.id} для user_id {user_id} на Prodamus (subscription_id: {subscription_id})")
        
        # Если есть активная подписка, продлеваем её
        new_end_date = active_subscription.end_date + timedelta(days=days)
        update_values = {
            "end_date": new_end_date,
            "price": price,  # Обновляем цену подписки на цену текущего платежа
            "payment_id": payment_id, # Обновляем payment_id на ID текущего платежа
            "renewal_price": actual_renewal_price,
            "renewal_duration_days": actual_renewal_duration_days,
            "is_active": True # Убедимся, что она активна
        }
        
        # УМНАЯ ЛОГИКА: Автоматически сдвигаем автоплатеж на новую дату окончания
        if active_subscription.next_retry_attempt_at is not None:
            update_values["next_retry_attempt_at"] = new_end_date
            logger.info(
                f"Автоплатеж для подписки ID {active_subscription.id} "
                f"автоматически сдвинут на {new_end_date} (досрочное продление)"
            )
        
        # Добавляем subscription_id только если он передан (Prodamus)
        if subscription_id is not None:
            update_values["subscription_id"] = subscription_id
            
        query = (
            update(Subscription)
            .where(Subscription.id == active_subscription.id)
            .values(**update_values)
        )
        await db.execute(query)
        await db.commit()
        await db.refresh(active_subscription)
        
        if is_safe_migration:
            logger.info(f"Миграция завершена. Подписка ID {active_subscription.id} теперь управляется Prodamus (subscription_id: {subscription_id})")
        else:
            logger.info(f"Подписка ID {active_subscription.id} для user_id {user_id} продлена. Новая цена: {price}, цена автопродления: {actual_renewal_price} на {actual_renewal_duration_days} дней.")
        
        return active_subscription
    else:
        # Иначе создаем новую подписку
        end_date = datetime.now() + timedelta(days=days)
        logger.info(f"Создание новой подписки для user_id {user_id} через extend_subscription. Цена: {price}, автопродление: {actual_renewal_price} на {actual_renewal_duration_days} дней.")
        return await create_subscription(
            db, 
            user_id, 
            end_date, 
            price, # Цена этого первого платежа
            payment_id,
            renewal_price=actual_renewal_price, 
            renewal_duration_days=actual_renewal_duration_days,
            subscription_id=subscription_id # Передаем subscription_id для новых подписок
        )

# Функции для логирования платежей
async def create_payment_log(db: AsyncSession, user_id: int, amount: int, status: str, 
                            subscription_id: int = None, payment_method: str = None, 
                            transaction_id: str = None, details: str = None, 
                            payment_label: str = None, days: Optional[int] = None,
                            payment_datetime: Optional[datetime] = None,
                            admin_id: Optional[int] = None):
    """
    Создает запись о платеже в логе с дополнительной меткой платежа и количеством дней.
    
    Args:
        payment_datetime: Реальное время платежа от платежной системы (если доступно).
                         Если не указано, используется текущее время.
    """
    from datetime import datetime
    
    # Используем реальное время платежа, если передано
    if payment_datetime:
        # Если время с timezone, конвертируем в naive datetime (SQLite не поддерживает timezone)
        if payment_datetime.tzinfo is not None:
            # Конвертируем UTC в локальное время (MSK = UTC+3)
            try:
                import pytz
                msk_tz = pytz.timezone('Europe/Moscow')
                payment_datetime = payment_datetime.astimezone(msk_tz).replace(tzinfo=None)
            except ImportError:
                # Если pytz не установлен, просто убираем timezone
                payment_datetime = payment_datetime.replace(tzinfo=None)
        
        # Создаем объект с явно указанным created_at
        payment_log = PaymentLog(
            user_id=user_id,
            subscription_id=subscription_id,
            amount=amount,
            status=status,
            payment_method=payment_method,
            transaction_id=transaction_id,
            details=details,
            payment_label=payment_label,
            days=days,
            created_at=payment_datetime,
            admin_id=admin_id
        )
    else:
        # Используем текущее время (по умолчанию)
        payment_log = PaymentLog(
            user_id=user_id,
            subscription_id=subscription_id,
            amount=amount,
            status=status,
            payment_method=payment_method,
            transaction_id=transaction_id,
            details=details,
            payment_label=payment_label,
            days=days,
            admin_id=admin_id
        )
    
    db.add(payment_log)
    await db.commit()
    await db.refresh(payment_log)
    return payment_log

# Функции для получения статистики
async def get_total_users_count(db: AsyncSession):
    """Получает общее количество пользователей"""
    query = select(func.count(User.id))
    result = await db.execute(query)
    return result.scalar_one_or_none() or 0

async def get_active_subscriptions_count(db: AsyncSession):
    """Получает количество активных подписок (исключая пожизненные)"""
    now = datetime.now()
    # Пожизненные подписки имеют end_date в далеком будущем (36500 дней = ~100 лет)
    # Исключаем их из подсчета активных подписок
    lifetime_threshold = datetime(2099, 1, 1)  # Порог для пожизненных подписок
    query = select(func.count(Subscription.id)).where(
        and_(
            Subscription.is_active == True,
            Subscription.end_date > now,
            Subscription.end_date < lifetime_threshold  # Исключаем пожизненные
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none() or 0

async def get_expired_subscriptions_count(db: AsyncSession):
    """Получает количество истекших подписок"""
    now = datetime.now()
    query = select(func.count(Subscription.id)).where(
        and_(
            Subscription.is_active == False,
            Subscription.end_date <= now
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none() or 0

async def get_total_payments_amount(db: AsyncSession):
    """Получает общую сумму платежей"""
    query = select(func.sum(PaymentLog.amount)).where(PaymentLog.status == "success")
    result = await db.execute(query)
    return result.scalar_one_or_none() or 0

# Дополнительные функции для работы с платежами
async def get_payment_by_transaction_id(db: AsyncSession, transaction_id: str):
    """Получает запись о платеже по ID транзакции"""
    query = select(PaymentLog).where(PaymentLog.transaction_id == transaction_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def update_payment_status(db: AsyncSession, payment_id: int, status: str):
    """Обновляет статус платежа"""
    values = {"status": status}
    
    # Если статус успешный, устанавливаем флаг подтверждения
    if status == "success":
        values["is_confirmed"] = True
    
    query = (
        update(PaymentLog)
        .where(PaymentLog.id == payment_id)
        .values(**values)
    )
    await db.execute(query)
    await db.commit()
    
async def update_payment_subscription(db: AsyncSession, payment_id: int, subscription_id: int):
    """Обновляет привязку платежа к подписке"""
    query = (
        update(PaymentLog)
        .where(PaymentLog.id == payment_id)
        .values(subscription_id=subscription_id)
    )
    await db.execute(query)
    await db.commit()

# Функции для работы с истекшими подписками
async def get_all_expired_subscriptions(db: AsyncSession):
    """
    Получает все истекшие подписки, которые все еще активны
    """
    now = datetime.now()
    query = select(Subscription).where(
        and_(
            Subscription.is_active == True,
            Subscription.end_date <= now
        )
    )
    result = await db.execute(query)
    return result.scalars().all()

async def get_inactive_expired_subscriptions(db: AsyncSession):
    """
    Получает последние истекшие подписки для пользователей (даже если они неактивны)
    Используется для поиска пользователей с неактивными подписками, которые всё ещё в группе
    """
    from sqlalchemy import func, desc
    now = datetime.now()
    
    # Подзаwinner: получаем ID последней подписки для каждого пользователя
    subquery = (
        select(
            Subscription.user_id,
            func.max(Subscription.end_date).label('max_end_date')
        )
        .group_by(Subscription.user_id)
        .having(
            and_(
                func.max(Subscription.end_date) <= now,
                func.max(Subscription.end_date) <= datetime(2099, 1, 1)  # Не берем безлимитные (2125 год)
            )
        )
    ).subquery()
    
    # Получаем полные данные подписок с истекшими последними датами
    query = (
        select(Subscription)
        .join(
            subquery,
            and_(
                Subscription.user_id == subquery.c.user_id,
                Subscription.end_date == subquery.c.max_end_date
            )
        )
        .where(Subscription.is_active == False)  # Только неактивные подписки
        .where(Subscription.end_date <= datetime(2099, 1, 1))  # Исключаем безлимитные подписки (> 2099)
        .order_by(Subscription.end_date.desc())
    )
    
    result = await db.execute(query)
    return result.scalars().all()

async def get_expiring_soon_subscriptions(db: AsyncSession, days: int):
    """
    Получает подписки, которые истекают в ближайшие {days} дней
    и для которых еще не отправлялись соответствующие уведомления
    """
    now = datetime.now()
    future = now + timedelta(days=days)
    
    # Находим подписки, которые скоро истекают
    query = select(Subscription).where(
        and_(
            Subscription.is_active == True,
            Subscription.end_date > now,
            Subscription.end_date <= future
        )
    )
    
    result = await db.execute(query)
    expiring_subs = result.scalars().all()
    
    # Фильтруем подписки, для которых уже отправлены уведомления
    filtered_subs = []
    for sub in expiring_subs:
        days_left = (sub.end_date - now).days
        
        # Определяем тип уведомления для данной подписки
        if days_left == 0:
            notification_type = 'expiration_today'
        elif days_left == 1:
            notification_type = 'expiration_tomorrow'
        else:
            notification_type = f'expiration_{days_left}_days'
        
        # Проверяем, отправлялось ли уже уведомление этого типа
        notification = await get_subscription_notification(db, sub.id, notification_type)
        
        # Если уведомление этого типа еще не отправлялось, добавляем подписку в результат
        if not notification:
            filtered_subs.append(sub)
    
    return filtered_subs

async def deactivate_subscription(db: AsyncSession, subscription_id: int):
    """
    Деактивирует подписку по ID
    """
    query = (
        update(Subscription)
        .where(Subscription.id == subscription_id)
        .values(is_active=False)
    )
    await db.execute(query)
    await db.commit()

# Функция для получения пользователя по username
async def get_user_by_username(db: AsyncSession, username: str):
    """
    Получает пользователя по username.
    Если найдено несколько пользователей с одинаковым username (дубликаты),
    возвращает самого свежего (по updated_at).
    """
    query = (
        select(User)
        .where(User.username == username)
        .order_by(User.updated_at.desc())  # Самый свежий первым
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()

# Функции для экспорта пользователей

async def get_all_users_with_subscriptions(db: AsyncSession):
    """
    Получает всех пользователей с их подписками (активными или нет)
    Возвращает список кортежей (user, subscription)
    """
    # Получаем всех пользователей
    query = select(User).order_by(User.created_at.desc())
    result = await db.execute(query)
    users = result.scalars().all()
    
    # Для каждого пользователя получаем его последнюю подписку
    users_with_subs = []
    for user in users:
        try:
            # Получаем последнюю подписку пользователя
            sub_query = (
                select(Subscription)
                .where(Subscription.user_id == user.id)
                .order_by(Subscription.end_date.desc())
                .limit(1)
            )
            sub_result = await db.execute(sub_query)
            subscription = sub_result.scalar_one_or_none()  # Ожидаем одну запись или None
            
            # Добавляем кортеж (пользователь, подписка)
            users_with_subs.append((user, subscription))
        except Exception as e:
            # Логируем ошибку и пропускаем пользователя
            logging.error(f"Ошибка при получении подписки для пользователя {user.id}: {e}")
            # Всё равно добавляем пользователя, но без подписки
            users_with_subs.append((user, None))
    
    return users_with_subs

async def get_users_with_active_subscriptions(db: AsyncSession):
    """
    Получает всех пользователей с активными подписками
    Возвращает список кортежей (user, subscription)
    """
    now = datetime.now()
    
    # Получаем активные подписки
    query = select(Subscription).where(
        and_(
            Subscription.is_active == True,
            Subscription.end_date > now
        )
    ).order_by(Subscription.end_date.asc())
    
    result = await db.execute(query)
    active_subs = result.scalars().all()
    
    # Получаем пользователей для этих подписок
    users_with_subs = []
    for sub in active_subs:
        user_query = select(User).where(User.id == sub.user_id)
        user_result = await db.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if user:
            users_with_subs.append((user, sub))
    
    return users_with_subs

async def get_users_with_expired_subscriptions(db: AsyncSession):
    """
    Получает всех пользователей, у которых подписка истекла
    Возвращает список кортежей (user, subscription)
    """
    now = datetime.now()
    
    # Получаем истекшие подписки с уникальными user_id
    # Используем подзапрос, чтобы получить самую последнюю подписку каждого пользователя
    sub_query = (
        select(Subscription)
        .where(
            or_(
                Subscription.is_active == False,
                Subscription.end_date <= now
            )
        )
        .distinct(Subscription.user_id)
        .order_by(Subscription.user_id, Subscription.end_date.desc())
    )
    
    result = await db.execute(sub_query)
    expired_subs = result.scalars().all()
    
    # Получаем пользователей для этих подписок
    users_with_subs = []
    for sub in expired_subs:
        user_query = select(User).where(User.id == sub.user_id)
        user_result = await db.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if user:
            users_with_subs.append((user, sub))
    
    return users_with_subs

# Функция для генерации случайного реферального кода
def generate_referral_code(length=8):
    """Создает случайный реферальный код из цифр и букв"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# Функция для создания реферального кода
async def create_referral_code(db: AsyncSession, user_id: int):
    """Создает или обновляет реферальный код для пользователя"""
    user = await get_user_by_id(db, user_id)
    
    if not user:
        return None
    
    # Если у пользователя уже есть реферальный код, возвращаем его
    if user.referral_code:
        return user.referral_code
    
    # Генерируем уникальный код
    while True:
        code = generate_referral_code()
        # Проверяем, не занят ли этот код
        existing = await get_user_by_referral_code(db, code)
        if not existing:
            break
    
    # Обновляем пользователя с новым кодом
    query = (
        update(User)
        .where(User.id == user_id)
        .values(referral_code=code)
    )
    await db.execute(query)
    await db.commit()
    
    return code

# Функция для получения пользователя по реферальному коду
async def get_user_by_referral_code(db: AsyncSession, code: str):
    """Получает пользователя по реферальному коду"""
    query = select(User).where(User.referral_code == code)
    result = await db.execute(query)
    return result.scalar_one_or_none()

# Функция для обновления реферала
async def update_user_referrer(db: AsyncSession, user_id: int, referrer_id: int):
    """Устанавливает реферера для пользователя"""
    query = (
        update(User)
        .where(User.id == user_id)
        .values(referrer_id=referrer_id)
    )
    await db.execute(query)
    await db.commit()

# Функция для получения информации о реферере пользователя
async def get_referrer_info(session, user_id, bot=None):
    """
    Получает информацию о реферере пользователя.
    
    Args:
        session: Сессия БД
        user_id: ID пользователя, для которого нужно найти реферера
        bot: Объект бота для отправки сообщений (опционально)
        
    Returns:
        User: объект пользователя-реферера или None, если реферер не найден
    """
    from database.models import User
    
    logger = logging.getLogger(__name__)
    
    try:
        # Получаем информацию о текущем пользователе, чтобы узнать ID реферера
        user = await session.get(User, user_id)
        
        if not user:
            logger.info(f"Пользователь с ID {user_id} не найден при поиске реферера")
            return None
            
        if not user.referrer_id:
            logger.info(f"У пользователя {user_id} нет реферера (referrer_id=None)")
            return None
        
        logger.info(f"Найден referrer_id={user.referrer_id} для пользователя {user_id}")
        
        # Получаем данные реферера
        referrer = await session.get(User, user.referrer_id)
        
        if not referrer:
            logger.warning(f"Реферер с ID {user.referrer_id} не найден в базе данных")
            return None
            
        logger.info(f"Успешно получены данные реферера: ID {referrer.id}, telegram_id {referrer.telegram_id}")
        return referrer
    except Exception as e:
        logger.error(f"Ошибка при получении информации о реферере: {e}")
        return None

# Функция для проверки наличия активной подписки у пользователя
async def has_active_subscription(db: AsyncSession, user_id: int):
    """Проверяет, есть ли у пользователя активная подписка"""
    subscription = await get_active_subscription(db, user_id)
    return subscription is not None

# Функции для работы с реферальной системой

# async def get_referrer_info(session, user_id):
#     """
#     Получает информацию о реферере пользователя.
#     
#     Args:
#         session: Сессия БД
#         user_id: ID пользователя, для которого нужно найти реферера
#         
#     Returns:
#         User: объект пользователя-реферера или None, если реферер не найден
#     """
#     from database.models import User
#     
#     try:
#         # Получаем информацию о текущем пользователе, чтобы узнать ID реферера
#         user = await session.get(User, user_id)
#         
#         if not user or not user.referrer_id:
#             return None
#         
#         # Получаем данные реферера
#         referrer = await session.get(User, user.referrer_id)
#         return referrer
#     except Exception as e:
#         print(f"Ошибка при получении информации о реферере: {e}")
#         return None

# Функция для продления подписки на указанное количество дней (для реферальной программы)
async def extend_subscription_days(db: AsyncSession, user_id: int, days: int, reason: str = "referral_bonus"):
    """
    Продлевает подписку пользователя на указанное количество дней
    Возвращает True, если успешно, False в противном случае
    """
    # Используем глобальный логгер для платежей
    payment_logger = logging.getLogger("payments")
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Попытка продления подписки для пользователя {user_id} на {days} дней. Причина: {reason}")
        payment_logger.info(f"Начисление бонуса: пользователь {user_id}, +{days} дней, причина: {reason}")
        
        from database.models import User
        
        # Получаем пользователя
        user_query = select(User).where(User.id == user_id)
        user_result = await db.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"Не найден пользователь с ID {user_id} при продлении подписки")
            return False
            
        logger.info(f"Найден пользователь {user.id} (telegram_id: {user.telegram_id})")
        
        # Получаем активную подписку
        active_subscription = await get_active_subscription(db, user_id)
        
        if not active_subscription:
            logger.warning(f"У пользователя {user_id} нет активной подписки для продления")
            return False
        
        logger.info(f"Найдена активная подписка (ID: {active_subscription.id}) с датой окончания {active_subscription.end_date}")
        
        # Если есть активная подписка, продлеваем её
        new_end_date = active_subscription.end_date + timedelta(days=days)
        logger.info(f"Новая дата окончания подписки: {new_end_date}")
        
        query = (
            update(Subscription)
            .where(Subscription.id == active_subscription.id)
            .values(end_date=new_end_date)
        )
        await db.execute(query)
        await db.commit()
        
        # Логируем бонусное продление
        payment_log = PaymentLog(
            user_id=user_id,
            subscription_id=active_subscription.id,
            amount=0,  # Бесплатное продление
            status="success",
            payment_method="bonus",
            transaction_id=None,
            details=f"Бонусное продление на {days} дней. Причина: {reason}"
        )
        db.add(payment_log)
        await db.commit()
        
        logger.info(f"Успешно продлена подписка для пользователя {user_id}")
        payment_logger.info(f"Подписка успешно продлена: пользователь {user_id}, новая дата окончания {new_end_date}, причина: {reason}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при продлении подписки для пользователя {user_id}: {e}")
        payment_logger.error(f"Ошибка при начислении бонуса: пользователь {user_id}, дней: {days}, причина: {reason}, ошибка: {e}")
        await db.rollback()
        return False 

# Функция для отметки, что пользователю было отправлено приветственное сообщение
async def mark_welcome_sent(db: AsyncSession, user_id: int):
    """
    Отмечает, что пользователю было отправлено приветственное сообщение
    
    Args:
        db: Сессия базы данных
        user_id: ID пользователя в базе данных
    
    Returns:
        bool: True если успешно, False в противном случае
    """
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Отмечаем, что приветственное сообщение отправлено пользователю {user_id}")
        
        # Обновляем флаг welcome_sent пользователя
        query = (
            update(User)
            .where(User.id == user_id)
            .values(welcome_sent=True)
        )
        await db.execute(query)
        await db.commit()
        
        logger.info(f"Успешно отмечено, что приветственное сообщение отправлено пользователю {user_id}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при обновлении флага welcome_sent для пользователя {user_id}: {e}")
        await db.rollback()
        return False

# Функция для проверки, было ли отправлено приветственное сообщение пользователю
async def has_welcome_sent(db: AsyncSession, user_id: int):
    """
    Проверяет, было ли отправлено приветственное сообщение пользователю
    
    Args:
        db: Сессия базы данных
        user_id: ID пользователя в базе данных
    
    Returns:
        bool: True если отправлено, False в противном случае
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Получаем пользователя
        user_query = select(User).where(User.id == user_id)
        user_result = await db.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"Не найден пользователь с ID {user_id} при проверке welcome_sent")
            return False
        
        return user.welcome_sent
    except Exception as e:
        logger.error(f"Ошибка при проверке флага welcome_sent для пользователя {user_id}: {e}")
        return False 

async def get_payment_by_label(db: AsyncSession, payment_label: str) -> Optional[PaymentLog]:
    """Получает запись о платеже по метке платежа"""
    result = await db.execute(
        select(PaymentLog).filter(PaymentLog.payment_label == payment_label)
    )
    return result.scalars().first()

async def get_payment_by_id(db: AsyncSession, payment_db_id: int) -> Optional[PaymentLog]:
    """Получает запись о платеже по его ID в базе данных"""
    result = await db.execute(
        select(PaymentLog).filter(PaymentLog.id == payment_db_id)
    )
    return result.scalars().first()

async def get_user_payment_history(db: AsyncSession, user_id: int, limit: int = 20, only_confirmed: bool = True) -> List[PaymentLog]:
    """
    Получает историю платежей пользователя, отсортированную по дате (новые первыми).
    
    Args:
        db: Сессия БД
        user_id: ID пользователя в БД
        limit: Максимальное количество записей (по умолчанию 20)
        only_confirmed: Показывать только подтвержденные успешные платежи (по умолчанию True)
                       Если False, покажет все платежи включая pending и failed
        
    Returns:
        Список записей PaymentLog
    """
    # Фильтруем успешные платежи:
    # 1. Подтверждённые реальные платежи (is_confirmed = True)
    # 2. ИЛИ админские выдачи (payment_method = 'admin')
    # 3. ИЛИ оплата балансом (payment_method = 'referral_balance')
    # Исключаем тестовые платежи
    if only_confirmed:
        # Условие для исключения тестовых платежей
        not_test_condition = or_(
            PaymentLog.details.is_(None),
            and_(
                PaymentLog.details.notlike('%ТЕСТ%'),
                PaymentLog.details.notlike('%Тест%'),
                PaymentLog.details.notlike('%тест%'),
                PaymentLog.details.notlike('%ТЕСТОВЫЙ%'),
                PaymentLog.details.notlike('%Тестовый%'),
                PaymentLog.details.notlike('%тестовый%'),
                PaymentLog.details.notlike('%TEST%'),
                PaymentLog.details.notlike('%Test%'),
                PaymentLog.details.notlike('%test%')
            )
        )
        
        query = select(PaymentLog).where(
            and_(
                PaymentLog.user_id == user_id,
                PaymentLog.status == 'success',
                not_test_condition,
                # Подтверждённые ИЛИ админские ИЛИ оплата балансом
                or_(
                    PaymentLog.is_confirmed == True,
                    PaymentLog.payment_method == 'admin',
                    PaymentLog.payment_method == 'referral_balance'
                )
            )
        )
    else:
        query = select(PaymentLog).where(PaymentLog.user_id == user_id)
    
    query = query.order_by(PaymentLog.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    return list(result.scalars().all())

async def get_payment_by_prodamus_order_id(db: AsyncSession, prodamus_order_id: str) -> Optional[PaymentLog]:
    """Получает запись о платеже по order_id от Prodamus"""
    result = await db.execute(
        select(PaymentLog).filter(PaymentLog.prodamus_order_id == prodamus_order_id)
    )
    return result.scalars().first()

async def is_payment_processed(db: AsyncSession, payment_label: str) -> bool:
    """Проверяет, был ли платеж уже обработан"""
    result = await db.execute(
        select(PaymentLog)
        .filter(
            and_(
                PaymentLog.payment_label == payment_label,
                PaymentLog.status == "success",
                PaymentLog.is_confirmed == True
            )
        )
    )
    return result.scalars().first() is not None

async def mark_payment_as_processed(db: AsyncSession, payment_label: str) -> None:
    """Отмечает платеж как обработанный"""
    # Находим платеж по метке
    payment = await get_payment_by_label(db, payment_label)
    if payment:
        # Обновляем его статус
        payment.is_confirmed = True
        payment.status = "success"
        await db.commit()

async def update_subscription_end_date(db: AsyncSession, subscription_id: int, end_date: datetime) -> None:
    """Обновляет дату окончания подписки"""
    await db.execute(
        update(Subscription)
        .where(Subscription.id == subscription_id)
        .values(end_date=end_date)
    )
    await db.commit()

async def has_received_referral_bonus(db: AsyncSession, user_id: int) -> bool:
    """Проверяет, был ли выдан реферальный бонус за этого пользователя (по логам)"""
    result = await db.execute(
        select(exists().where(
            and_(
                PaymentLog.user_id == user_id, # Проверяем логи самого пользователя
                PaymentLog.payment_method == "bonus",
                PaymentLog.details.like(f"%referral_bonus_for_{user_id}%") # Ищем бонус, выданный рефереру ЗА этого пользователя
                # Или ищем бонус, выданный самому пользователю при регистрации (если такая логика есть)
                # or_(...)
            )
        ))
    )
    # Альтернативная проверка (если бонус начисляется рефереру):
    # Нужно найти запись в PaymentLog реферера, где details указывает на user_id реферала.
    # Это сложнее и требует знания referrer_id здесь.
    # Проще использовать has_received_referral_bonus для реферера перед начислением ему.
    # Оставляем текущую логику, предполагая, что она проверяет, был ли _какой-то_ реф. бонус связан с этим user_id.
    # Возможно, нужна более точная проверка.
    return result.scalar()

async def mark_referral_bonus_as_received(db: AsyncSession, user_id: int) -> None:
    """Отмечает, что реферальный бонус за пользователя был выдан."""
    # Эта функция может быть не нужна, если extend_subscription_days надежно создает
    # запись в PaymentLog с reason="referral_bonus...", которую проверяет
    # has_received_referral_bonus. Оставляем pass.
    logger.info(f"Вызов mark_referral_bonus_as_received для user_id={user_id}. Функция пока ничего не делает.")
    pass

async def has_user_paid_before(db: AsyncSession, user_id: int, current_payment_id: int) -> bool:
    """Проверяет, совершал ли пользователь успешные платежи ранее (исключая текущий платеж)"""
    query = select(exists().where(
        and_(
            PaymentLog.user_id == user_id,
            PaymentLog.status == "success",
            PaymentLog.is_confirmed == True,
            PaymentLog.id != current_payment_id # Исключаем текущий платеж
        )
    ))
    result = await db.execute(query)
    paid_before = result.scalar()
    logger.debug(f"Проверка has_user_paid_before для user_id={user_id} (исключая payment_id={current_payment_id}): {paid_before}")
    return paid_before

async def is_first_payment_by_user(db: AsyncSession, user_id: int, current_payment_id: int) -> bool:
    """Проверяет, является ли текущий платеж первым успешным платежом пользователя"""
    return not await has_user_paid_before(db, user_id, current_payment_id)

async def send_referral_bonus_notification(bot, user_id: int, referred_name: str, bonus_days: int) -> None:
    """Отправляет уведомление о начислении реферального бонуса"""
    logger = logging.getLogger(__name__)
    try:
        await bot.send_message(
            user_id,
            f"🎁 Вам начислен бонус за приглашение!\n\n"
            f"Пользователь {referred_name} оплатил подписку, и ваша подписка автоматически продлена на {bonus_days} дней."
            f"\n\nСпасибо за участие в программе приглашений Mom's Club! 💖",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о бонусе: {e}")

async def send_referee_bonus_notification(bot, user_id: int, referrer_name: str, bonus_days: int) -> None:
    """Отправляет уведомление приглашенному пользователю о получении реферального бонуса"""
    logger = logging.getLogger(__name__)
    try:
        await bot.send_message(
            user_id,
            (
                f"🎁 Вам начислен реферальный бонус!\n\n"
                f"Вы были приглашены пользователем {referrer_name}, и ваша подписка автоматически продлена на {bonus_days} дней.\n\n"
                f"Спасибо, что с нами в Mom's Club! 💖"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о бонусе рефералу: {e}")

async def send_payment_notification_to_admins(bot, user, payment, subscription, transaction_id):
    """Отправляет уведомление администраторам о новой оплате"""
    logger = logging.getLogger(__name__)
    try:
        # Для проверки первого платежа используем специальный запрос
        from sqlalchemy import select, exists, and_
        from utils.constants import (
            SUBSCRIPTION_PRICE,
            SUBSCRIPTION_PRICE_2MONTHS,
            SUBSCRIPTION_PRICE_3MONTHS
        )
        
        # Проверяем, есть ли другие успешные платежи у этого пользователя
        is_first_payment = True  # Предполагаем по умолчанию, что это первый платеж
        
        async for db in get_db():
            # Проверяем, есть ли другие успешные платежи для этого пользователя
            query = select(exists().where(
                and_(
                    PaymentLog.user_id == user.id,
                    PaymentLog.status == "success",
                    PaymentLog.is_confirmed == True,
                    PaymentLog.id != payment.id  # Исключаем текущий платеж
                )
            ))
            result = await db.execute(query)
            is_first_payment = not result.scalar()
            break  # Достаточно одной итерации
        
        # Формируем заголовок в зависимости от типа платежа
        if is_first_payment:
            payment_title = "💰 <b>Новый платеж!</b>"
            payment_subtitle = "✨ <b>Новый пользователь оформил подписку</b>"
        else:
            payment_title = "🔄 <b>Продление подписки!</b>"
            payment_subtitle = "👑 <b>Пользователь продлил подписку</b>"
        
        user_info = f"{user.first_name} {user.last_name or ''} (@{user.username})" if user.username else f"{user.first_name} {user.last_name or ''} (ID: {user.telegram_id})"
        
        # Определяем базовую цену по количеству дней
        days = subscription.renewal_duration_days or payment.days or 30
        if days <= 30:
            base_price = SUBSCRIPTION_PRICE
        elif days <= 60:
            base_price = SUBSCRIPTION_PRICE_2MONTHS
        elif days <= 90:
            base_price = SUBSCRIPTION_PRICE_3MONTHS
        else:
            # Для нестандартных периодов вычисляем пропорционально месячной цене
            base_price = int((days / 30) * SUBSCRIPTION_PRICE)
        
        # Получаем информацию о скидке
        discount_percent = subscription.loyalty_discount_percent or 0
        if discount_percent == 0 and user.lifetime_discount_percent > 0:
            discount_percent = user.lifetime_discount_percent
        
        final_price = payment.amount
        
        # Формируем строку с информацией о цене и скидке
        if discount_percent > 0 and final_price < base_price:
            price_info = (
                f"💵 Цена: <s>{base_price} руб.</s> {final_price} руб.\n"
                f"💰 Скидка: {discount_percent}% (постоянная скидка лояльности)"
            )
        else:
            price_info = f"💵 Сумма: {final_price} руб."
        
        # Добавляем информацию о реферале, если есть
        referral_info_line = ""
        if getattr(user, "referrer_id", None):
            try:
                # Получаем данные реферера
                async for db in get_db():
                    referrer = await get_user_by_id(db, user.referrer_id)
                    break
                if referrer:
                    ref_display = f"@{referrer.username}" if referrer.username else f"ID: {referrer.telegram_id}"
                    referral_info_line = f"🤝 Реферал: пригласил {ref_display}\n"
            except Exception as e:
                logger.warning(f"Не удалось получить данные реферера для admin push: {e}")

        # Маркер реферальной оплаты, если это первый платеж реферала
        referral_marker_line = ""
        if getattr(user, "referrer_id", None) and is_first_payment:
            referral_marker_line = "🤝 Оплата по реферальной программе\n"

        admin_notification = (
            f"{payment_title}\n\n"
            f"{payment_subtitle}\n"
            f"{referral_marker_line}"
            f"👤 Пользователь: {user_info}\n"
            f"{referral_info_line}"
            f"{price_info}\n"
            f"📆 Срок действия: до {subscription.end_date.strftime('%d.%m.%Y')}\n"
            f"🆔 ID транзакции: <code>{transaction_id}</code>\n\n"
            f"✅ Подписка успешно активирована!"
        )
        
        # Отправляем сообщение только тем администраторам, которые должны получать уведомления
        from utils.admin_permissions import can_receive_payment_notifications
        from database.crud import get_user_by_telegram_id
        
        # Получаем всех админов из базы (по группам и по старым ADMIN_IDS)
        admin_telegram_ids = set(ADMIN_IDS)  # Старые админы из константы
        
        # Добавляем админов из базы по группам
        from utils.constants import ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR
        async for db in get_db():
            query = select(User).where(
                User.admin_group.in_([ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR])
            )
            result = await db.execute(query)
            admin_users = result.scalars().all()
            for admin_user in admin_users:
                admin_telegram_ids.add(admin_user.telegram_id)
            break
        
        # Отправляем уведомления только тем, кто должен их получать
        for admin_id in admin_telegram_ids:
            try:
                async for db in get_db():
                    admin_user = await get_user_by_telegram_id(db, admin_id)
                    if admin_user and can_receive_payment_notifications(admin_user):
                        await bot.send_message(
                            admin_id,
                            admin_notification,
                            parse_mode="HTML"
                        )
                    break
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления администратору {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений администраторам: {e}")

async def send_promocode_notification_to_admins(bot, user, promo_code, subscription):
    """Отправляет уведомление администраторам об использовании промокода"""
    logger = logging.getLogger(__name__)
    try:
        user_info = f"{user.first_name} {user.last_name or ''} (@{user.username})" if user.username else f"{user.first_name} {user.last_name or ''} (ID: {user.telegram_id})"
        promo_info = f"Код: {promo_code.code}, Тип: {promo_code.discount_type}, Значение: {promo_code.value}"
        
        admin_notification = (
            f"🎁 <b>Использован промокод!</b>\n\n"
            f"👤 Пользователь: {user_info}\n"
            f"🎫 Промокод: {promo_info}\n"
            f"📆 Новый срок действия: до {subscription.end_date.strftime('%d.%m.%Y')}\n\n"
            f"✅ Подписка успешно обновлена/создана!"
        )
        
        # Отправляем уведомления только тем администраторам, которые должны их получать
        from utils.admin_permissions import can_receive_payment_notifications
        from utils.constants import ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR
        from sqlalchemy import select
        
        admin_telegram_ids = set(ADMIN_IDS)  # Старые админы из константы
        
        # Добавляем админов из базы по группам
        async for db in get_db():
            query = select(User).where(
                User.admin_group.in_([ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR])
            )
            result = await db.execute(query)
            admin_users = result.scalars().all()
            for admin_user in admin_users:
                admin_telegram_ids.add(admin_user.telegram_id)
            break
        
        # Отправляем уведомления только тем, кто должен их получать
        for admin_id in admin_telegram_ids:
            try:
                async for db in get_db():
                    admin_user = await get_user_by_telegram_id(db, admin_id)
                    if admin_user and can_receive_payment_notifications(admin_user):
                        await bot.send_message(
                            admin_id,
                            admin_notification,
                            parse_mode="HTML"
                        )
                    break
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о промокоде админу {admin_id}: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений о промокоде администраторам: {e}")


async def send_loyalty_benefit_notification_to_admins(bot, user, level: str, code: str, benefit_details: dict = None):
    """Отправляет уведомление администраторам о выборе бонуса лояльности"""
    logger = logging.getLogger(__name__)
    try:
        user_info = f"{user.first_name} {user.last_name or ''} (@{user.username})" if user.username else f"{user.first_name} {user.last_name or ''} (ID: {user.telegram_id})"
        
        # Названия уровней
        level_names = {
            'silver': 'Silver Mom ⭐',
            'gold': 'Gold Mom 🌟',
            'platinum': 'Platinum Mom 💍'
        }
        level_name = level_names.get(level, level)
        
        # Описание бонусов
        benefit_descriptions = {
            'days_7': '🎁 +7 дней доступа к клубу',
            'days_14': '🎁 +14 дней доступа к клубу',
            'days_30_gift': '🎁 +30 дней доступа + подарок',
            'discount_5': '💰 Постоянная скидка 5%',
            'discount_10': '💰 Постоянная скидка 10%',
            'discount_15_forever': '💎 Постоянная скидка 15%'
        }
        
        benefit_description = benefit_descriptions.get(code, f'Бонус: {code}')
        
        # Дополнительная информация
        details_text = ""
        if benefit_details:
            if 'days' in benefit_details:
                details_text = f"\n📅 Добавлено дней: {benefit_details['days']}"
            if 'discount_percent' in benefit_details:
                details_text = f"\n💰 Размер скидки: {benefit_details['discount_percent']}%"
        
        admin_notification = (
            f"🎁 <b>Выбор бонуса лояльности!</b>\n\n"
            f"👤 Пользователь: {user_info}\n"
            f"⭐ Уровень: {level_name}\n"
            f"🎁 Выбранный бонус: {benefit_description}{details_text}\n\n"
            f"✅ Бонус успешно применён!"
        )
        
        # Отправляем уведомления только тем администраторам, которые должны их получать
        from utils.admin_permissions import can_receive_payment_notifications
        from utils.constants import ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR
        from sqlalchemy import select
        
        admin_telegram_ids = set(ADMIN_IDS)  # Старые админы из константы
        
        # Добавляем админов из базы по группам
        async for db in get_db():
            query = select(User).where(
                User.admin_group.in_([ADMIN_GROUP_CREATOR, ADMIN_GROUP_DEVELOPER, ADMIN_GROUP_CURATOR])
            )
            result = await db.execute(query)
            admin_users = result.scalars().all()
            for admin_user in admin_users:
                admin_telegram_ids.add(admin_user.telegram_id)
            break
        
        # Отправляем уведомления только тем, кто должен их получать
        for admin_id in admin_telegram_ids:
            try:
                async for db in get_db():
                    admin_user = await get_user_by_telegram_id(db, admin_id)
                    if admin_user and can_receive_payment_notifications(admin_user):
                        await bot.send_message(
                            admin_id,
                            admin_notification,
                            parse_mode="HTML"
                        )
                    break
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о бонусе лояльности админу {admin_id}: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений о бонусе лояльности администраторам: {e}")

async def add_user_to_club_channel(bot, user_id: int) -> None:
    """Добавляет пользователя в закрытый канал/группу"""
    logger = logging.getLogger(__name__)
    logger.info(f"Функция add_user_to_club_channel вызвана для user_id {user_id}, но больше не генерирует временную ссылку.")
    # Дополнительная логика, если потребуется

# Функции для работы с промокодами

async def get_all_promo_codes(db: AsyncSession, limit: int = 100, offset: int = 0) -> list[PromoCode]:
    """Получает список всех промокодов с пагинацией"""
    query = select(PromoCode).order_by(PromoCode.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()

async def update_promo_code(db: AsyncSession, promo_id: int, **kwargs) -> Optional[PromoCode]:
    """
    Обновляет данные промокода по его ID.
    Принимает ID промокода и словарь с полями для обновления (kwargs).
    Например: update_promo_code(db, 1, is_active=False, max_uses=100)
    Возвращает обновленный объект PromoCode или None, если промокод не найден.
    """
    # Проверяем, существует ли промокод
    query = select(PromoCode).where(PromoCode.id == promo_id)
    result = await db.execute(query)
    promo_to_update = result.scalar_one_or_none()

    if not promo_to_update:
        logger.warning(f"Попытка обновить несуществующий промокод ID {promo_id}.")
        return None

    # Обновляем указанные поля
    update_query = (
        update(PromoCode)
        .where(PromoCode.id == promo_id)
        .values(**kwargs)
        .execution_options(synchronize_session="fetch") # Важно для обновления объекта
    )
    await db.execute(update_query)
    await db.commit()
    
    # Обновляем объект в сессии, чтобы вернуть актуальные данные
    await db.refresh(promo_to_update)
    logger.info(f"Промокод ID {promo_id} обновлен. Данные: {kwargs}")
    return promo_to_update

async def delete_promo_code_by_id(db: AsyncSession, promo_code_id: int) -> bool:
    """
    Удаляет промокод по его ID.
    Сначала удаляет все записи об использовании этого промокода (UserPromoCode),
    затем удаляет сам промокод.
    Возвращает True, если удаление прошло успешно, False в противном случае.
    """
    # 1. Находим промокод
    query_promo = select(PromoCode).where(PromoCode.id == promo_code_id)
    result_promo = await db.execute(query_promo)
    promo_code_to_delete = result_promo.scalar_one_or_none()

    if not promo_code_to_delete:
        logger.warning(f"Попытка удалить несуществующий промокод ID {promo_code_id}.")
        return False

    logger.info(f"Удаление промокода ID {promo_code_id} ({promo_code_to_delete.code})...")

    try:
        # 2. Находим и удаляем связанные записи UserPromoCode
        query_usage = select(UserPromoCode).where(UserPromoCode.promo_code_id == promo_code_id)
        result_usage = await db.execute(query_usage)
        usage_records = result_usage.scalars().all()

        if usage_records:
            logger.info(f"Найдено {len(usage_records)} записей об использовании промокода ID {promo_code_id}. Удаляем их...")
            for record in usage_records:
                await db.delete(record)
            # Можно сделать flush, чтобы выполнить удаления до удаления промокода,
            # но commit в конце должен справиться
            # await db.flush()
        else:
             logger.info(f"Записей об использовании промокода ID {promo_code_id} не найдено.")

        # 3. Удаляем сам промокод
        await db.delete(promo_code_to_delete)

        # 4. Коммитим все изменения (удаление usage_records и promo_code)
        await db.commit()
        logger.info(f"Промокод ID {promo_code_id} и связанные записи успешно удалены.")
        return True

    except Exception as e:
        logger.error(f"Ошибка при удалении промокода ID {promo_code_id} или связанных записей: {e}", exc_info=True)
        await db.rollback() # Откатываем транзакцию при ошибке
        return False

async def create_promo_code(
    db: AsyncSession, 
    code: str, 
    value: int, 
    discount_type: str = 'days', 
    max_uses: Optional[int] = None, 
    expiry_date: Optional[datetime] = None,
    is_active: bool = True
) -> Optional[PromoCode]:
    """Создает новый промокод"""
    # Проверяем, существует ли уже код
    existing_code = await get_promo_code_by_code(db, code)
    if existing_code:
        logger.warning(f"Промокод '{code}' уже существует.")
        return None

    promo_code = PromoCode(
        code=code.upper(),  # Приводим код к верхнему регистру
        discount_type=discount_type,
        value=value,
        max_uses=max_uses,
        expiry_date=expiry_date,
        is_active=is_active
    )
    
    db.add(promo_code)
    await db.commit()
    await db.refresh(promo_code)
    logger.info(f"Создан промокод: {promo_code}")
    return promo_code

async def get_promo_code_by_id(db: AsyncSession, promo_code_id: int) -> Optional[PromoCode]:
    """Получает промокод по ID"""
    return await db.get(PromoCode, promo_code_id)

async def get_promo_code_by_code(db: AsyncSession, code: str) -> Optional[PromoCode]:
    """Получает промокод по его коду (регистронезависимо)"""
    query = select(PromoCode).where(func.upper(PromoCode.code) == code.upper())
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def use_promo_code(
    db: AsyncSession, 
    user_id: int, 
    promo_code_id: int
) -> Optional[UserPromoCode]:
    """Отмечает, что пользователь использовал промокод и увеличивает счетчик использования"""
    # Создаем запись об использовании
    user_promo_code_entry = UserPromoCode(user_id=user_id, promo_code_id=promo_code_id)
    db.add(user_promo_code_entry)
    
    # Увеличиваем счетчик использования промокода
    query = (
        update(PromoCode)
        .where(PromoCode.id == promo_code_id)
        .values(current_uses=PromoCode.current_uses + 1)
    )
    await db.execute(query)
    
    await db.commit()
    await db.refresh(user_promo_code_entry)
    logger.info(f"Пользователь ID {user_id} использовал промокод ID {promo_code_id}")
    return user_promo_code_entry

async def has_user_used_promo_code(db: AsyncSession, user_id: int, promo_code_id: int) -> bool:
    """
    Проверяет, использовал ли пользователь уже этот промокод
    
    Для персональных промокодов также проверяет, что промокод предназначен для этого пользователя
    """
    # Получаем промокод для проверки персональности
    promo_code = await db.get(PromoCode, promo_code_id)
    if promo_code and promo_code.is_personal:
        # Если промокод персональный, проверяем, что он для этого пользователя
        if promo_code.user_id != user_id:
            return True  # Промокод не для этого пользователя = считается использованным
    
    query = select(UserPromoCode).where(
        and_(
            UserPromoCode.user_id == user_id,
            UserPromoCode.promo_code_id == promo_code_id
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None

async def apply_promo_code_days(db: AsyncSession, user_id: int, days: int) -> Optional[Subscription]:
    """
    Применяет промокод, добавляя дни к подписке пользователя или создавая новую.
    При создании новой бесплатной подписки, параметры автопродления не устанавливаются.
    """
    active_subscription = await get_active_subscription(db, user_id)
    
    if active_subscription:
        # Если есть активная подписка, продлеваем её
        # Параметры renewal_price и renewal_duration_days НЕ изменяются, так как это бонусные дни
        new_end_date = active_subscription.end_date + timedelta(days=days)
        query = (
            update(Subscription)
            .where(Subscription.id == active_subscription.id)
            .values(end_date=new_end_date)
        )
        await db.execute(query)
        await db.commit()
        await db.refresh(active_subscription)
        logger.info(f"Подписка ID {active_subscription.id} для пользователя {user_id} продлена на {days} дней промокодом. Новая дата: {new_end_date}")
        return active_subscription
    else:
        # Иначе создаем новую бесплатную подписку
        end_date = datetime.now() + timedelta(days=days)
        new_subscription = await create_subscription(
            db,
            user_id,
            end_date,
            price=0, # Бесплатная по промокоду
            payment_id=f"promo_{days}days",
            renewal_price=None, # Явно указываем None для новой бесплатной подписки
            renewal_duration_days=None # Явно указываем None для новой бесплатной подписки
        )
        logger.info(f"Создана новая подписка для пользователя {user_id} на {days} дней по промокоду. Дата окончания: {end_date}. Автопродление не настроено.")
        return new_subscription

async def get_total_promo_code_uses_count(db: AsyncSession) -> int:
    """Получает общее количество использований промокодов"""
    query = select(func.count(UserPromoCode.id))
    result = await db.execute(query)
    return result.scalar_one_or_none() or 0

async def has_user_used_any_promo_code(db: AsyncSession, user_id: int) -> bool:
    """Проверяет, использовал ли пользователь хотя бы один промокод"""
    query = select(UserPromoCode).where(UserPromoCode.user_id == user_id).limit(1)
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None

async def get_total_promo_codes_count(db: AsyncSession) -> int:
    """Получает общее количество созданных промокодов"""
    query = select(func.count(PromoCode.id))
    result = await db.execute(query)
    return result.scalar_one_or_none() or 0

async def get_sorted_active_subscriptions(db: AsyncSession) -> List[Tuple[User, Subscription]]:
    """Получает все активные подписки, отсортированные по дате окончания (от ближайшей до самой дальней)"""
    now = datetime.now()
    query = (
        select(User, Subscription)
        .join(Subscription, User.id == Subscription.user_id)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now
            )
        )
        .order_by(Subscription.end_date.asc())  # Сортировка по возрастанию даты окончания
    )
    
    result = await db.execute(query)
    return result.all()

async def get_users_with_birthdays(db: AsyncSession) -> List[User]:
    """Получает всех пользователей с указанной датой рождения, 
    отсортированных по месяцу и дню (независимо от года)"""
    query = (
        select(User)
        .where(User.birthday.isnot(None))
        .order_by(
            func.strftime('%m-%d', User.birthday)
        )
    )
    
    result = await db.execute(query)
    return result.scalars().all()

async def get_subscription_notification(db: AsyncSession, subscription_id: int, notification_type: str):
    """Проверяет, было ли отправлено уведомление указанного типа для подписки"""
    query = select(SubscriptionNotification).where(
        and_(
            SubscriptionNotification.subscription_id == subscription_id,
            SubscriptionNotification.notification_type == notification_type
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def create_subscription_notification(db: AsyncSession, subscription_id: int, notification_type: str):
    """Создает запись об отправленном уведомлении"""
    notification = SubscriptionNotification(
        subscription_id=subscription_id,
        notification_type=notification_type
    )
    db.add(notification)
    await db.commit()
    return notification

async def get_users_with_expired_subscriptions_for_reminder(db: AsyncSession, days_after_expiration: int = 3):
    """
    Получает пользователей, у которых подписка истекла {days_after_expiration} дней назад
    и для которых еще не отправлялось уведомление "мы скучаем"
    
    Args:
        db: Сессия БД
        days_after_expiration: Количество дней после истечения подписки (по умолчанию 3)
        
    Returns:
        Список кортежей (user, subscription) для пользователей, которым нужно отправить уведомление
    """
    from sqlalchemy import func
    now = datetime.now()
    expiration_date = now - timedelta(days=days_after_expiration)
    
    # Получаем последние истекшие подписки для каждого пользователя
    subquery = (
        select(
            Subscription.user_id,
            func.max(Subscription.end_date).label('max_end_date')
        )
        .group_by(Subscription.user_id)
        .having(
            and_(
                func.max(Subscription.end_date) <= datetime(2099, 1, 1),  # Не берем безлимитные
                func.max(Subscription.end_date) <= expiration_date,  # Истекли минимум N дней назад
                func.max(Subscription.end_date) >= expiration_date - timedelta(days=1)  # Но не больше N+1 дней
            )
        )
    ).subquery()
    
    # Получаем полные данные подписок
    query = (
        select(User, Subscription)
        .join(Subscription, User.id == Subscription.user_id)
        .join(
            subquery,
            and_(
                Subscription.user_id == subquery.c.user_id,
                Subscription.end_date == subquery.c.max_end_date
            )
        )
        .where(
            and_(
                Subscription.is_active == False,
                User.is_blocked == False  # Не заблокировали бота
            )
        )
    )
    
    result = await db.execute(query)
    users_with_subs = result.all()
    
    # Фильтруем тех, кому еще не отправлялось уведомление "мы скучаем"
    filtered = []
    for user, subscription in users_with_subs:
        notification = await get_subscription_notification(db, subscription.id, 'expired_reminder_3days')
        if not notification:
            filtered.append((user, subscription))
    
    return filtered


# --- Функции для работы с персональными промокодами возврата ---

async def create_personal_return_promo_code(
    db: AsyncSession,
    user_id: int,
    loyalty_level: str,
    return_promo_count: int,
    days_valid: int = 7
) -> PromoCode:
    """
    Создает персональный промокод для возврата пользователя с учетом защиты от злоупотреблений
    
    Args:
        db: Сессия БД
        user_id: ID пользователя
        loyalty_level: Уровень лояльности ('none', 'silver', 'gold', 'platinum')
        return_promo_count: Текущее количество полученных промокодов возврата
        days_valid: Количество дней действия промокода (по умолчанию 7)
    
    Returns:
        PromoCode: Созданный промокод
    """
    from utils.constants import DISCOUNT_REDUCTION_PER_USE
    
    # Получаем конфигурацию для уровня лояльности
    config = RETURN_PROMO_CONFIG.get(loyalty_level, RETURN_PROMO_CONFIG['none'])
    base_discount = config['discount_percent']
    
    # ВАЖНО: Уменьшаем скидку в зависимости от количества использований
    # 1-й промокод: полная скидка
    # 2-й промокод: -5%
    # 3-й промокод: -10%
    discount_reduction = return_promo_count * DISCOUNT_REDUCTION_PER_USE
    discount_percent = max(base_discount - discount_reduction, 5)  # Минимум 5% скидка
    
    logger.info(
        f"Расчет скидки для user_id={user_id}: "
        f"базовая={base_discount}%, использований={return_promo_count}, "
        f"уменьшение={discount_reduction}%, итоговая={discount_percent}%"
    )
    
    # Генерируем уникальный код
    promo_code_str = f"RETURN{user_id}"
    
    # Проверяем, не существует ли уже такой промокод
    existing = await get_promo_code_by_code(db, promo_code_str)
    if existing:
        # Если существует, обновляем его
        promo_code = existing
        promo_code.discount_type = 'percent'
        promo_code.value = discount_percent
        promo_code.user_id = user_id
        promo_code.is_personal = True
        promo_code.auto_generated = True
        promo_code.max_uses = 1
        promo_code.current_uses = 0
        promo_code.is_active = True
        promo_code.expiry_date = datetime.now() + timedelta(days=days_valid)
    else:
        # Создаем новый
        promo_code = PromoCode(
            code=promo_code_str,
            discount_type='percent',
            value=discount_percent,
            max_uses=1,
            current_uses=0,
            is_active=True,
            expiry_date=datetime.now() + timedelta(days=days_valid),
            user_id=user_id,
            is_personal=True,
            auto_generated=True
        )
        db.add(promo_code)
    
    await db.commit()
    await db.refresh(promo_code)
    
    logger.info(
        f"Создан персональный промокод RETURN{user_id} для пользователя {user_id} "
        f"(уровень: {loyalty_level}, скидка: {discount_percent}%, использование #{return_promo_count + 1})"
    )
    return promo_code


async def get_users_for_7day_return_promo(
    db: AsyncSession,
    days_after_expiration: int = 7
) -> List[Tuple[User, Subscription]]:
    """
    Получает пользователей, у которых подписка истекла {days_after_expiration} дней назад
    и для которых еще не отправлялось уведомление с промокодом возврата
    
    Args:
        db: Сессия БД
        days_after_expiration: Количество дней после истечения подписки (по умолчанию 7)
    
    Returns:
        Список кортежей (user, subscription) для пользователей, которым нужно отправить уведомление
    """
    from sqlalchemy import func
    now = datetime.now()
    expiration_date = now - timedelta(days=days_after_expiration)
    
    # Получаем последние истекшие подписки для каждого пользователя
    subquery = (
        select(
            Subscription.user_id,
            func.max(Subscription.end_date).label('max_end_date')
        )
        .group_by(Subscription.user_id)
        .having(
            and_(
                func.max(Subscription.end_date) <= datetime(2099, 1, 1),  # Не берем безлимитные
                func.max(Subscription.end_date) <= expiration_date,  # Истекли минимум N дней назад
                func.max(Subscription.end_date) >= expiration_date - timedelta(days=1)  # Но не больше N+1 дней
            )
        )
    ).subquery()
    
    # Получаем полные данные подписок
    query = (
        select(User, Subscription)
        .join(Subscription, User.id == Subscription.user_id)
        .join(
            subquery,
            and_(
                Subscription.user_id == subquery.c.user_id,
                Subscription.end_date == subquery.c.max_end_date
            )
        )
        .where(
            and_(
                Subscription.is_active == False,
                User.is_blocked == False,  # Не заблокировали бота
                User.is_recurring_active == False  # Без автопродления
            )
        )
    )
    
    result = await db.execute(query)
    users_with_subs = result.all()
    
    # Фильтруем с учетом защиты от злоупотреблений
    from utils.constants import MAX_RETURN_PROMOS, MIN_DAYS_BETWEEN_RETURN_PROMOS
    
    filtered = []
    for user, subscription in users_with_subs:
        # Проверка 1: Уже отправлялось уведомление для этой подписки?
        notification = await get_subscription_notification(db, subscription.id, 'expired_reminder_7days')
        if notification:
            logger.debug(f"Пропускаем user_id={user.id}: уведомление уже отправлялось для subscription_id={subscription.id}")
            continue
        
        # Проверка 2: Не превышен ли лимит промокодов? (максимум 3)
        if user.return_promo_count >= MAX_RETURN_PROMOS:
            logger.info(
                f"Пропускаем user_id={user.id}: достигнут лимит промокодов возврата "
                f"({user.return_promo_count}/{MAX_RETURN_PROMOS})"
            )
            continue
        
        # Проверка 3: Прошло ли достаточно времени с последнего промокода? (минимум 90 дней)
        if user.last_return_promo_date:
            days_since_last = (now - user.last_return_promo_date).days
            if days_since_last < MIN_DAYS_BETWEEN_RETURN_PROMOS:
                logger.info(
                    f"Пропускаем user_id={user.id}: слишком рано для нового промокода "
                    f"(прошло {days_since_last} дней, нужно {MIN_DAYS_BETWEEN_RETURN_PROMOS})"
                )
                continue
        
        # Все проверки пройдены - добавляем в список
        filtered.append((user, subscription))
        logger.debug(
            f"User_id={user.id} прошел все проверки: "
            f"промокодов={user.return_promo_count}/{MAX_RETURN_PROMOS}, "
            f"последний={user.last_return_promo_date}"
        )
    
    logger.info(
        f"Отфильтровано {len(filtered)} из {len(users_with_subs)} пользователей "
        f"для отправки промокодов возврата"
    )
    
    return filtered


async def apply_promo_code_percent(
    db: AsyncSession,
    user_id: int,
    promo_code_id: int
) -> bool:
    """
    Применяет процентный промокод, устанавливая разовую скидку пользователю
    
    Args:
        db: Сессия БД
        user_id: ID пользователя
        promo_code_id: ID промокода
    
    Returns:
        bool: True если успешно применен, False в случае ошибки
    """
    try:
        # Получаем промокод
        promo_code = await db.get(PromoCode, promo_code_id)
        if not promo_code:
            logger.error(f"Промокод ID {promo_code_id} не найден")
            return False
        
        # Проверяем, что промокод процентный
        if promo_code.discount_type != 'percent':
            logger.error(f"Промокод ID {promo_code_id} не является процентным (тип: {promo_code.discount_type})")
            return False
        
        # Проверяем, что промокод персональный и для этого пользователя
        if promo_code.is_personal and promo_code.user_id != user_id:
            logger.error(f"Промокод ID {promo_code_id} предназначен для другого пользователя")
            return False
        
        # Проверяем, не использован ли уже
        already_used = await has_user_used_promo_code(db, user_id, promo_code_id)
        if already_used:
            logger.warning(f"Пользователь {user_id} уже использовал промокод {promo_code_id}")
            return False
        
        # Проверяем срок действия
        if promo_code.expiry_date and promo_code.expiry_date < datetime.now():
            logger.warning(f"Промокод {promo_code_id} истек")
            return False
        
        # Проверяем активность
        if not promo_code.is_active:
            logger.warning(f"Промокод {promo_code_id} неактивен")
            return False
        
        # Получаем пользователя
        user = await get_user_by_id(db, user_id)
        if not user:
            logger.error(f"Пользователь ID {user_id} не найден")
            return False
        
        # Устанавливаем разовую скидку
        user.one_time_discount_percent = promo_code.value
        user.updated_at = datetime.now()
        db.add(user)
        
        # Отмечаем использование промокода
        await use_promo_code(db, user_id, promo_code_id)
        
        await db.commit()
        
        logger.info(f"Применен процентный промокод {promo_code.code} для пользователя {user_id}. Установлена скидка: {promo_code.value}%")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при применении процентного промокода {promo_code_id} для пользователя {user_id}: {e}", exc_info=True)
        await db.rollback()
        return False

async def get_users_for_milestone_notifications(db: AsyncSession):
    """
    Получает пользователей, которые достигли milestone-дат (100, 180, 365 дней стажа)
    и для которых еще не отправлялись соответствующие уведомления
    
    Returns:
        Список кортежей (user, milestone_days) для пользователей, которым нужно отправить уведомление
    """
    from loyalty.levels import calc_tenure_days
    
    # Получаем всех пользователей с активными подписками
    query = select(User).where(
        and_(
            User.first_payment_date.isnot(None),
            User.is_blocked == False
        )
    )
    result = await db.execute(query)
    users = result.scalars().all()
    
    milestones = [100, 180, 365]
    users_for_notification = []
    
    for user in users:
        tenure_days = await calc_tenure_days(db, user)
        
        # Проверяем, достиг ли пользователь какого-либо milestone
        for milestone in milestones:
            # Проверяем, что стаж в диапазоне milestone ± 1 день (чтобы не пропустить)
            if milestone - 1 <= tenure_days <= milestone + 1:
                # Проверяем, отправлялось ли уже уведомление для этого milestone
                notification_type = f'milestone_{milestone}_days'
                
                # Получаем последнюю активную подписку пользователя
                from database.models import Subscription
                sub_query = select(Subscription).where(
                    and_(
                        Subscription.user_id == user.id,
                        Subscription.is_active == True
                    )
                ).order_by(Subscription.end_date.desc()).limit(1)
                sub_result = await db.execute(sub_query)
                subscription = sub_result.scalar_one_or_none()
                
                if subscription:
                    notification = await get_subscription_notification(db, subscription.id, notification_type)
                    if not notification:
                        users_for_notification.append((user, milestone))
                        break  # Отправляем только одно уведомление за раз
    
    return users_for_notification

# ===== Функции для работы с badges (достижениями) =====

async def get_user_badges(db: AsyncSession, user_id: int) -> List[UserBadge]:
    """
    Получает все badges пользователя
    
    Args:
        db: Сессия БД
        user_id: ID пользователя
        
    Returns:
        Список badges пользователя
    """
    query = select(UserBadge).where(
        UserBadge.user_id == user_id
    ).order_by(UserBadge.earned_at.desc())
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def has_user_badge(db: AsyncSession, user_id: int, badge_type: str) -> bool:
    """
    Проверяет, есть ли у пользователя badge указанного типа
    
    Args:
        db: Сессия БД
        user_id: ID пользователя
        badge_type: Тип badge ('first_payment', 'referral_1', 'referral_5', 'year_in_club')
        
    Returns:
        True если badge есть, иначе False
    """
    query = select(UserBadge).where(
        and_(
            UserBadge.user_id == user_id,
            UserBadge.badge_type == badge_type
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none() is not None


async def grant_user_badge(db: AsyncSession, user_id: int, badge_type: str, from_admin: bool = False, admin_id: Optional[int] = None) -> Optional[UserBadge]:
    """
    Выдает badge пользователю (если его еще нет)
    
    Args:
        db: Сессия БД
        user_id: ID пользователя
        badge_type: Тип badge
        from_admin: Выдан ли badge администратором
        admin_id: ID администратора, который выдал badge (если from_admin=True)
        
    Returns:
        UserBadge если badge был выдан, None если уже был
    """
    # Проверяем, есть ли уже такой badge
    if await has_user_badge(db, user_id, badge_type):
        return None
    
    # Создаем новый badge
    badge = UserBadge(
        user_id=user_id,
        badge_type=badge_type
    )
    db.add(badge)
    await db.commit()
    await db.refresh(badge)
    
    logger.info(f"Выдан badge '{badge_type}' пользователю {user_id}" + (f" администратором {admin_id}" if from_admin else ""))
    return badge


async def revoke_user_badge(db: AsyncSession, user_id: int, badge_type: str, admin_id: Optional[int] = None) -> bool:
    """
    Удаляет badge у пользователя
    
    Args:
        db: Сессия БД
        user_id: ID пользователя
        badge_type: Тип badge для удаления
        admin_id: ID администратора, который удалил badge
        
    Returns:
        True если badge был удален, False если его не было
    """
    query = select(UserBadge).where(
        and_(
            UserBadge.user_id == user_id,
            UserBadge.badge_type == badge_type
        )
    )
    result = await db.execute(query)
    badge = result.scalar_one_or_none()
    
    if badge:
        await db.delete(badge)
        await db.commit()
        logger.info(f"Удален badge '{badge_type}' у пользователя {user_id}" + (f" администратором {admin_id}" if admin_id else ""))
        return True
    
    logger.warning(f"Попытка удалить несуществующий badge '{badge_type}' у пользователя {user_id}")
    return False


async def send_badge_notification(bot, user: User, badge_type: str, from_admin: bool = False) -> bool:
    """
    Отправляет уведомление пользователю о получении badge
    
    Args:
        bot: Объект бота
        user: Объект пользователя
        badge_type: Тип badge
        from_admin: Выдан ли badge администратором
        
    Returns:
        True если уведомление отправлено, False если ошибка
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    badge_messages = {
        'first_payment': (
            "💳 *Поздравляю, красотка\\!*\n\n"
            "Ты получила достижение *«Первая оплата»*\\!\n\n"
            "Это твой первый шаг в Mom's Club, и мы рады, что ты с нами 💖\n\n"
            "Теперь тебя ждут еще больше возможностей и бонусов\\. Желаю тебе получать максимум от нашего клуба\\! 🩷"
        ),
        'referral_1': (
            "🤝 *Ура, красотка\\!*\n\n"
            "Ты получила достижение *«Пригласила друга»*\\!\n\n"
            "Спасибо, что делишься Mom's Club с подругами\\! Это значит, что тебе действительно нравится то, что мы делаем 💕\n\n"
            "Продолжай приглашать друзей — за каждое приглашение тебя ждут бонусы\\! ✨"
        ),
        'referral_5': (
            "🌟 *Красотка, ты просто звезда\\!*\n\n"
            "Ты получила достижение *«Пригласила 5 друзей»*\\!\n\n"
            "5 подруг уже с нами благодаря тебе\\! Это невероятно, и мы очень ценим твою поддержку 🤍\n\n"
            "Ты настоящий амбассадор Mom's Club\\! Продолжай в том же духе 💖"
        ),
        'referral_10': (
            "✨ *Красотка, ты просто невероятна\\!*\n\n"
            "Ты получила достижение *«Пригласила 10 друзей»*\\!\n\n"
            "10 подруг уже в Mom's Club благодаря тебе\\! Это настоящий подвиг, и мы бесконечно благодарны за твою поддержку 💎\n\n"
            "Ты — настоящий лидер нашего сообщества\\! 🏆"
        ),
        'month_in_club': (
            "📅 *Красотка, поздравляю\\!*\n\n"
            "Ты получила достижение *«Месяц в клубе»*\\!\n\n"
            "Ты с нами уже целый месяц\\! За это время ты стала частью нашего теплого сообщества 💖\n\n"
            "Спасибо, что остаешься с нами\\. Впереди еще столько интересного\\! ✨"
        ),
        'half_year_in_club': (
            "💫 *Красотка, это невероятно\\!*\n\n"
            "Ты получила достижение *«Полгода в клубе»*\\!\n\n"
            "Полгода вместе — это уже серьезно\\! Ты настоящая часть нашей семьи, и мы очень ценим тебя 🤍\n\n"
            "Спасибо за твою верность и поддержку\\. Ты — наша звезда\\! 🌟"
        ),
        'year_in_club': (
            "🏆 *КРАСОТКА, ЭТО НЕВЕРОЯТНО\\!*\n\n"
            "Ты получила достижение *«Год в клубе»*\\!\n\n"
            "Целый год вместе\\! Ты прошла с нами весь путь, и мы бесконечно благодарны за твою верность 💎\n\n"
            "Ты — настоящая легенда Mom's Club\\! Спасибо, что остаешься с нами\\. Мы любим тебя\\! 💖"
        ),
        'loyal_customer': (
            "💎 *Красотка, ты верный друг\\!*\n\n"
            "Ты получила достижение *«Верный клиент»*\\!\n\n"
            "5\\+ успешных платежей — это говорит о твоей преданности Mom's Club\\! Мы очень ценим таких участников, как ты 🤍\n\n"
            "Спасибо за твое доверие и поддержку\\. Ты — наша опора\\! ✨"
        ),
        'platinum_customer': (
            "👑 *Красотка, ты платиновая\\!*\n\n"
            "Ты получила достижение *«Платиновый клиент»*\\!\n\n"
            "10\\+ успешных платежей — это настоящий рекорд\\! Ты одна из самых преданных участниц нашего клуба 💎\n\n"
            "Мы бесконечно благодарны за твою поддержку\\. Ты — наша королева\\! 🏆"
        ),
        'active_member': (
            "🔥 *Красотка, ты активная\\!*\n\n"
            "Ты получила достижение *«Активный участник»*\\!\n\n"
            "Подписка продлевалась 3\\+ раза — это значит, что Mom's Club стал частью твоей жизни\\! Мы рады видеть тебя снова и снова 💖\n\n"
            "Спасибо за твою активность и преданность\\. Ты — наша энергия\\! ✨"
        ),
        'birthday_gift': (
            "🎂 *С днем рождения, красотка\\!*\n\n"
            "Ты получила достижение *«День рождения»*\\!\n\n"
            "Мы помним о твоем особом дне и рады поздравить тебя\\! Пусть этот год будет наполнен счастьем, любовью и вдохновением 💕\n\n"
            "Спасибо, что отмечаешь свой день вместе с нами\\. Мы любим тебя\\! 🩷"
        ),
        # Специальные badges (только от админов)
        'community_helper': (
            "💝 *Красотка, ты особенная\\!*\n\n"
            "Ты получила достижение *«Помощь сообществу»*\\!\n\n"
            "Твой вклад в развитие Mom's Club не остался незамеченным\\. Ты помогаешь создавать то теплое и поддерживающее пространство, которое мы все так любим 💖\n\n"
            "Спасибо за твою активность и заботу о других\\. Ты делаешь наш клуб лучше\\! ✨"
        ),
        'inspiration': (
            "✨ *Красотка, ты вдохновляешь\\!*\n\n"
            "Ты получила достижение *«Источник вдохновения»*\\!\n\n"
            "Твоя энергия, идеи и позитив вдохновляют других участниц нашего клуба\\. Ты показываешь, что возможно, когда есть поддержка и вера в себя 💫\n\n"
            "Продолжай делиться своим светом\\. Ты — настоящий пример для других\\! 🌟"
        ),
        'early_supporter': (
            "🌱 *Красотка, ты первопроходец\\!*\n\n"
            "Ты получила достижение *«Первопроходец»*\\!\n\n"
            "Ты была с нами с самого начала, когда Mom's Club только начинал свой путь\\. Твоя вера в нас и поддержка помогли нам стать тем сообществом, которым мы являемся сегодня 🌿\n\n"
            "Спасибо за то, что поверила в нас первая\\. Ты — часть нашей истории\\! 💚"
        ),
        'ambassador': (
            "🌟 *Красотка, ты амбассадор\\!*\n\n"
            "Ты получила достижение *«Амбассадор клуба»*\\!\n\n"
            "Ты — настоящий представитель Mom's Club\\. Своим примером, активностью и поддержкой других ты показываешь, что значит быть частью нашего сообщества 💎\n\n"
            "Мы гордимся тем, что ты с нами\\. Ты — лицо Mom's Club\\! 🏆"
        ),
        'special_thanks': (
            "💖 *Красотка, особая благодарность\\!*\n\n"
            "Ты получила достижение *«Особая благодарность»*\\!\n\n"
            "Мы хотим выразить тебе особую благодарность за все, что ты делаешь для Mom's Club\\. Твоя поддержка, активность и забота не остаются незамеченными 🤍\n\n"
            "Спасибо за то, что ты есть\\. Ты делаешь наше сообщество особенным\\! 💕"
        ),
        'milestone_celebrator': (
            "🎉 *Красотка, празднуем вместе\\!*\n\n"
            "Ты получила достижение *«Празднуем вместе»*\\!\n\n"
            "Ты всегда рядом, когда мы отмечаем особые моменты\\. Твоя поддержка и участие делают наши праздники еще более яркими и запоминающимися 🎊\n\n"
            "Спасибо, что делишь с нами радость\\. Вместе мы создаем незабываемые моменты\\! ✨"
        ),
        'supportive_friend': (
            "🤗 *Красотка, ты поддерживающая\\!*\n\n"
            "Ты получила достижение *«Поддерживающая подруга»*\\!\n\n"
            "Ты всегда готова поддержать других участниц клуба, поделиться опытом и просто быть рядом\\. Такие люди, как ты, делают наше сообщество по\\-настоящему теплым и безопасным местом 💝\n\n"
            "Спасибо за твою открытость и заботу\\. Ты — настоящая подруга\\! 🤍"
        ),
        'creative_soul': (
            "🎨 *Красотка, ты творческая\\!*\n\n"
            "Ты получила достижение *«Творческая душа»*\\!\n\n"
            "Твои идеи, креативность и нестандартный подход вдохновляют всех вокруг\\. Ты показываешь, что творчество и самовыражение — это то, что делает жизнь ярче 🌈\n\n"
            "Продолжай творить и делиться своим талантом\\. Ты — настоящий художник жизни\\! ✨"
        ),
        'motivator': (
            "💪 *Красотка, ты мотиватор\\!*\n\n"
            "Ты получила достижение *«Мотиватор»*\\!\n\n"
            "Твоя энергия и позитивный настрой мотивируют других участниц к действию\\. Ты показываешь, что все возможно, когда есть вера в себя и поддержка сообщества 🚀\n\n"
            "Спасибо за то, что вдохновляешь других на достижения\\. Ты — настоящий двигатель прогресса\\! 🌟"
        ),
        'heart_of_club': (
            "💕 *Красотка, ты — сердце клуба\\!*\n\n"
            "Ты получила достижение *«Сердце клуба»*\\!\n\n"
            "Ты — та, кто делает Mom's Club по\\-настоящему особенным местом\\. Твоя забота, поддержка и участие создают ту атмосферу, которую мы все так любим 💖\n\n"
            "Без тебя наш клуб был бы другим\\. Ты — его сердце и душа\\. Мы бесконечно благодарны за то, что ты с нами\\! 🩷"
        ),
        'creator_special': (
            "💋 *Пссс, красотка\\!*\n\n"
            "Ты получила достижение *«Моя сучка от создателя Moms Club»*\\!\n\n"
            "Это достижение особенное, если понимаешь, смекаешь\\? 😎💕\n\n"
            "Ты знаешь, что это значит\\. Ты особенная\\! 🔥"
        ),
        'moscow_first_meetup': (
            "🎉 *Красотка, это исторический момент\\!*\n\n"
            "Ты получила достижение *«Первая встреча в Москве»*\\!\n\n"
            "Сегодня мы встретились в реальном мире — и это было невероятно\\! Ты стала частью первой офлайн\\-встречи Mom\\'s Club, и мы бесконечно благодарны, что ты была с нами 💖\n\n"
            "Эти моменты живого общения, тепла и поддержки — именно то, что делает наше сообщество особенным\\. Ты — часть истории Mom\\'s Club\\! ✨\n\n"
            "Спасибо, что пришла\\. Мы любим тебя\\! 🫂💕"
        ),
    }
    
    message_text = badge_messages.get(badge_type)
    if not message_text:
        # Общее сообщение для неизвестных badges
        message_text = (
            f"🏆 *Поздравляю, красотка\\!*\n\n"
            f"Ты получила новое достижение\\!\n\n"
            f"Мы очень рады, что ты с нами\\. Продолжай в том же духе\\! 💖"
        )
    
    # Если badge выдан администратором, добавляем специальное сообщение
    if from_admin:
        admin_message = (
            "\n\n💝 *P\\.S\\.* Это достижение было выдано администратором в знак особой благодарности за твою преданность Mom's Club\\!"
        )
        message_text = message_text + admin_message
    
    try:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎀 Личный кабинет", callback_data="back_to_profile")]
            ]
        )
        await bot.send_message(
            user.telegram_id,
            message_text,
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о badge пользователю {user.telegram_id}: {e}")
        return False


async def check_and_grant_badges(db: AsyncSession, user: User) -> List[str]:
    """
    Проверяет условия для выдачи badges и выдает их при необходимости
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        
    Returns:
        Список типов выданных badges
    """
    granted_badges = []
    # ИСПРАВЛЕНО: сохраняем все атрибуты в начале для защиты от greenlet
    user_id = user.id
    is_first_payment_done = user.is_first_payment_done
    birthday_gift_year = user.birthday_gift_year
    
    try:
        # 1. Badge "Первая оплата"
        if is_first_payment_done and not await has_user_badge(db, user_id, 'first_payment'):
            badge = await grant_user_badge(db, user_id, 'first_payment')
            if badge:
                granted_badges.append('first_payment')
        
        # 2. Badge "Пригласил 1 друга" и "Пригласил 5 друзей"
        # Подсчитываем количество рефералов пользователя
        from database.models import User
        referrals_query = select(func.count(User.id)).where(User.referrer_id == user_id)
        result = await db.execute(referrals_query)
        total_referrals = result.scalar() or 0
        
        if total_referrals >= 1:
            if not await has_user_badge(db, user_id, 'referral_1'):
                badge = await grant_user_badge(db, user_id, 'referral_1')
                if badge:
                    granted_badges.append('referral_1')
        
        # 3. Badge "Пригласил 5 друзей"
        if total_referrals >= 5:
            if not await has_user_badge(db, user_id, 'referral_5'):
                badge = await grant_user_badge(db, user_id, 'referral_5')
                if badge:
                    granted_badges.append('referral_5')
        
        # 4. Badge "Пригласила 10 друзей"
        if total_referrals >= 10:
            if not await has_user_badge(db, user_id, 'referral_10'):
                badge = await grant_user_badge(db, user_id, 'referral_10')
                if badge:
                    granted_badges.append('referral_10')
        
        # 5. Badge "Месяц в клубе" (30 дней стажа)
        from loyalty.levels import calc_tenure_days
        tenure_days = await calc_tenure_days(db, user)
        if tenure_days >= 30 and not await has_user_badge(db, user_id, 'month_in_club'):
            badge = await grant_user_badge(db, user_id, 'month_in_club')
            if badge:
                granted_badges.append('month_in_club')
        
        # 6. Badge "Полгода в клубе" (180 дней стажа)
        if tenure_days >= 180 and not await has_user_badge(db, user_id, 'half_year_in_club'):
            badge = await grant_user_badge(db, user_id, 'half_year_in_club')
            if badge:
                granted_badges.append('half_year_in_club')
        
        # 7. Badge "Год в клубе" (365 дней стажа)
        if tenure_days >= 365 and not await has_user_badge(db, user_id, 'year_in_club'):
            badge = await grant_user_badge(db, user_id, 'year_in_club')
            if badge:
                granted_badges.append('year_in_club')
        
        # 8. Badge "Верный клиент" (5+ успешных платежей)
        from database.models import PaymentLog
        payments_query = select(func.count(PaymentLog.id)).where(
            and_(
                PaymentLog.user_id == user_id,
                PaymentLog.status == 'success',
                PaymentLog.is_confirmed == True
            )
        )
        payments_result = await db.execute(payments_query)
        total_payments = payments_result.scalar() or 0
        
        if total_payments >= 5 and not await has_user_badge(db, user_id, 'loyal_customer'):
            badge = await grant_user_badge(db, user_id, 'loyal_customer')
            if badge:
                granted_badges.append('loyal_customer')
        
        # 9. Badge "Платиновый клиент" (10+ успешных платежей)
        if total_payments >= 10 and not await has_user_badge(db, user_id, 'platinum_customer'):
            badge = await grant_user_badge(db, user_id, 'platinum_customer')
            if badge:
                granted_badges.append('platinum_customer')
        
        # 10. Badge "Активный участник" (подписка продлевалась 3+ раза)
        # Считаем по успешным платежам, так как при продлении через extend_subscription
        # новая запись подписки не создается, а обновляется существующая
        # Используем уже подсчитанный total_payments из проверки выше
        if total_payments >= 3 and not await has_user_badge(db, user_id, 'active_member'):
            badge = await grant_user_badge(db, user_id, 'active_member')
            if badge:
                granted_badges.append('active_member')
        
        # 11. Badge "День рождения" (получен подарок на ДР)
        if birthday_gift_year and not await has_user_badge(db, user_id, 'birthday_gift'):
            badge = await grant_user_badge(db, user_id, 'birthday_gift')
            if badge:
                granted_badges.append('birthday_gift')
    
    except Exception as e:
        logger.error(f"Ошибка при проверке badges для пользователя {user_id}: {e}", exc_info=True)
    
    return granted_badges

async def disable_user_auto_renewal(db: AsyncSession, user_id: int) -> bool:
    """
    Отключает автопродление для пользователя и очищает связанные данные в подписке.

    Args:
        db: Сессия базы данных.
        user_id: ID пользователя (из таблицы User).

    Returns:
        bool: True, если операция прошла успешно, False в противном случае.
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        logger.warning(f"Попытка отключить автопродление для несуществующего пользователя ID {user_id}")
        return False

    # Сохраняем старый streak для логирования
    old_streak = user.autopay_streak or 0
    
    # Отключаем автопродление на уровне пользователя (НЕ удаляем yookassa_payment_method_id!)
    # Также сбрасываем streak бонусов
    user_update_query = (
        update(User)
        .where(User.id == user_id)
        .values(
            is_recurring_active=False,
            autopay_streak=0  # Сбрасываем streak при отключении
            # yookassa_payment_method_id НЕ удаляем - оставляем для возможности повторного включения
        )
    )
    await db.execute(user_update_query)
    logger.info(f"Автопродление отключено для пользователя ID {user_id}. is_recurring_active=False, streak: {old_streak}→0 (yookassa_payment_method_id сохранен).")

    # Сбрасываем параметры попыток автопродления для его активной подписки (если есть)
    active_sub = await get_active_subscription(db, user_id)
    if active_sub:
        logger.info(f"Найдена активная подписка ID {active_sub.id} для пользователя {user_id}")

        subscription_reset_query = (
            update(Subscription)
            .where(Subscription.id == active_sub.id)
            .values(
                autopayment_fail_count=0,  # Сбрасываем счетчик
                next_retry_attempt_at=None  # Убираем дату следующей попытки
            )
        )
        await db.execute(subscription_reset_query)
        logger.info(f"Сброшены параметры автопродления для подписки ID {active_sub.id}")
    else:
        logger.info(f"У пользователя {user_id} нет активной подписки")
    
    await db.commit()
    return True 

async def enable_user_auto_renewal(db: AsyncSession, user_id: int) -> bool:
    """
    Включает автопродление для пользователя и активирует подписку в Prodamus.

    Args:
        db: Сессия базы данных.
        user_id: ID пользователя (из таблицы User).

    Returns:
        bool: True, если операция прошла успешно, False в противном случае.
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        logger.warning(f"Попытка включить автопродление для несуществующего пользователя ID {user_id}")
        return False

    # Проверяем, есть ли сохраненный yookassa_payment_method_id
    if not user.yookassa_payment_method_id:
        logger.warning(f"У пользователя {user_id} нет сохраненного yookassa_payment_method_id для автопродления")
        return False

    # Включаем автопродление на уровне пользователя
    user_update_query = (
        update(User)
        .where(User.id == user_id)
        .values(is_recurring_active=True)
    )
    await db.execute(user_update_query)

    logger.info(f"Автопродление включено для пользователя ID {user_id}. is_recurring_active=True.")
    await db.commit()
    return True

async def update_subscription_renewal_params(db: AsyncSession, subscription_id: int, renewal_price: int, renewal_duration_days: int):
    """
    Обновляет параметры автопродления для указанной подписки.
    
    Args:
        db: Сессия базы данных
        subscription_id: ID подписки для обновления
        renewal_price: Новая цена автопродления (в копейках)
        renewal_duration_days: Новое количество дней для автопродления
    
    Returns:
        Обновленный объект подписки
    """
    query = (
        update(Subscription)
        .where(Subscription.id == subscription_id)
        .values(
            renewal_price=renewal_price,
            renewal_duration_days=renewal_duration_days,
            updated_at=func.now()
        )
        .returning(Subscription)
    )
    
    result = await db.execute(query)
    subscription = result.scalar_one_or_none()
    await db.commit()
    
    logger.info(f"Обновлены параметры автопродления для подписки ID {subscription_id}: renewal_price={renewal_price}, renewal_duration_days={renewal_duration_days}")
    
    return subscription 

async def update_reminder_sent(session, user_id, sent=True):
    """
    Обновляет статус отправки напоминания пользователю
    """
    try:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(reminder_sent=sent)
        )
        await session.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка при обновлении статуса напоминания: {e}")
        await session.rollback()
        return False

async def get_users_for_reminder(session, hours_threshold=1):
    """
    Получает список пользователей, которым нужно отправить напоминание:
    - зарегистрировались больше hours_threshold часов назад
    - не имеют активной подписки
    - еще не получали напоминание (reminder_sent=False)
    - НИКОГДА не имели подписки (полностью новые пользователи)
    - не блокировали бота (is_blocked=False)
    
    Возвращает список объектов User
    """
    try:
        # Вычисляем временную границу (текущее время минус hours_threshold часов)
        time_threshold = datetime.now() - timedelta(hours=hours_threshold)
        
        # Получаем ID пользователей с активными подписками
        stmt_active_subs = select(Subscription.user_id).where(
            Subscription.end_date > datetime.now(),
            Subscription.is_active == True
        )
        active_users = await session.execute(stmt_active_subs)
        active_user_ids = [user_id for (user_id,) in active_users]
        
        # Получаем ID пользователей, которые когда-либо имели подписку (даже если она уже неактивна)
        stmt_ever_had_sub = select(Subscription.user_id).distinct()
        ever_had_sub = await session.execute(stmt_ever_had_sub)
        ever_had_sub_ids = [user_id for (user_id,) in ever_had_sub]
        
        # Получаем пользователей, которые соответствуют условиям
        stmt = select(User).where(
            User.created_at <= time_threshold,
            User.id.notin_(active_user_ids) if active_user_ids else True,
            User.id.notin_(ever_had_sub_ids) if ever_had_sub_ids else True,  # Никогда не имели подписку
            User.reminder_sent == False,
            User.is_blocked == False  # Добавляем проверку на блокировку бота
        )
        
        result = await session.execute(stmt)
        return result.scalars().all()
    except Exception as e:
        logging.error(f"Ошибка при получении пользователей для напоминания: {e}")
        return []

async def mark_user_as_blocked(session, user_id):
    """
    Отмечает пользователя как заблокировавшего бота,
    чтобы больше не пытаться отправлять ему сообщения
    """
    try:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_blocked=True)
        )
        await session.commit()
        logging.info(f"Пользователь {user_id} отмечен как заблокировавший бота")
        return True
    except Exception as e:
        logging.error(f"Ошибка при обновлении статуса блокировки пользователя {user_id}: {e}")
        await session.rollback()
        return False


# --- Функции для работы с шаблонами сообщений ---

async def create_message_template(
    db: AsyncSession, 
    name: str, 
    text: str, 
    format: str = "HTML",
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
    created_by: Optional[int] = None
) -> MessageTemplate:
    """Создает новый шаблон сообщения"""
    template = MessageTemplate(
        name=name,
        text=text,
        format=format,
        media_type=media_type,
        media_file_id=media_file_id,
        created_by=created_by
    )
    
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template

async def get_message_templates(db: AsyncSession, limit: int = 100, offset: int = 0) -> List[MessageTemplate]:
    """Получает список шаблонов сообщений"""
    query = select(MessageTemplate).order_by(MessageTemplate.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()

async def get_message_template_by_id(db: AsyncSession, template_id: int) -> Optional[MessageTemplate]:
    """Получает шаблон сообщения по ID"""
    query = select(MessageTemplate).where(MessageTemplate.id == template_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def update_message_template(db: AsyncSession, template_id: int, **kwargs) -> Optional[MessageTemplate]:
    """Обновляет шаблон сообщения"""
    query = update(MessageTemplate).where(MessageTemplate.id == template_id).values(**kwargs)
    await db.execute(query)
    await db.commit()
    
    return await get_message_template_by_id(db, template_id)

async def delete_message_template(db: AsyncSession, template_id: int) -> bool:
    """Удаляет шаблон сообщения"""
    query = select(MessageTemplate).where(MessageTemplate.id == template_id)
    result = await db.execute(query)
    template = result.scalar_one_or_none()
    
    if not template:
        return False
    
    await db.delete(template)
    await db.commit()
    return True

# --- Функции для работы с запланированными сообщениями ---

async def create_scheduled_message(
    db: AsyncSession,
    text: str,
    format: str,
    scheduled_time: datetime,
    media_type: Optional[str] = None,
    media_file_id: Optional[str] = None,
    template_id: Optional[int] = None,
    created_by: Optional[int] = None
) -> ScheduledMessage:
    """Создает запланированное сообщение"""
    scheduled_message = ScheduledMessage(
        text=text,
        format=format,
        media_type=media_type,
        media_file_id=media_file_id,
        scheduled_time=scheduled_time,
        template_id=template_id,
        created_by=created_by,
        is_sent=False
    )
    
    db.add(scheduled_message)
    await db.commit()
    await db.refresh(scheduled_message)
    return scheduled_message

async def add_scheduled_message_recipient(
    db: AsyncSession,
    message_id: int,
    user_id: int
) -> ScheduledMessageRecipient:
    """Добавляет получателя к запланированному сообщению"""
    recipient = ScheduledMessageRecipient(
        message_id=message_id,
        user_id=user_id,
        is_sent=False
    )
    
    db.add(recipient)
    await db.commit()
    await db.refresh(recipient)
    return recipient

async def get_scheduled_messages_for_sending(db: AsyncSession) -> List[ScheduledMessage]:
    """Получает запланированные сообщения, которые пора отправить"""
    now = datetime.now()
    query = select(ScheduledMessage).where(
        and_(
            ScheduledMessage.scheduled_time <= now,
            ScheduledMessage.is_sent == False
        )
    )
    result = await db.execute(query)
    return result.scalars().all()

async def mark_scheduled_message_as_sent(db: AsyncSession, message_id: int) -> None:
    """Помечает запланированное сообщение как отправленное"""
    query = update(ScheduledMessage).where(ScheduledMessage.id == message_id).values(is_sent=True)
    await db.execute(query)
    await db.commit()

async def update_recipient_status(
    db: AsyncSession,
    recipient_id: int,
    is_sent: bool,
    error: Optional[str] = None
) -> None:
    """Обновляет статус отправки для получателя"""
    values = {
        "is_sent": is_sent,
        "sent_at": datetime.now() if is_sent else None,
        "error": error
    }
    query = update(ScheduledMessageRecipient).where(ScheduledMessageRecipient.id == recipient_id).values(**values)
    await db.execute(query)
    await db.commit()

async def get_unsent_recipients(db: AsyncSession, message_id: int) -> List[ScheduledMessageRecipient]:
    """Получает список получателей, которым еще не отправлено сообщение"""
    query = select(ScheduledMessageRecipient).where(
        and_(
            ScheduledMessageRecipient.message_id == message_id,
            ScheduledMessageRecipient.is_sent == False
        )
    ).join(ScheduledMessageRecipient.user)
    result = await db.execute(query)
    return result.scalars().all()

async def get_all_scheduled_messages(db: AsyncSession, include_sent: bool = False) -> List[ScheduledMessage]:
    """Получает все запланированные сообщения"""
    query = select(ScheduledMessage)
    if not include_sent:
        query = query.where(ScheduledMessage.is_sent == False)
    query = query.order_by(ScheduledMessage.scheduled_time.asc())
    result = await db.execute(query)
    return result.scalars().all()

async def get_scheduled_message_by_id(db: AsyncSession, message_id: int) -> Optional[ScheduledMessage]:
    """Получает запланированное сообщение по ID"""
    query = select(ScheduledMessage).where(ScheduledMessage.id == message_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def delete_scheduled_message(db: AsyncSession, message_id: int) -> bool:
    """Удаляет запланированное сообщение"""
    query = select(ScheduledMessage).where(ScheduledMessage.id == message_id)
    result = await db.execute(query)
    message = result.scalar_one_or_none()
    
    if not message:
        return False
    
    await db.delete(message)
    await db.commit()
    return True


# === ФУНКЦИИ ДЛЯ УВЕДОМЛЕНИЙ О СМЕНЕ ПЛАТЕЖНОЙ СИСТЕМЫ ===

async def get_users_for_migration_notification(db: AsyncSession, notification_window_days: int = 7) -> List[User]:
    """
    Возвращает пользователей, которым нужно отправить уведомление о смене платежной системы.
    ВАЖНО: В режиме "возврат на ЮКасy" отправляем ВСЕМ пользователям с активной подпиской!

    Returns:
        List[User]: Список пользователей для уведомления
    """
    from database.models import MigrationNotification
    
    logger = logging.getLogger(__name__)
    
    try:
        now = datetime.now()
        notification_window = now + timedelta(days=notification_window_days)
        
        # ВАЖНО: В режиме "возврат на ЮКасy" отправляем ВСЕМ пользователям с активной подпиской
        # Находим ВСЕХ пользователей с активными подписками (любая дата окончания)
        users_with_expiring_subscriptions_query = (
            select(User.id).distinct()
            .join(Subscription, User.id == Subscription.user_id)
            .where(
                and_(
                    Subscription.is_active == True,
                    Subscription.end_date > now  # Подписка еще активна (БЕЗ ограничения по окну!)
                )
            )
        )
        
        # Находим пользователей, которые уже получили уведомления
        users_with_notifications_query = (
            select(MigrationNotification.user_id).distinct()
            .where(MigrationNotification.notification_type == 'payment_system_migration')
        )
        
        # Выполняем подзапросы
        users_with_subs_result = await db.execute(users_with_expiring_subscriptions_query)
        target_user_ids = [user_id for (user_id,) in users_with_subs_result]
        
        users_with_notifications_result = await db.execute(users_with_notifications_query)
        notified_user_ids = [user_id for (user_id,) in users_with_notifications_result]
        
        # Исключаем пользователей, которые уже получили уведомления
        users_to_notify_ids = list(set(target_user_ids) - set(notified_user_ids))
        
        if not users_to_notify_ids:
            logger.info("Нет пользователей для отправки уведомлений о миграции")
            return []
        
        # Получаем объекты пользователей
        users_query = (
            select(User)
            .where(
                and_(
                    User.id.in_(users_to_notify_ids),
                    User.is_blocked == False  # Не заблокировали бота
                )
            )
        )
        
        result = await db.execute(users_query)
        users = result.scalars().all()
        
        logger.info(f"Найдено {len(users)} пользователей для уведомления о смене платежной системы")
        return users
        
    except Exception as e:
        logger.error(f"Ошибка при поиске пользователей для уведомления о миграции: {e}")
        return []


async def create_migration_notification(db: AsyncSession, user_id: int, notification_type: str = 'payment_system_migration') -> bool:
    """
    Создает запись уведомления о миграции для пользователя
    
    Args:
        db: Сессия базы данных
        user_id: ID пользователя
        notification_type: Тип уведомления
        
    Returns:
        bool: True если успешно создано
    """
    from database.models import MigrationNotification
    
    logger = logging.getLogger(__name__)
    
    try:
        # Проверяем, нет ли уже уведомления для этого пользователя
        existing_query = select(MigrationNotification).where(
            and_(
                MigrationNotification.user_id == user_id,
                MigrationNotification.notification_type == notification_type
            )
        )
        existing_result = await db.execute(existing_query)
        existing_notification = existing_result.scalar_one_or_none()
        
        if existing_notification:
            logger.info(f"Уведомление типа {notification_type} для пользователя {user_id} уже существует")
            return True
        
        # Создаем новое уведомление
        notification = MigrationNotification(
            user_id=user_id,
            notification_type=notification_type,
            is_sent=False
        )
        
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
        
        logger.info(f"Создано уведомление о миграции ID {notification.id} для пользователя {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при создании уведомления о миграции для пользователя {user_id}: {e}")
        await db.rollback()
        return False


async def mark_migration_notification_sent(db: AsyncSession, user_id: int, notification_type: str = 'payment_system_migration') -> bool:
    """
    Помечает уведомление о миграции как отправленное
    
    Args:
        db: Сессия базы данных
        user_id: ID пользователя
        notification_type: Тип уведомления
        
    Returns:
        bool: True если успешно обновлено
    """
    from database.models import MigrationNotification
    
    logger = logging.getLogger(__name__)
    
    try:
        # Находим уведомление
        notification_query = select(MigrationNotification).where(
            and_(
                MigrationNotification.user_id == user_id,
                MigrationNotification.notification_type == notification_type,
                MigrationNotification.is_sent == False
            )
        )
        
        result = await db.execute(notification_query)
        notification = result.scalar_one_or_none()
        
        if not notification:
            logger.warning(f"Не найдено неотправленных уведомлений типа {notification_type} для пользователя {user_id}")
            return False
        
        # Обновляем статус
        # Сохраняем ID до commit
        notification_id = notification.id
        notification.is_sent = True
        notification.sent_at = datetime.now()
        
        await db.commit()
        
        logger.info(f"Уведомление о миграции ID {notification_id} помечено как отправленное")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса уведомления для пользователя {user_id}: {e}")
        await db.rollback()
        return False


# Функции для работы с заявками на отмену автопродления

async def create_autorenewal_cancellation_request(db: AsyncSession, user_id: int, reason: str = None) -> AutorenewalCancellationRequest:
    """Создает заявку на отмену автопродления"""
    request = AutorenewalCancellationRequest(
        user_id=user_id,
        status='pending',
        reason=reason
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    logger.info(f"Создана заявка на отмену автопродления ID {request.id} для пользователя {user_id} с причиной: {reason}")
    return request

async def get_pending_cancellation_requests(db: AsyncSession) -> List[AutorenewalCancellationRequest]:
    """Получает все ожидающие заявки"""
    query = select(AutorenewalCancellationRequest).where(
        AutorenewalCancellationRequest.status == 'pending'
    ).order_by(AutorenewalCancellationRequest.created_at)
    result = await db.execute(query)
    return result.scalars().all()

async def get_cancellation_request_by_id(db: AsyncSession, request_id: int) -> Optional[AutorenewalCancellationRequest]:
    """Получает заявку по ID"""
    query = select(AutorenewalCancellationRequest).where(
        AutorenewalCancellationRequest.id == request_id
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def get_all_cancellation_requests(db: AsyncSession, status: Optional[str] = None, limit: int = 50) -> List[AutorenewalCancellationRequest]:
    """Получает все заявки (или с фильтром по статусу)"""
    query = select(AutorenewalCancellationRequest)
    if status:
        query = query.where(AutorenewalCancellationRequest.status == status)
    query = query.order_by(AutorenewalCancellationRequest.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

async def get_cancellation_requests_stats(db: AsyncSession) -> dict:
    """Получает статистику по заявкам"""
    from sqlalchemy import func
    
    # Общее количество
    total_query = select(func.count()).select_from(AutorenewalCancellationRequest)
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0
    
    # По статусам
    stats_query = select(
        AutorenewalCancellationRequest.status,
        func.count(AutorenewalCancellationRequest.id).label('count')
    ).group_by(AutorenewalCancellationRequest.status)
    
    stats_result = await db.execute(stats_query)
    stats = {row.status: row.count for row in stats_result.all()}
    
    return {
        'total': total,
        'pending': stats.get('pending', 0),
        'contacted': stats.get('contacted', 0),
        'approved': stats.get('approved', 0),
        'rejected': stats.get('rejected', 0)
    }

async def update_cancellation_request_status(
    db: AsyncSession, 
    request_id: int, 
    status: str, 
    reviewed_by: Optional[int] = None,
    admin_notes: Optional[str] = None
) -> bool:
    """Обновляет статус заявки"""
    query = (
        update(AutorenewalCancellationRequest)
        .where(AutorenewalCancellationRequest.id == request_id)
        .values(
            status=status,
            reviewed_at=datetime.now(),
            reviewed_by=reviewed_by,
            admin_notes=admin_notes
        )
    )
    await db.execute(query)
    await db.commit()
    logger.info(f"Обновлен статус заявки {request_id} на '{status}'")
    return True

async def mark_cancellation_request_contacted(db: AsyncSession, request_id: int) -> bool:
    """Отмечает заявку как 'связались с пользователем'"""
    query = (
        update(AutorenewalCancellationRequest)
        .where(AutorenewalCancellationRequest.id == request_id)
        .values(
            status='contacted',
            contacted_at=datetime.now()
        )
    )
    await db.execute(query)
    await db.commit()
    logger.info(f"Заявка {request_id} отмечена как 'связались с пользователем'")
    return True

async def send_cancellation_request_notifications(bot, user, request_id: int, reason: str = None):
    """Отправляет уведомления админам о новой заявке на отмену автопродления"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from database.config import AsyncSessionLocal
    
    logger = logging.getLogger(__name__)
    
    try:
        async with AsyncSessionLocal() as session:
            active_sub = await get_active_subscription(session, user.id)
            
            user_info = f"{user.first_name} {user.last_name or ''} (@{user.username})" if user.username else f"{user.first_name} {user.last_name or ''} (ID: {user.telegram_id})"
            
            subscription_info = ""
            if active_sub:
                end_date = active_sub.end_date.strftime('%d.%m.%Y')
                subscription_info = f"\n📅 Подписка до: {end_date}"
            
            reason_info = f"\n📝 Причина: {reason}" if reason else ""
            
            # Уведомление админам
            admin_notification = (
                f"🚫 <b>Заявка на отмену автопродления</b>\n\n"
                f"👤 Пользователь: {user_info}\n"
                f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
                f"📱 Телефон: {user.phone or 'не указан'}{subscription_info}{reason_info}\n"
                f"🆔 ID заявки: <code>{request_id}</code>\n\n"
                f"⏳ Требуется обработать заявку"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_cancel_renewal_{request_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_cancel_renewal_{request_id}")],
                [InlineKeyboardButton(text="📋 Список заявок", callback_data="admin_pending_cancellations")]
            ])
            
            # Отправляем только админам
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        admin_notification,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                    logger.info(f"Уведомление о заявке {request_id} отправлено админу {admin_id}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
            
            # Уведомление службе заботы УБРАНО (админ рассматривает все заявки)
                
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений о заявке: {e}", exc_info=True)


# ==================== ФУНКЦИИ ДЛЯ РАСШИРЕННОЙ АНАЛИТИКИ ====================

async def get_new_users_by_date(db: AsyncSession, days: int = 30) -> List[Tuple[date, int]]:
    """
    Получает количество новых пользователей по дням за последние N дней
    
    Args:
        db: Сессия БД
        days: Количество дней для анализа (по умолчанию 30)
        
    Returns:
        Список кортежей (дата, количество новых пользователей)
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    # Получаем всех новых пользователей, созданных в указанный период
    query = select(
        func.date(User.created_at).label('date'),
        func.count(User.id).label('count')
    ).where(
        and_(
            func.date(User.created_at) >= start_date,
            func.date(User.created_at) <= end_date
        )
    ).group_by(
        func.date(User.created_at)
    ).order_by(
        func.date(User.created_at)
    )
    
    result = await db.execute(query)
    rows = result.all()
    
    # Создаем словарь для быстрого доступа
    # В SQLite func.date() возвращает строку, нужно конвертировать в date
    users_by_date = {}
    for row in rows:
        # row.date может быть строкой или date объектом
        if isinstance(row.date, str):
            # Конвертируем строку в date
            try:
                date_obj = datetime.strptime(row.date, '%Y-%m-%d').date()
            except:
                # Если формат другой, пробуем другой вариант
                try:
                    date_obj = datetime.fromisoformat(row.date).date()
                except:
                    logger.error(f"Не удалось распарсить дату пользователя: {row.date}")
                    continue
        else:
            date_obj = row.date if isinstance(row.date, date) else row.date.date()
        users_by_date[date_obj] = row.count
    
    # Заполняем все дни (даже если пользователей не было)
    result_list = []
    current_date = start_date
    while current_date <= end_date:
        count = users_by_date.get(current_date, 0)
        result_list.append((current_date, count))
        current_date += timedelta(days=1)
    
    return result_list


async def get_new_subscriptions_by_date(db: AsyncSession, days: int = 30) -> List[Tuple[date, int]]:
    """
    Получает количество продаж (все подписки включая продления) по дням за последние N дней
    
    ВАЖНО: Используем дату платежа (PaymentLog.created_at), а не дату создания подписки,
    потому что продажа происходит в момент оплаты, а не в момент создания подписки.
    Это особенно важно для платежей, которые приходят ночью (например, платеж от 12.11 в 00:39,
    но подписка была создана 11.11 в 21:39).
    
    Args:
        db: Сессия БД
        days: Количество дней для анализа (по умолчанию 30)
        
    Returns:
        Список кортежей (дата, количество продаж)
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    # Получаем все успешные платежи (продажи) по дате оплаты
    # Используем PaymentLog.created_at, который обновляется на реальное время оплаты от ЮКассы
    query = select(
        func.date(PaymentLog.created_at).label('date'),
        func.count(PaymentLog.id).label('count')
    ).where(
        and_(
            PaymentLog.status == 'success',
            PaymentLog.is_confirmed == True,
            PaymentLog.payment_method == 'yookassa',  # Только платежи через ЮКассу
            PaymentLog.transaction_id.isnot(None),  # Только с transaction_id от ЮКассы
            func.date(PaymentLog.created_at) >= start_date,
            func.date(PaymentLog.created_at) <= end_date
        )
    ).group_by(
        func.date(PaymentLog.created_at)
    ).order_by(
        func.date(PaymentLog.created_at)
    )
    
    result = await db.execute(query)
    rows = result.all()
    
    # Создаем словарь для быстрого доступа
    # В SQLite func.date() возвращает строку, нужно конвертировать в date
    subscriptions_by_date = {}
    for row in rows:
        # row.date может быть строкой или date объектом
        if isinstance(row.date, str):
            # Конвертируем строку в date
            try:
                date_obj = datetime.strptime(row.date, '%Y-%m-%d').date()
            except:
                # Если формат другой, пробуем другой вариант
                try:
                    date_obj = datetime.fromisoformat(row.date).date()
                except:
                    logger.error(f"Не удалось распарсить дату: {row.date}")
                    continue
        else:
            date_obj = row.date if isinstance(row.date, date) else row.date.date()
        subscriptions_by_date[date_obj] = row.count
    
    # Заполняем все дни (даже если подписок не было)
    result_list = []
    current_date = start_date
    while current_date <= end_date:
        count = subscriptions_by_date.get(current_date, 0)
        result_list.append((current_date, count))
        current_date += timedelta(days=1)
    
    return result_list


async def get_conversion_rate(db: AsyncSession) -> dict:
    """
    Рассчитывает конверсию: регистрации → платежи
    
    Returns:
        Словарь с метриками конверсии
    """
    # Всего пользователей
    total_users_query = select(func.count(User.id))
    total_users_result = await db.execute(total_users_query)
    total_users = total_users_result.scalar() or 0
    
    # Пользователей с хотя бы одним успешным платежом
    users_with_payments_query = select(func.count(func.distinct(PaymentLog.user_id))).where(
        and_(
            PaymentLog.status == 'success',
            PaymentLog.is_confirmed == True
        )
    )
    users_with_payments_result = await db.execute(users_with_payments_query)
    users_with_payments = users_with_payments_result.scalar() or 0
    
    # Пользователей с активной подпиской (исключая пожизненные)
    now = datetime.now()
    lifetime_threshold = datetime(2099, 1, 1)
    active_subs_query = select(func.count(func.distinct(Subscription.user_id))).where(
        and_(
            Subscription.is_active == True,
            Subscription.end_date > now,
            Subscription.end_date < lifetime_threshold  # Исключаем пожизненные
        )
    )
    active_subs_result = await db.execute(active_subs_query)
    users_with_active_subs = active_subs_result.scalar() or 0
    
    # Конверсия
    conversion_to_payment = round((users_with_payments / total_users * 100), 2) if total_users > 0 else 0
    conversion_to_active = round((users_with_active_subs / total_users * 100), 2) if total_users > 0 else 0
    
    return {
        'total_users': total_users,
        'users_with_payments': users_with_payments,
        'users_with_active_subs': users_with_active_subs,
        'conversion_to_payment': conversion_to_payment,
        'conversion_to_active': conversion_to_active
    }


async def get_average_ltv(db: AsyncSession) -> dict:
    """
    Рассчитывает средний LTV (lifetime value) пользователя
    
    Returns:
        Словарь с метриками LTV
    """
    # Общая сумма всех успешных платежей (только реально оплаченные через webhook от ЮКассы)
    total_revenue_query = select(func.sum(PaymentLog.amount)).where(
        and_(
            PaymentLog.status == 'success',
            PaymentLog.is_confirmed == True,
            PaymentLog.payment_method == 'yookassa',  # Только платежи через ЮКассу
            PaymentLog.transaction_id.isnot(None)  # Только с transaction_id от ЮКассы
        )
    )
    total_revenue_result = await db.execute(total_revenue_query)
    total_revenue = total_revenue_result.scalar() or 0
    
    # Количество уникальных платящих пользователей (только реально оплаченные через webhook)
    paying_users_query = select(func.count(func.distinct(PaymentLog.user_id))).where(
        and_(
            PaymentLog.status == 'success',
            PaymentLog.is_confirmed == True,
            PaymentLog.payment_method == 'yookassa',  # Только платежи через ЮКассу
            PaymentLog.transaction_id.isnot(None)  # Только с transaction_id от ЮКассы
        )
    )
    paying_users_result = await db.execute(paying_users_query)
    paying_users = paying_users_result.scalar() or 0
    
    # Средний LTV
    avg_ltv = round(total_revenue / paying_users, 2) if paying_users > 0 else 0
    
    # Средний LTV всех пользователей (включая не плативших)
    total_users_query = select(func.count(User.id))
    total_users_result = await db.execute(total_users_query)
    total_users = total_users_result.scalar() or 0
    avg_ltv_all = round(total_revenue / total_users, 2) if total_users > 0 else 0
    
    return {
        'total_revenue': total_revenue,
        'paying_users': paying_users,
        'avg_ltv_paying': avg_ltv,
        'avg_ltv_all': avg_ltv_all
    }


async def get_revenue_by_month(db: AsyncSession, months: int = 6) -> List[Tuple[str, int]]:
    """
    Рассчитывает выручку по месяцам
    
    Args:
        db: Сессия БД
        months: Количество месяцев для анализа (по умолчанию 6)
        
    Returns:
        Список кортежей (месяц в формате YYYY-MM, выручка в рублях)
    """
    revenue_data = []
    
    # Для каждого месяца рассчитываем выручку
    now = datetime.now()
    for i in range(months):
        # Месяц для анализа
        target_month = now - timedelta(days=30 * (months - i - 1))
        month_start = target_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        month_end = month_end.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Сохраняем оригинальный месяц для ключа (до изменения периода)
        month_key = month_start.strftime('%Y-%m')
        
        # Специальная обработка для месяцев 2025:
        # - Октябрь 2025: включаем ВСЕ платежи от 31.10.2025 (период 1-31.10)
        # - Ноябрь 2025: включаем платежи 1-12.11 + только один платеж от 31.10 (который был в отчете ЮКассы)
        #   Transaction ID валидного платежа от 31.10: "309703e0-000f-5000-b000-1f83368cb27c"
        query_start = month_start
        special_oct31_transaction_id = None  # Для ноября: исключаем лишние платежи от 31.10
        if month_start.year == 2025:
            if month_start.month == 10:
                # Октябрь: включаем все платежи от 31.10 (период 1-31.10)
                month_end = datetime(2025, 10, 31, 23, 59, 59, 999999)
            elif month_start.month == 11:
                # Ноябрь: включаем платежи 1-12.11 + только один платеж от 31.10 (который был в отчете)
                # Исключаем 4 лишних платежа от 31.10, которые не были в отчете ЮКассы
                query_start = datetime(2025, 10, 31, 0, 0, 0)
                special_oct31_transaction_id = "309703e0-000f-5000-b000-1f83368cb27c"
        
        # Для текущего месяца ограничиваем до текущего дня
        if month_start.year == now.year and month_start.month == now.month:
            month_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Выручка за этот месяц (только реально оплаченные платежи через webhook от ЮКассы)
        # ВАЖНО: Используем created_at, который обновляется на реальное время оплаты от ЮКассы (captured_at)
        # в webhook_handlers.py строка 543: payment_log.created_at = payment_datetime
        # где payment_datetime берется из payment.captured_at (время фактической оплаты)
        # Учитываем только платежи, которые:
        # 1. Пришли через webhook (payment_method = 'yookassa')
        # 2. Имеют transaction_id от ЮКассы (не NULL)
        # 3. Подтверждены (is_confirmed = True) - это означает, что webhook обработал платеж
        # 4. Успешны (status = 'success')
        # 5. Оплачены в указанный период (created_at содержит реальное время оплаты от ЮКассы)
        # 6. Для ноября 2025: исключаем лишние платежи от 31.10 (оставляем только один, который был в отчете)
        conditions = [
            PaymentLog.status == 'success',
            PaymentLog.is_confirmed == True,  # Только подтвержденные через webhook
            PaymentLog.payment_method == 'yookassa',  # Только платежи через ЮКассу
            PaymentLog.transaction_id.isnot(None),  # Только с transaction_id от ЮКассы
            PaymentLog.created_at >= query_start,  # Используем query_start (может быть расширен для ноября)
            PaymentLog.created_at <= month_end
        ]
        
        # Для ноября 2025: исключаем лишние платежи от 31.10 (оставляем только один, который был в отчете)
        if special_oct31_transaction_id:
            # Для платежей от 31.10: включаем только тот, который был в отчете ЮКассы
            # Для платежей от 1-12.11: включаем все
            from sqlalchemy import or_
            conditions.append(
                or_(
                    PaymentLog.created_at >= datetime(2025, 11, 1, 0, 0, 0),  # Платежи от 1.11 и позже
                    PaymentLog.transaction_id == special_oct31_transaction_id  # Или валидный платеж от 31.10
                )
            )
        
        revenue_query = select(func.sum(PaymentLog.amount)).where(and_(*conditions))
        revenue_result = await db.execute(revenue_query)
        revenue = revenue_result.scalar() or 0
        
        revenue_data.append((month_key, int(revenue)))  # Используем оригинальный month_key
    
    return revenue_data


async def get_retention_rate_by_month(db: AsyncSession, months: int = 6) -> List[Tuple[str, float]]:
    """
    Рассчитывает retention rate по месяцам
    
    Args:
        db: Сессия БД
        months: Количество месяцев для анализа (по умолчанию 6)
        
    Returns:
        Список кортежей (месяц, retention rate в %)
    """
    retention_data = []
    
    # Для каждого месяца рассчитываем retention
    for i in range(months):
        # Месяц для анализа
        target_month = datetime.now() - timedelta(days=30 * (months - i - 1))
        month_start = target_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        # Пользователи, зарегистрированные в этом месяце
        new_users_query = select(func.count(User.id)).where(
            and_(
                User.created_at >= month_start,
                User.created_at <= month_end
            )
        )
        new_users_result = await db.execute(new_users_query)
        new_users = new_users_result.scalar() or 0
        
        if new_users == 0:
            retention_data.append((month_start.strftime('%Y-%m'), 0.0))
            continue
        
        # Пользователи из этого месяца, у которых есть подписка после регистрации
        retained_users_query = select(func.count(func.distinct(User.id))).join(
            Subscription, User.id == Subscription.user_id
        ).where(
            and_(
                User.created_at >= month_start,
                User.created_at <= month_end,
                Subscription.created_at >= User.created_at  # Подписка после регистрации
            )
        )
        retained_users_result = await db.execute(retained_users_query)
        retained_users = retained_users_result.scalar() or 0
        
        retention_rate = round((retained_users / new_users * 100), 2) if new_users > 0 else 0
        retention_data.append((month_start.strftime('%Y-%m'), retention_rate))
    
    return retention_data


async def get_top_referral_sources(db: AsyncSession, limit: int = 10) -> List[Tuple[str, int, int]]:
    """
    Получает топ источников по реферальным кодам
    
    Args:
        db: Сессия БД
        limit: Количество топ источников (по умолчанию 10)
        
    Returns:
        Список кортежей (referral_code, количество рефералов, количество успешных платежей)
    """
    # Находим всех рефереров (пользователей, которые пригласили других)
    # Группируем по referrer_id и считаем количество рефералов
    referrers_query = select(
        User.referrer_id,
        func.count(User.id).label('referrals_count')
    ).where(
        User.referrer_id.isnot(None)
    ).group_by(
        User.referrer_id
    ).order_by(
        desc('referrals_count')
    ).limit(limit)
    
    referrers_result = await db.execute(referrers_query)
    referrers_rows = referrers_result.all()
    
    # Собираем статистику
    top_sources = []
    for row in referrers_rows:
        referrer_id = row.referrer_id
        referrals_count = row.referrals_count
        
        # Получаем информацию о реферере
        referrer_query = select(User).where(User.id == referrer_id)
        referrer_result = await db.execute(referrer_query)
        referrer = referrer_result.scalar_one_or_none()
        
        if referrer:
            referral_code = referrer.referral_code or 'Без кода'
            
            # Считаем платящих рефералов для этого реферера
            paying_query = select(func.count(func.distinct(User.id))).join(
                PaymentLog,
                and_(
                    PaymentLog.user_id == User.id,
                    PaymentLog.status == 'success',
                    PaymentLog.is_confirmed == True
                )
            ).where(
                User.referrer_id == referrer_id
            )
            paying_result = await db.execute(paying_query)
            paying_count = paying_result.scalar() or 0
            
            top_sources.append((referral_code, referrals_count, paying_count))
    
    return top_sources


async def export_analytics_data(db: AsyncSession, format: str = 'text') -> str:
    """
    Экспортирует данные для аналитики
    
    Args:
        db: Сессия БД
        format: Формат экспорта ('text' или 'csv')
        
    Returns:
        Строка с данными в указанном формате
    """
    from io import StringIO
    import csv
    
    # Получаем все данные
    new_users = await get_new_users_by_date(db, days=30)
    new_subs = await get_new_subscriptions_by_date(db, days=30)
    conversion = await get_conversion_rate(db)
    ltv = await get_average_ltv(db)
    revenue_by_month = await get_revenue_by_month(db, months=6)
    retention = await get_retention_rate_by_month(db, months=6)
    top_sources = await get_top_referral_sources(db, limit=10)
    
    if format == 'csv':
        output = StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(['Метрика', 'Значение'])
        
        # Конверсия
        writer.writerow(['Всего пользователей', conversion['total_users']])
        writer.writerow(['Пользователей с платежами', conversion['users_with_payments']])
        writer.writerow(['Конверсия в платежи (%)', conversion['conversion_to_payment']])
        writer.writerow(['Конверсия в активные подписки (%)', conversion['conversion_to_active']])
        
        # LTV
        writer.writerow(['Общая выручка (₽)', ltv['total_revenue']])
        writer.writerow(['Платящих пользователей', ltv['paying_users']])
        writer.writerow(['Средний LTV платящих (₽)', ltv['avg_ltv_paying']])
        writer.writerow(['Средний LTV всех (₽)', ltv['avg_ltv_all']])
        
        # Выручка по месяцам
        writer.writerow([])
        writer.writerow(['Месяц', 'Выручка (₽)'])
        for month, revenue in revenue_by_month:
            writer.writerow([month, revenue])
        
        # Retention
        writer.writerow([])
        writer.writerow(['Месяц', 'Retention Rate (%)'])
        for month, rate in retention:
            writer.writerow([month, rate])
        
        # Топ источников
        writer.writerow([])
        writer.writerow(['Реферальный код', 'Рефералов', 'Платящих'])
        for code, refs, paying in top_sources:
            writer.writerow([code, refs, paying])
        
        # Новые пользователи по дням
        writer.writerow([])
        writer.writerow(['Дата', 'Новых пользователей'])
        for date_obj, count in new_users[-30:]:  # Последние 30 дней
            writer.writerow([date_obj.strftime('%Y-%m-%d'), count])
        
        # Продажи по дням (все подписки включая продления)
        writer.writerow([])
        writer.writerow(['Дата', 'Продаж (все подписки)'])
        for date_obj, count in new_subs[-30:]:  # Последние 30 дней
            writer.writerow([date_obj.strftime('%Y-%m-%d'), count])
        
        return output.getvalue()
    else:
        # Текстовый формат
        lines = []
        lines.append("📊 ЭКСПОРТ ДАННЫХ АНАЛИТИКИ")
        lines.append("=" * 50)
        lines.append("")
        
        lines.append("КОНВЕРСИЯ:")
        lines.append(f"  Всего пользователей: {conversion['total_users']}")
        lines.append(f"  Пользователей с платежами: {conversion['users_with_payments']}")
        lines.append(f"  Конверсия в платежи: {conversion['conversion_to_payment']}%")
        lines.append(f"  Конверсия в активные подписки: {conversion['conversion_to_active']}%")
        lines.append("")
        
        lines.append("LTV (LIFETIME VALUE):")
        lines.append(f"  Общая выручка: {ltv['total_revenue']} ₽")
        lines.append(f"  Платящих пользователей: {ltv['paying_users']}")
        lines.append(f"  Средний LTV платящих: {ltv['avg_ltv_paying']} ₽")
        lines.append(f"  Средний LTV всех: {ltv['avg_ltv_all']} ₽")
        lines.append("")
        
        lines.append("ВЫРУЧКА ПО МЕСЯЦАМ (последние 6 месяцев):")
        for month, revenue in revenue_by_month:
            lines.append(f"  {month}: {revenue} ₽")
        lines.append("")
        
        lines.append("RETENTION RATE ПО МЕСЯЦАМ:")
        for month, rate in retention:
            lines.append(f"  {month}: {rate}%")
        lines.append("")
        
        lines.append("ТОП ИСТОЧНИКОВ (РЕФЕРАЛЬНЫЕ КОДЫ):")
        for code, refs, paying in top_sources:
            lines.append(f"  {code}: {refs} рефералов ({paying} платящих)")
        lines.append("")
        
        lines.append("НОВЫЕ ПОЛЬЗОВАТЕЛИ ПО ДНЯМ (последние 30 дней):")
        for date_obj, count in new_users[-30:]:  # Последние 30 дней
            lines.append(f"  {date_obj.strftime('%d.%m.%Y')}: {count}")
        lines.append("")
        
        lines.append("ПРОДАЖИ ПО ДНЯМ (последние 30 дней, все подписки включая продления):")
        for date_obj, count in new_subs[-30:]:  # Последние 30 дней
            lines.append(f"  {date_obj.strftime('%d.%m.%Y')}: {count}")
        
        return "\n".join(lines)


# --- Функции для работы с активностью в группе ---

async def get_group_activity(db: AsyncSession, user_id: int) -> Optional[GroupActivity]:
    """Получает активность пользователя в группе"""
    query = select(GroupActivity).where(GroupActivity.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_group_activity(db: AsyncSession, user_id: int) -> GroupActivity:
    """Обновляет активность пользователя в группе (увеличивает счетчик сообщений и обновляет дату последней активности)"""
    activity = await get_group_activity(db, user_id)
    now = datetime.now()
    
    if activity:
        # Обновляем существующую запись
        activity.message_count += 1
        activity.last_activity = now
        activity.updated_at = now
    else:
        # Создаем новую запись
        activity = GroupActivity(
            user_id=user_id,
            message_count=1,
            last_activity=now,
            created_at=now,
            updated_at=now
        )
        db.add(activity)
    
    await db.commit()
    await db.refresh(activity)
    logger.debug(f"Обновлена активность пользователя {user_id}: сообщений={activity.message_count}, последняя активность={activity.last_activity}")
    return activity


async def update_group_activity_log(db: AsyncSession, user_id: int) -> None:
    """
    Обновляет детальный лог активности пользователя в группе за текущий день.
    Создаёт новую запись если её нет, или увеличивает счётчик если запись есть.
    """
    from database.models import GroupActivityLog
    from sqlalchemy import select
    
    today = datetime.now().date()
    
    # Ищем запись за сегодня
    query = select(GroupActivityLog).where(
        GroupActivityLog.user_id == user_id,
        GroupActivityLog.date == today
    )
    result = await db.execute(query)
    log_entry = result.scalar_one_or_none()
    
    if log_entry:
        # Обновляем существующую запись
        log_entry.message_count += 1
        log_entry.updated_at = datetime.now()
    else:
        # Создаём новую запись за сегодня
        log_entry = GroupActivityLog(
            user_id=user_id,
            date=today,
            message_count=1
        )
        db.add(log_entry)


async def get_top_active_users(db: AsyncSession, limit: int = 20, page: int = 0) -> Tuple[List[Tuple[User, GroupActivity]], int]:
    """
    Получает топ активных пользователей в группе (по количеству сообщений)
    
    Returns:
        Tuple[List[Tuple[User, GroupActivity]], int]: Список кортежей (пользователь, активность) и общее количество
    """
    offset = page * limit
    
    # Запрос с JOIN для получения пользователей с активностью, отсортированных по количеству сообщений
    query = (
        select(User, GroupActivity)
        .join(GroupActivity, User.id == GroupActivity.user_id)
        .order_by(desc(GroupActivity.message_count), desc(GroupActivity.last_activity))
        .offset(offset)
        .limit(limit)
    )
    
    result = await db.execute(query)
    users_with_activity = result.all()
    
    # Получаем общее количество пользователей с активностью
    count_query = select(func.count(GroupActivity.id))
    total_count = await db.scalar(count_query)
    
    return [(user, activity) for user, activity in users_with_activity], total_count or 0


async def get_inactive_users(db: AsyncSession, days: int = 30, limit: int = 20, page: int = 0) -> Tuple[List[Tuple[User, Optional[GroupActivity]]], int]:
    """
    Получает список неактивных пользователей (не писали в группе N дней)
    
    Args:
        days: Количество дней без активности
        limit: Количество пользователей на страницу
        page: Номер страницы
    
    Returns:
        Tuple[List[Tuple[User, Optional[GroupActivity]]], int]: Список кортежей (пользователь, активность) и общее количество
    """
    offset = page * limit
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Запрос для пользователей, которые либо не имеют активности, либо последняя активность была более N дней назад
    query = (
        select(User, GroupActivity)
        .outerjoin(GroupActivity, User.id == GroupActivity.user_id)
        .where(
            or_(
                GroupActivity.last_activity.is_(None),
                GroupActivity.last_activity < cutoff_date
            )
        )
        .order_by(
            case(
                (GroupActivity.last_activity.is_(None), 0),
                else_=1
            ),
            GroupActivity.last_activity.asc()
        )
        .offset(offset)
        .limit(limit)
    )
    
    result = await db.execute(query)
    users_with_activity = result.all()
    
    # Получаем общее количество
    count_query = (
        select(func.count(User.id))
        .outerjoin(GroupActivity, User.id == GroupActivity.user_id)
        .where(
            or_(
                GroupActivity.last_activity.is_(None),
                GroupActivity.last_activity < cutoff_date
            )
        )
    )
    total_count = await db.scalar(count_query) or 0
    
    return [(user, activity) for user, activity in users_with_activity], total_count


# Функции для работы с избранными пользователями
async def add_to_favorites(db: AsyncSession, admin_telegram_id: int, user_telegram_id: int, note: str = None):
    """
    Добавляет пользователя в избранное админа
    
    Args:
        admin_telegram_id: Telegram ID админа
        user_telegram_id: Telegram ID пользователя
        note: Заметка о пользователе
    
    Returns:
        FavoriteUser или None если уже существует
    """
    try:
        favorite = FavoriteUser(
            admin_telegram_id=admin_telegram_id,
            user_telegram_id=user_telegram_id,
            note=note
        )
        db.add(favorite)
        await db.commit()
        await db.refresh(favorite)
        logger.info(f"Админ {admin_telegram_id} добавил пользователя {user_telegram_id} в избранное")
        return favorite
    except IntegrityError:
        await db.rollback()
        logger.warning(f"Пользователь {user_telegram_id} уже в избранном у админа {admin_telegram_id}")
        return None


async def remove_from_favorites(db: AsyncSession, admin_telegram_id: int, user_telegram_id: int):
    """
    Удаляет пользователя из избранного админа
    
    Args:
        admin_telegram_id: Telegram ID админа
        user_telegram_id: Telegram ID пользователя
    
    Returns:
        True если удалено, False если не найдено
    """
    query = select(FavoriteUser).where(
        and_(
            FavoriteUser.admin_telegram_id == admin_telegram_id,
            FavoriteUser.user_telegram_id == user_telegram_id
        )
    )
    result = await db.execute(query)
    favorite = result.scalar_one_or_none()
    
    if favorite:
        await db.delete(favorite)
        await db.commit()
        logger.info(f"Админ {admin_telegram_id} удалил пользователя {user_telegram_id} из избранного")
        return True
    return False


async def update_favorite_note(db: AsyncSession, admin_telegram_id: int, user_telegram_id: int, note: str):
    """
    Обновляет заметку для избранного пользователя
    
    Args:
        admin_telegram_id: Telegram ID админа
        user_telegram_id: Telegram ID пользователя
        note: Новая заметка
    
    Returns:
        True если обновлено, False если не найдено
    """
    query = (
        update(FavoriteUser)
        .where(
            and_(
                FavoriteUser.admin_telegram_id == admin_telegram_id,
                FavoriteUser.user_telegram_id == user_telegram_id
            )
        )
        .values(note=note, updated_at=datetime.now())
    )
    result = await db.execute(query)
    await db.commit()
    
    if result.rowcount > 0:
        logger.info(f"Админ {admin_telegram_id} обновил заметку для пользователя {user_telegram_id}")
        return True
    return False


async def get_favorite(db: AsyncSession, admin_telegram_id: int, user_telegram_id: int):
    """
    Получает запись избранного пользователя
    
    Args:
        admin_telegram_id: Telegram ID админа
        user_telegram_id: Telegram ID пользователя
    
    Returns:
        FavoriteUser или None
    """
    query = select(FavoriteUser).where(
        and_(
            FavoriteUser.admin_telegram_id == admin_telegram_id,
            FavoriteUser.user_telegram_id == user_telegram_id
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def is_favorite(db: AsyncSession, admin_telegram_id: int, user_telegram_id: int) -> bool:
    """
    Проверяет, находится ли пользователь в избранном админа
    
    Args:
        admin_telegram_id: Telegram ID админа
        user_telegram_id: Telegram ID пользователя
    
    Returns:
        True если в избранном, иначе False
    """
    favorite = await get_favorite(db, admin_telegram_id, user_telegram_id)
    return favorite is not None


async def get_admin_favorites(db: AsyncSession, admin_telegram_id: int, limit: int = 50, page: int = 0):
    """
    Получает список избранных пользователей админа с их данными
    
    Args:
        admin_telegram_id: Telegram ID админа
        limit: Количество на страницу
        page: Номер страницы
    
    Returns:
        Tuple[List[Tuple[User, FavoriteUser]], int]: Список кортежей (пользователь, избранное) и общее количество
    """
    offset = page * limit
    
    # Запрос с join к User для получения актуальных данных
    query = (
        select(User, FavoriteUser)
        .join(FavoriteUser, User.telegram_id == FavoriteUser.user_telegram_id)
        .where(FavoriteUser.admin_telegram_id == admin_telegram_id)
        .order_by(FavoriteUser.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    
    result = await db.execute(query)
    favorites_with_users = result.all()
    
    # Получаем общее количество
    count_query = (
        select(func.count(FavoriteUser.id))
        .where(FavoriteUser.admin_telegram_id == admin_telegram_id)
    )
    total_count = await db.scalar(count_query) or 0
    
    return [(user, favorite) for user, favorite in favorites_with_users], total_count


# =============================================================================
# РЕФЕРАЛЬНАЯ СИСТЕМА 2.0 - CRUD ФУНКЦИИ
# =============================================================================

async def add_referral_balance(session: AsyncSession, user_id: int, amount: int, bot=None) -> bool:
    """
    Добавляет средства на реферальный баланс пользователя
    
    Args:
        session: Сессия БД
        user_id: ID пользователя
        amount: Сумма для начисления в рублях
        bot: Экземпляр бота для отправки уведомлений (опционально)
        
    Returns:
        True если успешно, False при ошибке
    """
    try:
        user = await get_user_by_id(session, user_id)
        if not user:
            logger.error(f"[referral] Пользователь {user_id} не найден")
            return False
        
        # Запоминаем старый баланс для проверки порогов
        old_balance = user.referral_balance or 0
        
        query = (
            update(User)
            .where(User.id == user_id)
            .values(
                referral_balance=User.referral_balance + amount,
                total_earned_referral=User.total_earned_referral + amount
            )
        )
        await session.execute(query)
        await session.commit()
        
        # Получаем новый баланс
        await session.refresh(user)
        new_balance = user.referral_balance or 0
        
        logger.info(f"[referral] Начислено {amount}₽ на баланс пользователя {user_id} (было {old_balance}₽, стало {new_balance}₽)")
        
        # Проверяем достижение порога накопления
        if bot:
            from utils.balance_payment_helpers import check_balance_milestone, send_balance_milestone_notification
            
            milestone = check_balance_milestone(old_balance, new_balance)
            if milestone > 0:
                logger.info(f"[referral] Пользователь {user_id} достиг порога {milestone}₽!")
                # Отправляем уведомление асинхронно
                try:
                    await send_balance_milestone_notification(bot, user.telegram_id, milestone)
                except Exception as e:
                    logger.error(f"[referral] Ошибка при отправке уведомления о порога: {e}")
        
        return True
    except Exception as e:
        logger.error(f"[referral] Ошибка при начислении баланса: {e}")
        await session.rollback()
        return False


async def deduct_referral_balance(session: AsyncSession, user_id: int, amount: int) -> bool:
    """
    Списывает средства с реферального баланса пользователя
    
    Args:
        session: Сессия БД
        user_id: ID пользователя
        amount: Сумма для списания в рублях
        
    Returns:
        True если успешно, False при ошибке или недостатке средств
    """
    try:
        user = await get_user_by_id(session, user_id)
        if not user:
            logger.error(f"[referral] Пользователь {user_id} не найден")
            return False
        
        if user.referral_balance < amount:
            logger.error(f"[referral] Недостаточно средств на балансе пользователя {user_id}")
            return False
        
        query = (
            update(User)
            .where(User.id == user_id)
            .values(referral_balance=User.referral_balance - amount)
        )
        await session.execute(query)
        await session.commit()
        
        logger.info(f"[referral] Списано {amount}₽ с баланса пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"[referral] Ошибка при списании баланса: {e}")
        await session.rollback()
        return False


async def create_referral_reward(
    session: AsyncSession,
    referrer_id: int,
    referee_id: int,
    payment_amount: int,
    reward_type: str,
    reward_amount: int,
    loyalty_level: str,
    bonus_percent: int,
    payment_id: int = None
) -> bool:
    """
    Создает запись о реферальной награде
    
    Args:
        session: Сессия БД
        referrer_id: ID реферера (кто получил награду)
        referee_id: ID реферала (кто оплатил)
        payment_amount: Сумма покупки реферала
        reward_type: Тип награды ('money' или 'days')
        reward_amount: Размер награды (рубли или дни)
        loyalty_level: Уровень лояльности реферера
        bonus_percent: Процент бонуса
        payment_id: ID платежа (для отслеживания постоянных выплат)
        
    Returns:
        True если успешно, False при ошибке
    """
    try:
        from database.models import ReferralReward
        
        reward = ReferralReward(
            referrer_id=referrer_id,
            referee_id=referee_id,
            payment_id=payment_id,
            payment_amount=payment_amount,
            reward_type=reward_type,
            reward_amount=reward_amount,
            loyalty_level=loyalty_level,
            bonus_percent=bonus_percent
        )
        
        session.add(reward)
        
        # НЕКРИТИЧЕСКАЯ ПРОБЛЕМА #1: Увеличиваем счетчик только при ПЕРВОЙ награде от этого реферала
        # Проверяем, есть ли уже награды от этого реферала
        check_query = select(func.count(ReferralReward.id)).where(
            ReferralReward.referrer_id == referrer_id,
            ReferralReward.referee_id == referee_id
        )
        existing_count = await session.scalar(check_query) or 0
        
        if existing_count == 0:
            # Это первая награда от этого реферала - увеличиваем счетчик
            query = (
                update(User)
                .where(User.id == referrer_id)
                .values(total_referrals_paid=User.total_referrals_paid + 1)
            )
            await session.execute(query)
            logger.info(f"[referral] Увеличен счетчик total_referrals_paid для реферера {referrer_id}")
        
        await session.commit()
        
        logger.info(f"[referral] Создана запись награды: реферер={referrer_id}, тип={reward_type}, сумма={reward_amount}")
        return True
    except Exception as e:
        logger.error(f"[referral] Ошибка при создании записи награды: {e}")
        await session.rollback()
        return False


async def get_referral_rewards(session: AsyncSession, user_id: int, limit: int = 10):
    """
    Получает историю реферальных наград пользователя
    
    Args:
        session: Сессия БД
        user_id: ID пользователя (реферера)
        limit: Максимальное количество записей
        
    Returns:
        List[Tuple[ReferralReward, User]]: Список кортежей (награда, реферал)
    """
    try:
        from database.models import ReferralReward
        
        query = (
            select(ReferralReward, User)
            .join(User, ReferralReward.referee_id == User.id)
            .where(ReferralReward.referrer_id == user_id)
            .order_by(ReferralReward.created_at.desc())
            .limit(limit)
        )
        
        result = await session.execute(query)
        rewards = result.all()
        
        return [(reward, user) for reward, user in rewards]
    except Exception as e:
        logger.error(f"[referral] Ошибка при получении истории наград: {e}")
        return []


async def is_eligible_for_money_reward(session: AsyncSession, user_id: int) -> bool:
    """
    Проверяет, может ли пользователь получать денежные награды
    (админы и пользователи с бесконечной подпиской не могут)
    
    Args:
        session: Сессия БД
        user_id: ID пользователя
        
    Returns:
        True если может получать деньги, False если нет
    """
    try:
        user = await get_user_by_id(session, user_id)
        if not user:
            return False
        
        # Админы не получают деньги
        if user.admin_group:
            logger.info(f"[referral] Пользователь {user_id} - админ, денежные награды недоступны")
            return False
        
        # Проверяем бесконечную подписку
        subscription = await get_active_subscription(session, user.id)
        if subscription:
            from datetime import datetime
            # Если подписка заканчивается после 2050 года - считаем бесконечной
            if subscription.end_date.year > 2050:
                logger.info(f"[referral] Пользователь {user_id} имеет бесконечную подписку, денежные награды недоступны")
                return False
        
        return True
    except Exception as e:
        logger.error(f"[referral] Ошибка при проверке права на денежные награды: {e}")
        return False


async def create_withdrawal_request(
    session: AsyncSession,
    user_id: int,
    amount: int,
    payment_method: str,
    payment_details: str
) -> bool:
    """
    Создает заявку на вывод реферальных средств
    
    Args:
        session: Сессия БД
        user_id: ID пользователя
        amount: Сумма вывода в рублях
        payment_method: Способ вывода ('card' или 'sbp')
        payment_details: Реквизиты (номер карты или телефона)
        
    Returns:
        True если успешно, False при ошибке
    """
    try:
        from database.models import WithdrawalRequest
        
        # Проверяем баланс
        user = await get_user_by_id(session, user_id)
        if not user or user.referral_balance < amount:
            logger.error(f"[referral] Недостаточно средств для вывода")
            return False
        
        # Проверяем минимальную сумму (из constants)
        if amount < 500:
            logger.error(f"[referral] Сумма вывода меньше минимальной (500₽)")
            return False
        
        withdrawal = WithdrawalRequest(
            user_id=user_id,
            amount=amount,
            payment_method=payment_method,
            payment_details=payment_details,
            status='pending'
        )
        
        session.add(withdrawal)
        await session.commit()
        
        logger.info(f"[referral] Создана заявка на вывод {amount}₽ для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"[referral] Ошибка при создании заявки на вывод: {e}")
        await session.rollback()
        return False


async def get_withdrawal_requests(session: AsyncSession, status: str = None, limit: int = 50):
    """
    Получает заявки на вывод средств
    
    Args:
        session: Сессия БД
        status: Фильтр по статусу ('pending', 'approved', 'rejected') или None для всех
        limit: Максимальное количество записей
        
    Returns:
        List[Tuple[WithdrawalRequest, User]]: Список кортежей (заявка, пользователь)
    """
    try:
        from database.models import WithdrawalRequest
        
        query = (
            select(WithdrawalRequest, User)
            .join(User, WithdrawalRequest.user_id == User.id)
            .order_by(WithdrawalRequest.created_at.desc())
        )
        
        if status:
            query = query.where(WithdrawalRequest.status == status)
        
        query = query.limit(limit)
        
        result = await session.execute(query)
        requests = result.all()
        
        return [(withdrawal, user) for withdrawal, user in requests]
    except Exception as e:
        logger.error(f"[referral] Ошибка при получении заявок на вывод: {e}")
        return []


async def process_withdrawal_request(
    session: AsyncSession,
    request_id: int,
    admin_id: int,
    new_status: str,
    admin_comment: str = None
) -> bool:
    """
    Обрабатывает заявку на вывод средств (одобрение/отклонение)
    
    Args:
        session: Сессия БД
        request_id: ID заявки
        admin_id: ID админа, который обрабатывает
        new_status: Новый статус ('approved' или 'rejected')
        admin_comment: Комментарий админа (опционально)
        
    Returns:
        True если успешно, False при ошибке
    """
    try:
        from database.models import WithdrawalRequest
        from datetime import datetime
        
        withdrawal = await session.get(WithdrawalRequest, request_id)
        if not withdrawal:
            logger.error(f"[referral] Заявка {request_id} не найдена")
            return False
        
        if withdrawal.status != 'pending':
            logger.error(f"[referral] Заявка {request_id} уже обработана")
            return False
        
        # Если одобрено - списываем средства
        if new_status == 'approved':
            success = await deduct_referral_balance(session, withdrawal.user_id, withdrawal.amount)
            if not success:
                logger.error(f"[referral] Не удалось списать средства для заявки {request_id}")
                return False
        
        # Обновляем статус заявки
        query = (
            update(WithdrawalRequest)
            .where(WithdrawalRequest.id == request_id)
            .values(
                status=new_status,
                processed_at=datetime.now(),
                processed_by_admin_id=admin_id,
                admin_comment=admin_comment
            )
        )
        await session.execute(query)
        await session.commit()
        
        logger.info(f"[referral] Заявка {request_id} обработана: {new_status}")
        return True
    except Exception as e:
        logger.error(f"[referral] Ошибка при обработке заявки: {e}")
        await session.rollback()
        return False

