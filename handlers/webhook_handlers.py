"""
Webhook handlers for YooKassa payment system
Полностью на ЮКассе, без Prodamus
"""

import json
import logging
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import update, select
from typing import Optional, Dict, Any
from pydantic import BaseModel
from dateutil import parser as date_parser
try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False

from database.config import AsyncSessionLocal
from database.crud import (
    get_payment_by_transaction_id,
    update_payment_status,
    update_payment_subscription,
    has_active_subscription,
    extend_subscription,
    create_subscription,
    get_user_by_id,
    send_payment_notification_to_admins,
    get_user_by_telegram_id,
    extend_subscription_days,
    send_referral_bonus_notification,
    send_referee_bonus_notification,
    is_first_payment_by_user,
    check_and_grant_badges,
    update_user,
    get_active_subscription,
    get_payment_by_id,
    create_payment_log,
    send_badge_notification,
    is_eligible_for_money_reward
)
from database.models import PaymentLog, User, Subscription
from utils.constants import REFERRAL_BONUS_DAYS, CLUB_CHANNEL_URL, SUBSCRIPTION_DAYS, REFERRAL_MONEY_PERCENT
from utils.helpers import escape_markdown_v2
from utils.payment import verify_yookassa_signature
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from dotenv import load_dotenv
from yookassa.domain.notification import WebhookNotification, WebhookNotificationEventType
import uvicorn

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
webhook_logger = logging.getLogger("yookassa_webhook")
webhook_logger.setLevel(logging.INFO)
payment_logger = logging.getLogger("payment")

# Получаем токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

# Создаем FastAPI приложение
app = FastAPI()

# Инициализируем rate limiter
# Используем in-memory хранилище (можно заменить на Redis для production)
try:
    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    webhook_logger.info("Rate limiter инициализирован успешно")
except Exception as e:
    webhook_logger.warning(f"Не удалось инициализировать rate limiter: {e}. Продолжаем без rate limiting.")
    limiter = None

# Добавляем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ЮКасса отправляет с разных IP
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)

# Список доверенных IP ЮКассы (можно расширить)
# ЮКасса отправляет вебхуки с разных IP, поэтому используем более мягкие лимиты
YOOKASSA_IPS = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11",
    "77.75.156.35",
    "77.75.154.128/25",
    "2a02:5180::/32"
]

def is_yookassa_ip(ip: str) -> bool:
    """Проверяет, является ли IP адресом ЮКассы"""
    import ipaddress
    try:
        ip_obj = ipaddress.ip_address(ip)
        for yookassa_net in YOOKASSA_IPS:
            try:
                if ip_obj in ipaddress.ip_network(yookassa_net, strict=False):
                    return True
            except ValueError:
                # Если это не сеть, а конкретный IP
                if str(ip_obj) == yookassa_net:
                    return True
    except ValueError:
        pass
    return False


