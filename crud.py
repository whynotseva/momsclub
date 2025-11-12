from sqlalchemy import select, func, update, and_, or_, exists, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, case, desc
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, date
from database.models import User, Subscription, PaymentLog, PromoCode, UserPromoCode, SubscriptionNotification, MessageTemplate, ScheduledMessage, ScheduledMessageRecipient, AutorenewalCancellationRequest
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
    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        phone=phone
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
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

async def update_user(db: AsyncSession, telegram_id: int, commit: bool = True, **kwargs):
    """
    Обновляет данные пользователя
    
    Args:
        commit: Если False, не выполняет commit (для использования в транзакциях)
    """
    query = update(User).where(User.telegram_id == telegram_id).values(**kwargs)
    await db.execute(query)
    if commit:
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
                              subscription_id: Optional[str] = None,
                              commit: bool = True):
    """
    Создает новую подписку для пользователя, ПРОВЕРЯЯ наличие активной.
    
    Args:
        commit: Если False, не выполняет commit (для использования в транзакциях)
    """
    # Проверяем, нет ли уже активной подписки
    existing_active_sub = await get_active_subscription(db, user_id)
    if existing_active_sub:
        logger.warning(f"Попытка создать новую активную подписку для user_id={user_id}, хотя активная (ID: {existing_active_sub.id}) уже существует.")
        # Если активная подписка уже существует, не создаем новую, а возвращаем существующую.
        # Это поведение может потребовать пересмотра в зависимости от бизнес-логики.
        # Возможно, стоит обновить существующую, если параметры новой более выгодны или актуальны.
        return existing_active_sub

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
    if commit:
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
                              subscription_id: Optional[str] = None, # Добавляем subscription_id для Prodamus
                              commit: bool = True
                              ):
    """
    Продлевает подписку пользователя или создает новую, обновляя данные для автопродления.
    
    Args:
        commit: Если False, не выполняет commit (для использования в транзакциях)
    """
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
        
        # Добавляем subscription_id только если он передан (Prodamus)
        if subscription_id is not None:
            update_values["subscription_id"] = subscription_id
            
        query = (
            update(Subscription)
            .where(Subscription.id == active_subscription.id)
            .values(**update_values)
        )
        await db.execute(query)
        if commit:
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
            payment_id=payment_id,  # Исправлено: именованный аргумент
            renewal_price=actual_renewal_price, 
            renewal_duration_days=actual_renewal_duration_days,
            subscription_id=subscription_id,  # Передаем subscription_id для новых подписок
            commit=commit
        )

