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
from sqlalchemy import update
from typing import Optional, Dict, Any

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
    is_first_payment_by_user,
    update_user,
    get_active_subscription,
    get_payment_by_id,
    create_payment_log
)
from database.models import PaymentLog, User, Subscription
from utils.constants import REFERRAL_BONUS_DAYS, CLUB_CHANNEL_URL, SUBSCRIPTION_DAYS
from utils.helpers import escape_markdown_v2
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

# Добавляем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ЮКасса отправляет с разных IP
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)


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
            
            subscription = await extend_subscription(
                session, 
                user_id=user.id, 
                days=subscription_days,
                price=payment_amount,
                payment_id=payment_log_entry.transaction_id,
                renewal_price=payment_amount,
                renewal_duration_days=subscription_days
            )
            
            payment_logger.info(f"Подписка ID {subscription.id} продлена на {subscription_days} дней")
        else:
            # Создаем новую
            payment_logger.info(f"Создание новой подписки для user_id={user.id}")
            
            subscription = await create_subscription(
                session, 
                user_id=user.id, 
                end_date=datetime.now() + timedelta(days=subscription_days),
                price=payment_amount,
                payment_id=payment_log_entry.transaction_id,
                renewal_price=payment_amount,
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
        import json
        
        applied_discount = effective_discount(user)
        
        # Проверяем, была ли применена скидка (разовая или постоянная)
        # Разовую скидку сбрасываем, постоянную оставляем
        if user.one_time_discount_percent > 0 and applied_discount == user.one_time_discount_percent:
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
            from sqlalchemy import update
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
        
        # Обработка реферального бонуса
        if user.referrer_id:
            referrer = await get_user_by_id(session, user.referrer_id)
            if referrer:
                is_first_payment = await is_first_payment_by_user(session, user.id, payment_log_entry.id)
                
                if is_first_payment:
                    payment_logger.info(f"Начисляем бонус {REFERRAL_BONUS_DAYS} дней рефереру {referrer.id}")
                    
                    success_bonus = await extend_subscription_days(
                        session,
                        referrer.id,
                        REFERRAL_BONUS_DAYS,
                        reason=f"referral_bonus_for_{user.id}"
                    )
                    
                    if success_bonus:
                        await send_referral_bonus_notification(
                            bot,
                            referrer.telegram_id,
                            user.first_name or f"ID: {user.telegram_id}",
                            REFERRAL_BONUS_DAYS
                        )
                        payment_logger.info(f"Реферальный бонус начислен рефереру {referrer.id}")
        
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


@app.post("/webhook")
async def yookassa_webhook_handler(request: Request):
    """Обработчик вебхуков от ЮКассы"""
    webhook_logger.info("Получен вебхук от ЮКассы")
    
    try:
        # Получаем тело запроса
        body = await request.body()
        body_str = body.decode('utf-8')
        
        webhook_logger.info(f"Тело запроса: {body_str[:500]}...")
        
        # Валидация подписи вебхука
        from utils.payment import verify_yookassa_signature
        client_ip = request.client.host if request.client else None
        
        if not verify_yookassa_signature(body_str, client_ip):
            webhook_logger.warning(f"Вебхук не прошёл валидацию подписи от IP {client_ip}")
            return JSONResponse({"status": "error", "message": "Invalid signature"}, status_code=403)
        
        # Парсим JSON
        data = json.loads(body_str)
        
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
        
        return JSONResponse({"status": "success"})
        
    except Exception as e:
        webhook_logger.error(f"Ошибка обработки вебхука ЮКассы: {e}", exc_info=True)
        return JSONResponse({"status": "error", "message": str(e)})


async def handle_payment_succeeded(payment):
    """Обрабатывает успешный платеж"""
    try:
        payment_id = payment.id
        amount = int(float(payment.amount.value))
        metadata = payment.metadata or {}
        
        # Получаем реальное время платежа от ЮКассы
        payment_datetime = None
        if hasattr(payment, 'captured_at') and payment.captured_at:
            # captured_at - время когда платеж был подтвержден (оплачен)
            from dateutil import parser
            payment_datetime = parser.parse(payment.captured_at)
        elif hasattr(payment, 'created_at') and payment.created_at:
            # created_at - время создания платежа в ЮКассе
            from dateutil import parser
            payment_datetime = parser.parse(payment.created_at)
        
        webhook_logger.info(f"Обработка успешного платежа: {payment_id}")
        webhook_logger.info(f"Метаданные: {metadata}")
        if payment_datetime:
            webhook_logger.info(f"Время платежа от ЮКассы: {payment_datetime} (UTC)")
        else:
            webhook_logger.warning(f"Не удалось получить время платежа от ЮКассы")
        
        async with AsyncSessionLocal() as session:
            # Ищем платеж в БД
            payment_log = await get_payment_by_transaction_id(session, payment_id)
            
            # ЗАЩИТА ОТ ПОВТОРНОЙ ОБРАБОТКИ: если платеж уже успешно обработан, пропускаем
            if payment_log and payment_log.status == "success" and payment_log.is_confirmed:
                webhook_logger.info(f"Платеж {payment_id} уже обработан (status=success, is_confirmed=True), пропускаем повторную обработку")
                return  # Идемпотентность - не обрабатываем повторно
            
            if not payment_log:
                webhook_logger.warning(f"Платеж {payment_id} не найден в БД, создаем новую запись")
                
                # Извлекаем user_id из метаданных
                user_id_from_meta = metadata.get("user_id")
                if not user_id_from_meta:
                    webhook_logger.error("Нет user_id в metadata!")
                    return
                
                # Находим пользователя
                user = await get_user_by_telegram_id(session, int(user_id_from_meta))
                if not user:
                    webhook_logger.error(f"Пользователь telegram_id={user_id_from_meta} не найден!")
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
            
            # Если платеж уже существовал и есть реальное время от ЮКассы,
            # обновляем его на реальное время (если время от ЮКассы более точное)
            if payment_datetime:
                # Конвертируем UTC в MSK если нужно
                if payment_datetime.tzinfo is not None:
                    try:
                        import pytz
                        msk_tz = pytz.timezone('Europe/Moscow')
                        payment_datetime = payment_datetime.astimezone(msk_tz).replace(tzinfo=None)
                    except ImportError:
                        payment_datetime = payment_datetime.replace(tzinfo=None)
                payment_log.created_at = payment_datetime
                webhook_logger.info(f"Обновлено время платежа на реальное от ЮКассы: {payment_datetime}")
            
            await session.commit()
            
            webhook_logger.info(f"Статус платежа обновлен: PaymentLog ID={payment_log.id}")
            
            # Обрабатываем успешный платеж (создаем/продлеваем подписку)
            # Передаем объект payment напрямую, чтобы сохранить payment_method_id
            payment_data_dict = {
                'payment_method': {
                    'id': payment.payment_method.id if payment.payment_method and hasattr(payment.payment_method, 'id') else None,
                    'saved': payment.payment_method.saved if payment.payment_method and hasattr(payment.payment_method, 'saved') else False,
                    'type': payment.payment_method.type if payment.payment_method and hasattr(payment.payment_method, 'type') else None
                } if payment.payment_method else {}
            }
            
            success = await process_successful_payment(session, payment_log, payment_data_dict)
            
            if success:
                await session.commit()
                webhook_logger.info(f"✅ Платеж {payment_id} успешно обработан")
            else:
                await session.rollback()
                webhook_logger.error(f"❌ Ошибка обработки платежа {payment_id}")
        
    except Exception as e:
        webhook_logger.error(f"Ошибка в handle_payment_succeeded: {e}", exc_info=True)


async def handle_payment_canceled(payment):
    """Обрабатывает отмененный платеж"""
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
                
                # Уведомление пользователю об отмене
                user = await get_user_by_id(session, payment_log.user_id)
                if user:
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            "❌ К сожалению, платеж был отменен.\n\n"
                            "Пожалуйста, попробуйте еще раз или свяжитесь с поддержкой."
                        )
                    except Exception as e:
                        webhook_logger.error(f"Ошибка отправки уведомления об отмене: {e}")
        
    except Exception as e:
        webhook_logger.error(f"Ошибка в handle_payment_canceled: {e}", exc_info=True)


async def handle_payment_waiting(payment):
    """Обрабатывает платеж в ожидании подтверждения"""
    try:
        payment_id = payment.id
        webhook_logger.info(f"Платеж ожидает подтверждения: {payment_id}")
        
        async with AsyncSessionLocal() as session:
            payment_log = await get_payment_by_transaction_id(session, payment_id)
            
            if payment_log:
                payment_log.status = "pending"
                await session.commit()
        
    except Exception as e:
        webhook_logger.error(f"Ошибка в handle_payment_waiting: {e}")


@app.get("/")
@app.get("/health")
async def health_check():
    """Проверяет работоспособность API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "system": "YooKassa"}


if __name__ == "__main__":
    # Запускаем сервер на порту 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