def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Маскирует персональные данные в словаре для безопасного логирования.
    
    Маскирует следующие поля:
    - phone, phone_number, tel - номера телефонов
    - email, e_mail - email адреса
    - user_id, telegram_id - ID пользователей (можно оставить частично)
    - card_number, pan - номера карт
    - cvc, cvv - коды безопасности карт
    
    Args:
        data: словарь с данными для маскировки
        
    Returns:
        словарь с замаскированными данными
    """
    if not isinstance(data, dict):
        return data
    
    masked = {}
    sensitive_keys = [
        'phone', 'phone_number', 'tel', 'mobile',
        'email', 'e_mail', 'mail',
        'card_number', 'pan', 'card',
        'cvc', 'cvv', 'security_code',
        'passport', 'passport_number',
        'inn', 'snils'
    ]
    
    # Поля, которые можно показать частично (первые/последние символы)
    partially_masked_keys = ['user_id', 'telegram_id']
    
    for key, value in data.items():
        key_lower = key.lower()
        
        # Полная маскировка для чувствительных полей
        if any(sensitive in key_lower for sensitive in sensitive_keys):
            if isinstance(value, str) and value:
                # Маскируем все кроме первых 2 и последних 2 символов
                if len(value) > 4:
                    masked[key] = value[:2] + '*' * (len(value) - 4) + value[-2:]
                else:
                    masked[key] = '*' * len(value)
            else:
                masked[key] = '***MASKED***'
        
        # Частичная маскировка для ID (показываем только последние 4 цифры)
        elif any(partial in key_lower for partial in partially_masked_keys):
            if isinstance(value, (str, int)):
                value_str = str(value)
                if len(value_str) > 4:
                    masked[key] = '***' + value_str[-4:]
                else:
                    masked[key] = '***'
            else:
                masked[key] = value
        
        # Рекурсивная обработка вложенных словарей
        elif isinstance(value, dict):
            masked[key] = mask_sensitive_data(value)
        
        # Рекурсивная обработка списков
        elif isinstance(value, list):
            masked[key] = [mask_sensitive_data(item) if isinstance(item, dict) else item for item in value]
        
        # Остальные поля оставляем как есть
        else:
            masked[key] = value
    
    return masked


async def process_successful_payment(session, payment_log_entry, yookassa_payment_data: Optional[Dict[str, Any]] = None):
    """
    Обрабатывает успешный платеж: создает/продлевает подписку
    
    Args:
        session: DB session
        payment_log_entry: PaymentLog объект
        yookassa_payment_data: данные платежа от ЮКассы
    """
    try:
        payment_logger.info(f"Обработка успешного платежа ID: {payment_log_entry.id}, order_id: {payment_log_entry.transaction_id}")
        
        # Получаем пользователя
        user = await get_user_by_id(session, payment_log_entry.user_id)
        if not user:
            payment_logger.error(f"Пользователь ID {payment_log_entry.user_id} не найден")
            return False
        
        # Количество дней и цена
        subscription_days = payment_log_entry.days or SUBSCRIPTION_DAYS
        payment_amount = payment_log_entry.amount

        payment_logger.info(f"Платеж: user_id={user.id}, сумма={payment_amount}, дней={subscription_days}")
        
        # Проверяем активную подписку
        has_sub = await has_active_subscription(session, user.id)
        
        if has_sub:
            # Продлеваем существующую
            payment_logger.info(f"Продление подписки для user_id={user.id}")
            
            # renewal_price будет установлен позже после расчета
            subscription = await extend_subscription(
                session, 
                user_id=user.id, 
                days=subscription_days,
                price=payment_amount,
                payment_id=payment_log_entry.transaction_id,
                renewal_price=None,  # Будет установлен позже
                renewal_duration_days=subscription_days
            )
            
            payment_logger.info(f"Подписка ID {subscription.id} продлена на {subscription_days} дней")
        else:
            # Создаем новую
            payment_logger.info(f"Создание новой подписки для user_id={user.id}")
            
            # renewal_price будет установлен позже после расчета
            subscription = await create_subscription(
                session, 
                user_id=user.id, 
                end_date=datetime.now() + timedelta(days=subscription_days),
                price=payment_amount,
                payment_id=payment_log_entry.transaction_id,
                renewal_price=None,  # Будет установлен позже
                renewal_duration_days=subscription_days
            )
            
            payment_logger.info(f"Создана подписка ID {subscription.id}")
        
        # Проверяем первую оплату по специальной цене (690 руб)
        if not user.is_first_payment_done and payment_amount <= 690:
            user.is_first_payment_done = True
            user.updated_at = datetime.now()
            session.add(user)
            payment_logger.info(f"Установлен флаг is_first_payment_done для пользователя {user.telegram_id} (оплата: {payment_amount} руб)")
        
        # Устанавливаем дату первой оплаты для лояльности (если ещё не установлена)
        # Используем дату создания платежа, а не текущее время
        if not user.first_payment_date:
            # Берем дату из payment_log_entry.created_at (дата создания записи о платеже)
            # или текущую дату, если created_at не доступен
            payment_date = payment_log_entry.created_at if payment_log_entry.created_at else datetime.now()
            user.first_payment_date = payment_date
            user.updated_at = datetime.now()
            session.add(user)
            payment_logger.info(f"Установлена дата первой оплаты для user_id={user.id}: {payment_date}")
        
        # Логируем применение скидки лояльности после успешного платежа (если была применена)
        from loyalty.service import effective_discount
        from database.models import LoyaltyEvent
        
        applied_discount = effective_discount(user)
        
        # Определяем базовую цену тарифа по количеству дней
        def get_base_price_by_days(days: int) -> int:
            from utils.constants import SUBSCRIPTION_PRICE, SUBSCRIPTION_PRICE_2MONTHS, SUBSCRIPTION_PRICE_3MONTHS
            if days == 30:
                return SUBSCRIPTION_PRICE  # 990₽
            elif days == 60:
                return SUBSCRIPTION_PRICE_2MONTHS  # 1790₽
            elif days == 90:
                return SUBSCRIPTION_PRICE_3MONTHS  # 2490₽
            else:
                # По умолчанию 30 дней
                return SUBSCRIPTION_PRICE
        
        # Определяем цену для следующего автопродления
        # ВАЖНО: Всегда используем ПОЛНУЮ цену тарифа, даже если текущий платёж был со скидкой первой оплаты (690₽)
        base_price = get_base_price_by_days(subscription_days)
        
        # Проверяем, была ли это первая оплата со скидкой (690₽)
        from utils.constants import SUBSCRIPTION_PRICE_FIRST
        is_first_payment_discount = payment_amount == SUBSCRIPTION_PRICE_FIRST  # 690₽
        
        # Проверяем, была ли применена разовая скидка промокода
        was_one_time_discount = user.one_time_discount_percent > 0 and applied_discount == user.one_time_discount_percent
        
        # Вычисляем renewal_price
        # При первой оплате со скидкой 690₽ — renewal_price всегда должен быть полной ценой (990₽)
        if is_first_payment_discount or was_one_time_discount:
            # Была разовая скидка - renewal_price = базовая цена с постоянной скидкой (если есть)
            if user.lifetime_discount_percent > 0:
                from loyalty.service import price_with_discount
                calculated_renewal_price = price_with_discount(base_price, user.lifetime_discount_percent)
            else:
                calculated_renewal_price = base_price  # Обычная цена без скидок
        else:
            # Не было разовой скидки - renewal_price = цена с постоянной скидкой (если есть)
            if user.lifetime_discount_percent > 0:
                from loyalty.service import price_with_discount
                calculated_renewal_price = price_with_discount(base_price, user.lifetime_discount_percent)
            else:
                calculated_renewal_price = base_price
        
        # Обновляем renewal_price в подписке
        subscription.renewal_price = calculated_renewal_price
        session.add(subscription)
        
        # Проверяем, была ли применена скидка (разовая или постоянная)
        # Разовую скидку сбрасываем, постоянную оставляем
        if was_one_time_discount:
            # Сбрасываем только разовую скидку (старая логика, если кто-то использовал промокод)
            old_discount = user.one_time_discount_percent
            user.one_time_discount_percent = 0
            user.updated_at = datetime.now()
            session.add(user)
            
            # Записываем событие применения скидки
            event = LoyaltyEvent(
                user_id=user.id,
                kind='bonus_applied',
                level=user.current_loyalty_level,
                payload=json.dumps({
                    "benefit": f"discount_{old_discount}",
                    "payment_id": payment_log_entry.transaction_id,
                    "discount_percent": old_discount,
                    "payment_amount": payment_amount,
                    "type": "one_time"
                }, ensure_ascii=False)
            )
            session.add(event)
            
            payment_logger.info(f"Сброшена разовая скидка {old_discount}% для user_id={user.id} после оплаты")
            
        elif user.lifetime_discount_percent > 0 and applied_discount == user.lifetime_discount_percent:
            # Логируем применение постоянной скидки (но не сбрасываем её)
            # Записываем событие применения скидки
            event = LoyaltyEvent(
                user_id=user.id,
                kind='bonus_applied',
                level=user.current_loyalty_level,
                payload=json.dumps({
                    "benefit": f"discount_{user.lifetime_discount_percent}",
                    "payment_id": payment_log_entry.transaction_id,
                    "discount_percent": user.lifetime_discount_percent,
                    "payment_amount": payment_amount,
                    "type": "lifetime"
                }, ensure_ascii=False)
            )
            session.add(event)
            
            payment_logger.info(f"Логировано применение постоянной скидки {user.lifetime_discount_percent}% для user_id={user.id} (скидка сохранена)")
        
        # Сохраняем информацию о лояльности в подписке (для аудита)
        if subscription:
            from database.models import Subscription
            await session.execute(
                update(Subscription)
                .where(Subscription.id == subscription.id)
                .values(
                    loyalty_applied_level=user.current_loyalty_level,
                    loyalty_discount_percent=applied_discount
                )
            )
        
        # Привязываем платеж к подписке
        await update_payment_subscription(session, payment_log_entry.id, subscription.id)
        
        # Сохраняем payment_method_id для автоплатежей
        if yookassa_payment_data and yookassa_payment_data.get('payment_method'):
            payment_method = yookassa_payment_data['payment_method']
            if payment_method.get('id'):
                await update_user(
                    session,
                    user.telegram_id,
                    yookassa_payment_method_id=payment_method['id'],
                    is_recurring_active=True
                )
                webhook_logger.info(f"Сохранен payment_method_id для пользователя {user.id}")
        
        # ============================================
        # РЕФЕРАЛЬНАЯ СИСТЕМА 2.0
        # При КАЖДОЙ оплате реферала рефереру приходит выбор: деньги или дни
        # ============================================
        if user.referrer_id:
            referrer = await get_user_by_id(session, user.referrer_id)
            if referrer:
                is_first_payment = await is_first_payment_by_user(session, user.id, payment_log_entry.id)
                
                # --- СИСТЕМА 2.0: Отправляем выбор награды при КАЖДОЙ оплате ---
                try:
                    # Проверяем что у реферера есть активная подписка
                    referrer_has_sub = await has_active_subscription(session, referrer.id)
                    
                    if referrer_has_sub:
                        # Рассчитываем денежный бонус
                        loyalty_level = referrer.current_loyalty_level or 'none'
                        bonus_percent = REFERRAL_MONEY_PERCENT.get(loyalty_level, 10)
                        money_amount = int(payment_amount * bonus_percent / 100)
                        
                        # Проверяем право на денежную награду
                        can_get_money = await is_eligible_for_money_reward(session, referrer.id)
                        
                        # Получаем имя реферала
                        referee_name = user.first_name or f"ID: {user.telegram_id}"
                        if user.username:
                            referee_name = f"@{user.username}"
                        
                        # Формируем сообщение с выбором
                        from utils.referral_helpers import get_loyalty_emoji
                        loyalty_emoji = get_loyalty_emoji(loyalty_level)
                        
                        text = (
                            f"🎁 <b>Отличные новости!</b>\n\n"
                            f"Твой друг {referee_name} оплатил подписку! 🔄\n\n"
                            f"💰 <b>Твоя награда:</b> {money_amount:,}₽ ({bonus_percent}% {loyalty_emoji})\n"
                            f"✨ <i>Ты получаешь процент с КАЖДОЙ его оплаты!</i>\n\n"
                            f"Выбери награду:"
                        )
                        
                        if not can_get_money:
                            text += (
                                "\n\n⚠️ <i>Денежные награды недоступны для администраторов "
                                "и пользователей с бесконечной подпиской</i>"
                            )
                        
                        # Кнопки выбора
                        buttons = []
                        if can_get_money:
                            buttons.append([InlineKeyboardButton(
                                text=f"💰 Деньги ({money_amount}₽)",
                                callback_data=f"ref_reward_money:{user.id}:{payment_log_entry.id}"
                            )])
                        buttons.append([InlineKeyboardButton(
                            text=f"📅 +{REFERRAL_BONUS_DAYS} дней к подписке",
                            callback_data=f"ref_reward_days:{user.id}:{payment_log_entry.id}"
                        )])
                        
                        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                        
                        # Отправляем сообщение рефереру
                        await bot.send_message(
                            referrer.telegram_id,
                            text,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                        payment_logger.info(f"[Referral 2.0] Отправлен выбор награды рефереру {referrer.id} за оплату реферала {user.id}")
                    else:
                        payment_logger.info(f"[Referral 2.0] У реферера {referrer.id} нет активной подписки, выбор награды не отправлен")
                        
                except Exception as e_ref:
                    payment_logger.error(f"[Referral 2.0] Ошибка отправки выбора награды: {e_ref}")
                
                # --- Бонус рефералу (приглашённому) при ПЕРВОЙ оплате ---
                if is_first_payment:
                    ref_self_reason = f"referral_bonus_self_from_{referrer.id}"
                    exists_q = await session.execute(
                        select(PaymentLog).where(
                            PaymentLog.user_id == user.id,
                            PaymentLog.payment_method == "bonus",
                            PaymentLog.details.like(f"%{ref_self_reason}%")
                        )
                    )
                    already_self_bonus = exists_q.scalars().first() is not None
                    if not already_self_bonus:
                        success_self = await extend_subscription_days(
                            session,
                            user.id,
                            REFERRAL_BONUS_DAYS,
                            reason=ref_self_reason
                        )
                        if success_self:
                            ref_name = referrer.first_name or "Пользователь"
                            if referrer.username:
                                ref_name = f"{ref_name} (@{referrer.username})"
                            await send_referee_bonus_notification(
                                bot,
                                user.telegram_id,
                                ref_name,
                                REFERRAL_BONUS_DAYS
                            )
                            payment_logger.info(
                                f"[Referral 2.0] Бонус {REFERRAL_BONUS_DAYS} дней начислен рефералу (user_id={user.id})"
                            )
        
        # Уведомление админам
        await send_payment_notification_to_admins(
            bot, 
            user, 
            payment_log_entry,
            subscription, 
            payment_log_entry.transaction_id
        )
        
        # Уведомление пользователю
        await send_payment_success_notification(user, subscription)
        
        # Проверяем бонус за автопродление (streak bonus)
        try:
            metadata = yookassa_payment_data.get('metadata', {}) if yookassa_payment_data else {}
            is_auto_renewal = metadata.get('auto_renewal') == 'true'
            
            if is_auto_renewal and user.is_recurring_active:
                from utils.autopay_bonus import process_autopay_streak_bonus, format_streak_bonus_message
                
                bonus_result = await process_autopay_streak_bonus(session, user, subscription)
                
                if bonus_result['bonus_days'] > 0:
                    # Отправляем уведомление о бонусе
                    bonus_message = format_streak_bonus_message(
                        bonus_result['streak'],
                        bonus_result['bonus_days'],
                        bonus_result['next_bonus_days'],
                        bonus_result['new_end_date']
                    )
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=bonus_message,
                        parse_mode="HTML"
                    )
                    payment_logger.info(
                        f"🎁 Streak bonus отправлен user_id={user.id}: "
                        f"streak={bonus_result['streak']}, +{bonus_result['bonus_days']} дней"
                    )
        except Exception as e:
            payment_logger.error(f"Ошибка при обработке streak bonus: {e}", exc_info=True)
        
        # Проверяем и выдаем badges после успешной оплаты
        try:
            # Обновляем пользователя из БД для актуальных данных
            await session.refresh(user)
            granted_badges = await check_and_grant_badges(session, user)
            if granted_badges:
                payment_logger.info(f"Выданы badges пользователю {user.id}: {granted_badges}")
                # Отправляем уведомления о новых badges
                for badge_type in granted_badges:
                    try:
                        await send_badge_notification(bot, user, badge_type, from_admin=False)
                    except Exception as e:
                        payment_logger.error(f"Ошибка при отправке уведомления о badge {badge_type}: {e}")
        except Exception as e:
            payment_logger.error(f"Ошибка при проверке badges для пользователя {user.id}: {e}")
        
        # Проверяем pending_loyalty_reward — если есть невыбранный бонус, отправляем выбор
        try:
            if user.pending_loyalty_reward and user.current_loyalty_level and user.current_loyalty_level != 'none':
                from loyalty.service import send_choose_benefit_push
                await send_choose_benefit_push(bot, session, user, user.current_loyalty_level)
                payment_logger.info(f"Отправлен выбор бонуса лояльности для пользователя {user.id}")
        except Exception as e:
            payment_logger.error(f"Ошибка при отправке выбора бонуса лояльности: {e}")
        
        # Проверяем badges для реферера (если реферал сделал первую оплату)
        if user.referrer_id:
            try:
                referrer = await get_user_by_id(session, user.referrer_id)
                if referrer:
                    await session.refresh(referrer)
                    granted_referrer_badges = await check_and_grant_badges(session, referrer)
                    if granted_referrer_badges:
                        payment_logger.info(f"Выданы badges рефереру {referrer.id}: {granted_referrer_badges}")
                        # Отправляем уведомления о новых badges рефереру
                        for badge_type in granted_referrer_badges:
                            try:
                                await send_badge_notification(bot, referrer, badge_type, from_admin=False)
                            except Exception as e:
                                payment_logger.error(f"Ошибка при отправке уведомления о badge {badge_type} рефереру: {e}")
            except Exception as e:
                payment_logger.error(f"Ошибка при проверке badges для реферера {user.referrer_id}: {e}")
        
        return True
        
    except Exception as e:
        payment_logger.error(f"Ошибка при обработке успешного платежа: {e}", exc_info=True)
        return False


async def send_payment_success_notification(user, subscription):
    """Отправляет пользователю уведомление об успешной оплате"""
    try:
        # Сначала отправляем видео-кружок от Полины
        try:
            video_path = os.path.join(os.getcwd(), "media", "videoposlepay.mp4")
            if os.path.exists(video_path):
                video_note = FSInputFile(video_path)
                await bot.send_video_note(
                    chat_id=user.telegram_id,
                    video_note=video_note
                )
                payment_logger.info(f"Отправлен видео-кружок пользователю {user.telegram_id}")
            else:
                payment_logger.warning(f"Видео-файл не найден: {video_path}")
        except Exception as e:
            payment_logger.error(f"Ошибка отправки видео-кружка: {e}")
            # Продолжаем отправку текстового сообщения даже если видео не отправилось
        
        # Затем отправляем текстовое сообщение об успешной оплате
        end_date_formatted = subscription.end_date.strftime("%d.%m.%Y")
        
        success_text = (
            f"🎉 *Поздравляем\\!* Ваш платеж успешно прошел\\.\n\n"
            f"Подписка активна до: *{escape_markdown_v2(end_date_formatted)}*\n\n"
            f"Добро пожаловать в клуб\\! Теперь вы можете перейти в закрытый канал и получить доступ ко всем материалам\\."
        )
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎀 Перейти в Mom's Club", url=CLUB_CHANNEL_URL)]
            ]
        )
        
        await bot.send_message(
            chat_id=user.telegram_id,
            text=success_text,
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        
        payment_logger.info(f"Отправлено уведомление об успешной оплате пользователю {user.telegram_id}")
        
        # Второе сообщение: промо InstaBot
        try:
            instabot_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="✨ Перейти в InstaBot", url="https://t.me/instaio_bot")]]
            )
            instabot_text = (
                "✨ Дополнительно для участниц Mom's Club\n\n"
                "Вам доступен наш Instagram AI-бот для продвижения — <b>InstaBot</b>.\n"
                "Он подскажет идеи постов и Reels, поможет с текстами и оформлением.\n\n"
                "Попробуйте прямо сейчас:"
            )
            await bot.send_message(
                chat_id=user.telegram_id,
                text=instabot_text,
                reply_markup=instabot_keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            payment_logger.error(f"Ошибка отправки промо InstaBot: {e}")
        
    except Exception as e:
        payment_logger.error(f"Ошибка отправки уведомления: {e}")


# Создаем обработчик вебхука с условным rate limiting
# Применяем декоратор только если limiter доступен
if limiter:
    @app.post("/webhook")
    @limiter.limit("10/second")  # 10 запросов в секунду для защиты от DDoS
    async def yookassa_webhook_handler(request: Request):
        """Обработчик вебхуков от ЮКассы с rate limiting"""
        return await _process_webhook(request)
else:
    @app.post("/webhook")
    async def yookassa_webhook_handler(request: Request):
        """Обработчик вебхуков от ЮКассы (без rate limiting)"""
        return await _process_webhook(request)


async def _process_webhook(request: Request):
    """Внутренняя функция обработки вебхука"""
    client_ip = request.client.host if request.client else "unknown"
    webhook_logger.info(f"Получен вебхук от IP: {client_ip}")
    
    try:
        # Проверяем IP на подозрительную активность
        # Для не-ЮКасса IP логируем предупреждение
        if not is_yookassa_ip(client_ip):
            webhook_logger.warning(f"⚠️ ВНИМАНИЕ: Вебхук от не-ЮКасса IP: {client_ip}. Проверяем подпись...")
            # Дополнительная проверка для не-ЮКасса IP
            # Если это не ЮКасса, но подпись валидна - возможно тестирование или прокси
        
        # Получаем тело запроса (необработанное, для проверки подписи)
        body = await request.body()
        body_str = body.decode('utf-8')
        
        webhook_logger.info(f"Тело запроса: {body_str[:500]}...")
        
        # ИСПРАВЛЕНО HIGH-001: Требуем только криптографическую HMAC подпись
        # X-Idempotence-Key - это НЕ подпись, это просто ID запроса
        # ЮКасса отправляет подпись в заголовке 'signature' (через nginx проксируется без X-Content префикса)
        # Источник: https://yookassa.ru/developers/using-api/webhooks#signature
        signature_header = (
            request.headers.get("signature") or 
            request.headers.get("Signature") or
            request.headers.get("X-Content-Signature") or 
            request.headers.get("X-Content-HMAC-SHA256")
        )
        
        # Валидация подписи вебхука
        if not verify_yookassa_signature(body_str, signature_header=signature_header, client_ip=client_ip):
            webhook_logger.error(f"🚨 БЕЗОПАСНОСТЬ: Вебхук не прошёл валидацию подписи от IP {client_ip}. Возможная атака!")
            # Логируем подозрительную активность
            webhook_logger.error(f"Подозрительный запрос: IP={client_ip}, Body length={len(body_str)}, Signature header present={signature_header is not None}")
            # Возвращаем 403 Forbidden при неверной подписи
            return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=403)
        
        # Парсим JSON
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError as e:
            webhook_logger.error(f"Ошибка парсинга JSON вебхука: {e}")
            # Возвращаем 400 Bad Request при невалидном JSON
            return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)
        
        # Получаем тип события
        event_type = data.get("event")
        webhook_logger.info(f"Тип события: {event_type}")
        
        # Создаем объект уведомления ЮКассы
        notification = WebhookNotification(data)
        payment = notification.object
        
        webhook_logger.info(f"Платеж ID: {payment.id}, статус: {payment.status}")
        
        # Обрабатываем в зависимости от типа события
        if event_type == WebhookNotificationEventType.PAYMENT_SUCCEEDED:
            await handle_payment_succeeded(payment)
            
        elif event_type == WebhookNotificationEventType.PAYMENT_CANCELED:
            await handle_payment_canceled(payment)
            
        elif event_type == WebhookNotificationEventType.PAYMENT_WAITING_FOR_CAPTURE:
            await handle_payment_waiting(payment)
        
        else:
            webhook_logger.warning(f"Неизвестный тип события: {event_type}")
        
        # Возвращаем 200 OK только при успешной обработке
        return JSONResponse({"status": "success"}, status_code=200)
        
    except HTTPException:
        # Пробрасываем HTTP исключения наверх (они уже имеют правильный статус код)
        raise
    except Exception as e:
        webhook_logger.error(f"КРИТИЧЕСКАЯ ОШИБКА обработки вебхука ЮКассы: {e}", exc_info=True)
        # Возвращаем 500 Internal Server Error при внутренних ошибках
        # Это позволит YooKassa повторить запрос
        return JSONResponse(
            {"status": "error", "message": "Internal server error"},
            status_code=500
        )


async def handle_payment_succeeded(payment):
    """Обрабатывает успешный платеж
    
    ВАЖНО: При ошибках в этой функции исключения пробрасываются наверх,
    чтобы _process_webhook мог вернуть правильный HTTP статус (5xx),
    что позволит YooKassa повторить запрос.
    """
    try:
        payment_id = payment.id
        amount = int(float(payment.amount.value))
        metadata = payment.metadata or {}
        
        # Получаем реальное время платежа от ЮКассы
        payment_datetime = None
        if hasattr(payment, 'captured_at') and payment.captured_at:
            # captured_at - время когда платеж был подтвержден (оплачен)
            payment_datetime = date_parser.parse(payment.captured_at)
        elif hasattr(payment, 'created_at') and payment.created_at:
            # created_at - время создания платежа в ЮКассе
            payment_datetime = date_parser.parse(payment.created_at)
        
        webhook_logger.info(f"Обработка успешного платежа: {payment_id}")
        # Маскируем персональные данные перед логированием
        masked_metadata = mask_sensitive_data(metadata)
        webhook_logger.info(f"Метаданные (замаскированы): {masked_metadata}")
        if payment_datetime:
            webhook_logger.info(f"Время платежа от ЮКассы: {payment_datetime} (UTC)")
        else:
            webhook_logger.warning(f"Не удалось получить время платежа от ЮКассы")
        
        async with AsyncSessionLocal() as session:
            # Ищем платеж в БД
            payment_log = await get_payment_by_transaction_id(session, payment_id)
            
            # ЗАЩИТА ОТ ПОВТОРНОЙ ОБРАБОТКИ: если платеж уже успешно обработан, пропускаем
            # Проверяем не только статус, но и наличие подписки для полной идемпотентности
            if payment_log and payment_log.status == "success" and payment_log.is_confirmed:
                # Дополнительная проверка: есть ли подписка, связанная с этим платежом
                if payment_log.subscription_id:
                    webhook_logger.info(f"Платеж {payment_id} уже обработан (status=success, is_confirmed=True, subscription_id={payment_log.subscription_id}), пропускаем повторную обработку")
                    return  # Идемпотентность - не обрабатываем повторно
                else:
                    # Платеж помечен как success, но подписка не создана - возможно ошибка при обработке
                    webhook_logger.warning(f"Платеж {payment_id} помечен как success, но подписка не найдена. Пытаемся обработать повторно...")
            
            if not payment_log:
                webhook_logger.warning(f"Платеж {payment_id} не найден в БД, создаем новую запись")
                
                # Извлекаем telegram_id из метаданных (не user_id!)
                telegram_id_from_meta = metadata.get("telegram_id")
                if not telegram_id_from_meta:
                    webhook_logger.error("Нет telegram_id в metadata!")
                    return
                
                # Находим пользователя по telegram_id
                user = await get_user_by_telegram_id(session, int(telegram_id_from_meta))
                if not user:
                    webhook_logger.error(f"Пользователь telegram_id={telegram_id_from_meta} не найден!")
                    return
                
                # Получаем количество дней
                days = int(metadata.get("days", 30))
                
                # Создаем запись о платеже с реальным временем от ЮКассы
                payment_log = await create_payment_log(
                    session,
                    user_id=user.id,
                    amount=amount,
                    status="pending",
                    payment_method="yookassa",
                    transaction_id=payment_id,
                    details=f"ЮКасса: {payment.description}",
                    payment_label=metadata.get("payment_label"),
                    days=days,
                    payment_datetime=payment_datetime  # Передаем реальное время платежа
                )
            
            # Обновляем статус на success
            payment_log.status = "success"
            payment_log.is_confirmed = True
            
            # ВАЖНО: Всегда обновляем created_at на реальное время оплаты от ЮКассы (captured_at)
            # Это критично для правильного подсчета выручки по месяцам
            if payment_datetime:
                # Конвертируем UTC в MSK если нужно
                if payment_datetime.tzinfo is not None:
                    if HAS_PYTZ:
                        msk_tz = pytz.timezone('Europe/Moscow')
                        payment_datetime = payment_datetime.astimezone(msk_tz).replace(tzinfo=None)
                    else:
                        payment_datetime = payment_datetime.replace(tzinfo=None)
                # Обновляем created_at на реальное время оплаты (captured_at от ЮКассы)
                # Это важно для правильного подсчета выручки - используем время фактической оплаты
                payment_log.created_at = payment_datetime
                webhook_logger.info(f"Обновлено время платежа на реальное от ЮКассы (captured_at): {payment_datetime}")
            else:
                webhook_logger.warning(f"Не удалось получить время оплаты от ЮКассы для платежа {payment_id}")
            
            # НЕ коммитим здесь - коммитим только после успешной обработки всего платежа
            # Это гарантирует атомарность транзакции
            
            webhook_logger.info(f"Статус платежа подготовлен к обновлению: PaymentLog ID={payment_log.id}")
            
            # Обрабатываем успешный платеж (создаем/продлеваем подписку)
            # Передаем объект payment напрямую, чтобы сохранить payment_method_id
            payment_data_dict = {
                'payment_method': {
                    'id': payment.payment_method.id if payment.payment_method and hasattr(payment.payment_method, 'id') else None,
                    'saved': payment.payment_method.saved if payment.payment_method and hasattr(payment.payment_method, 'saved') else False,
                    'type': payment.payment_method.type if payment.payment_method and hasattr(payment.payment_method, 'type') else None
                } if payment.payment_method else {},
                'metadata': metadata  # Передаём metadata для проверки auto_renewal
            }
            
            success = await process_successful_payment(session, payment_log, payment_data_dict)
            
            if success:
                # Коммитим всю транзакцию атомарно: payment_log + subscription + все изменения
                await session.commit()
                webhook_logger.info(f"✅ Платеж {payment_id} успешно обработан и закоммичен")
            else:
                # Откатываем всю транзакцию, включая изменения payment_log
                await session.rollback()
                webhook_logger.error(f"❌ Ошибка обработки платежа {payment_id}, транзакция откачена")
        
    except Exception as e:
        webhook_logger.error(f"Ошибка в handle_payment_succeeded: {e}", exc_info=True)
        # Пробрасываем исключение наверх, чтобы _process_webhook вернул 5xx
        raise


async def handle_payment_canceled(payment):
    """Обрабатывает отмененный платеж
    
    ВАЖНО: При ошибках исключения пробрасываются наверх для правильной обработки.
    """
    try:
        payment_id = payment.id
        
        webhook_logger.info(f"Платеж отменен: {payment_id}")
        
        async with AsyncSessionLocal() as session:
            payment_log = await get_payment_by_transaction_id(session, payment_id)
            
            if payment_log:
                payment_log.status = "failed"
                payment_log.details = f"Отменен. Причина: {payment.cancellation_details.reason if payment.cancellation_details else 'не указана'}"
                await session.commit()
                
                webhook_logger.info(f"Статус платежа {payment_id} обновлен на 'failed'")
                
                # Уведомление пользователю об отмене УБРАНО
                # Причина: ЮКасса шлёт множество дублирующихся вебхуков payment.canceled,
                # что приводило к спаму одинаковых сообщений пользователю (6+ раз подряд).
                # Если пользователь не оплатил - он и так об этом знает, спамить не нужно.
        
    except Exception as e:
        webhook_logger.error(f"Ошибка в handle_payment_canceled: {e}", exc_info=True)
        # Пробрасываем исключение наверх
        raise


async def handle_payment_waiting(payment):
    """Обрабатывает платеж в ожидании подтверждения
    
    ВАЖНО: При ошибках исключения пробрасываются наверх для правильной обработки.
    """
    try:
        payment_id = payment.id
        webhook_logger.info(f"Платеж ожидает подтверждения: {payment_id}")
        
        async with AsyncSessionLocal() as session:
            payment_log = await get_payment_by_transaction_id(session, payment_id)
            
            if payment_log:
                payment_log.status = "pending"
                await session.commit()
        
    except Exception as e:
        webhook_logger.error(f"Ошибка в handle_payment_waiting: {e}", exc_info=True)
        # Пробрасываем исключение наверх
        raise


# ============== API ДЛЯ УВЕДОМЛЕНИЙ ОТ САЙТА ==============

NOTIFICATION_API_KEY = os.getenv("NOTIFICATION_API_KEY", "")

class NotificationRequest(BaseModel):
    telegram_id: int
    message: str
    api_key: str
    notification_type: str = "general"


@app.post("/api/send_notification")
async def send_notification(request: NotificationRequest):
    """
    Отправляет уведомление пользователю в Telegram.
    Используется сайтом для отправки пушей при действиях админа.
    """
    if not NOTIFICATION_API_KEY or request.api_key != NOTIFICATION_API_KEY:
        webhook_logger.warning(f"Попытка отправки уведомления с неверным API ключом")
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    try:
        await bot.send_message(
            request.telegram_id,
            request.message,
            parse_mode="HTML"
        )
        webhook_logger.info(f"Уведомление отправлено: telegram_id={request.telegram_id}, type={request.notification_type}")
        return {"success": True, "telegram_id": request.telegram_id}
    except Exception as e:
        webhook_logger.error(f"Ошибка отправки уведомления telegram_id={request.telegram_id}: {e}")
        return {"success": False, "error": str(e)}


# ============== HEALTH CHECK ==============

@app.get("/")
@app.get("/health")
async def health_check():
    """Проверяет работоспособность API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "system": "YooKassa"}


if __name__ == "__main__":
    # Запускаем сервер на порту 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