# Функции для логирования платежей
async def create_payment_log(db: AsyncSession, user_id: int, amount: int, status: str, 
                            subscription_id: int = None, payment_method: str = None, 
                            transaction_id: str = None, details: str = None, 
                            payment_label: str = None, days: Optional[int] = None,
                            payment_datetime: Optional[datetime] = None,
                            commit: bool = True):
    """
    Создает запись о платеже в логе с дополнительной меткой платежа и количеством дней.
    
    Args:
        payment_datetime: Реальное время платежа от платежной системы (если доступно).
                         Если не указано, используется текущее время.
        commit: Если False, не выполняет commit (для использования в транзакциях)
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
            created_at=payment_datetime
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
            days=days
        )
    
    db.add(payment_log)
    if commit:
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
    """Получает количество активных подписок"""
    now = datetime.now()
    query = select(func.count(Subscription.id)).where(
        and_(
            Subscription.is_active == True,
            Subscription.end_date > now
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

async def update_payment_status(db: AsyncSession, payment_id: int, status: str, commit: bool = True):
    """
    Обновляет статус платежа
    
    Args:
        commit: Если False, не выполняет commit (для использования в транзакциях)
    """
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
    if commit:
        await db.commit()
    
async def update_payment_subscription(db: AsyncSession, payment_id: int, subscription_id: int, commit: bool = True):
    """
    Обновляет привязку платежа к подписке
    
    Args:
        commit: Если False, не выполняет commit (для использования в транзакциях)
    """
    query = (
        update(PaymentLog)
        .where(PaymentLog.id == payment_id)
        .values(subscription_id=subscription_id)
    )
    await db.execute(query)
    if commit:
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
    """Получает пользователя по username"""
    query = select(User).where(User.username == username)
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
async def extend_subscription_days(db: AsyncSession, user_id: int, days: int, reason: str = "referral_bonus", commit: bool = True):
    """
    Продлевает подписку пользователя на указанное количество дней
    Возвращает True, если успешно, False в противном случае
    
    Args:
        commit: Если False, не выполняет commit (для использования в транзакциях)
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
        
        if commit:
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
        
        admin_notification = (
            f"{payment_title}\n\n"
            f"{payment_subtitle}\n"
            f"👤 Пользователь: {user_info}\n"
            f"{price_info}\n"
            f"📆 Срок действия: до {subscription.end_date.strftime('%d.%m.%Y')}\n"
            f"🆔 ID транзакции: <code>{transaction_id}</code>\n\n"
            f"✅ Подписка успешно активирована!"
        )
        
        # Отправляем сообщение всем администраторам
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    admin_notification,
                    parse_mode="HTML"
                )
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
        
        # Отправляем сообщение всем администраторам
        if ADMIN_IDS:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        admin_notification,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления о промокоде админу {admin_id}: {e}")
        else:
            logger.warning("Список ADMIN_IDS пуст, уведомление о промокоде не отправлено.")
            
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
        
        # Отправляем сообщение всем администраторам
        if ADMIN_IDS:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        admin_notification,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления о бонусе лояльности админу {admin_id}: {e}")
        else:
            logger.warning("Список ADMIN_IDS пуст, уведомление о бонусе лояльности не отправлено.")
            
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
    """Проверяет, использовал ли пользователь уже этот промокод"""
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

    # Отключаем автопродление на уровне пользователя (НЕ удаляем yookassa_payment_method_id!)
    user_update_query = (
        update(User)
        .where(User.id == user_id)
        .values(
            is_recurring_active=False
            # yookassa_payment_method_id НЕ удаляем - оставляем для возможности повторного включения
        )
    )
    await db.execute(user_update_query)
    logger.info(f"Автопродление отключено для пользователя ID {user_id}. is_recurring_active=False (yookassa_payment_method_id сохранен).")

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
        notification.is_sent = True
        notification.sent_at = datetime.now()
        
        await db.commit()
        
        logger.info(f"Уведомление о миграции ID {notification.id} помечено как отправленное")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса уведомления для пользователя {user_id}: {e}")
        await db.rollback()
        return False


# Функции для работы с заявками на отмену автопродления

async def create_autorenewal_cancellation_request(db: AsyncSession, user_id: int) -> AutorenewalCancellationRequest:
    """Создает заявку на отмену автопродления"""
    request = AutorenewalCancellationRequest(
        user_id=user_id,
        status='pending'
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    logger.info(f"Создана заявка на отмену автопродления ID {request.id} для пользователя {user_id}")
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

async def send_cancellation_request_notifications(bot, user, request_id: int):
    """Отправляет уведомления админам и службе заботы о новой заявке на отмену автопродления"""
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
            
            # Уведомление админам
            admin_notification = (
                f"🚫 <b>Заявка на отмену автопродления</b>\n\n"
                f"👤 Пользователь: {user_info}\n"
                f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
                f"📱 Телефон: {user.phone or 'не указан'}\n"
                f"📧 Email: {user.email or 'не указан'}{subscription_info}\n"
                f"🆔 ID заявки: <code>{request_id}</code>\n\n"
                f"⏳ Требуется обработать заявку"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_cancel_renewal_{request_id}")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_cancel_renewal_{request_id}")],
                [InlineKeyboardButton(text="📋 Список заявок", callback_data="admin_pending_cancellations")]
            ])
            
            # Отправляем админам
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        admin_notification,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления админу {admin_id}: {e}")
            
            # Уведомление службе заботы (@momsclubsupport)
            support_username = "momsclubsupport"
            support_user = await get_user_by_username(session, support_username)
            
            if support_user:
                support_message = (
                    f"🛟 <b>Новая заявка на отмену автопродления</b>\n\n"
                    f"👤 Пользователь: {user_info}\n"
                    f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
                    f"📱 Телефон: {user.phone or 'не указан'}\n"
                    f"📧 Email: {user.email or 'не указан'}{subscription_info}\n\n"
                    f"💬 <b>Пожалуйста, свяжитесь с пользователем, узнайте причину отмены и попробуйте отработать возражения.</b>\n\n"
                    f"После контакта используйте команду:\n"
                    f"<code>/contacted_cancel {request_id}</code>"
                )
                
                try:
                    await bot.send_message(
                        support_user.telegram_id,
                        support_message,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления службе заботы: {e}")
            else:
                logger.warning(f"Служба заботы (@{support_username}) не найдена в базе!")
                
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений о заявке: {e}", exc_info=True)