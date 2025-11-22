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
                renewal_duration_days=subscription_days,
                commit=False  # Не коммитим - работаем в транзакции
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
                renewal_duration_days=subscription_days,
                commit=False  # Не коммитим - работаем в транзакции
            )
            
            payment_logger.info(f"Создана подписка ID {subscription.id}")
        
        # Проверяем первую оплату по специальной цене (690 руб)
        if not user.is_first_payment_done and payment_amount <= 690:
            user.is_first_payment_done = True
            user.updated_at = datetime.now()
            session.add(user)
            payment_logger.info(f"Установлен флаг is_first_payment_done для пользователя {user.telegram_id} (оплата: {payment_amount} руб)")
        
        # Устанавливаем дату первой оплаты для лояльности (если ещё не установлена)
        # P1.2: Устанавливаем на ПЕРВОМ успешном платеже, независимо от суммы
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
        await update_payment_subscription(session, payment_log_entry.id, subscription.id, commit=False)
        
        # Сохраняем payment_method_id для автоплатежей
        if yookassa_payment_data and yookassa_payment_data.get('payment_method'):
            payment_method = yookassa_payment_data['payment_method']
            if payment_method.get('id'):
                await update_user(
                    session,
                    user.telegram_id,
                    commit=False,  # Не коммитим - работаем в транзакции
                    yookassa_payment_method_id=payment_method['id'],
                    is_recurring_active=True
                )
                webhook_logger.info(f"Сохранен payment_method_id для пользователя {user.id}")
        
        # Обработка реферального бонуса (Реферальная система 2.0)
        # ИЗМЕНЕНО: Теперь реферер получает процент от КАЖДОЙ оплаты реферала!
        if user.referrer_id:
            referrer = await get_user_by_id(session, user.referrer_id)
            if referrer:
                payment_logger.info(f"Платеж пользователя {user.id} (реферал). Отправляем выбор награды рефереру {referrer.id}")
                
                # Отправляем уведомление с выбором награды (деньги или дни)
                # Реферер получает процент от КАЖДОЙ оплаты своего реферала!
                await send_referral_reward_choice(
                    bot,
                    referrer,
                    user,
                    payment_log_entry.amount
                )
                
                payment_logger.info(f"Уведомление о выборе награды отправлено рефереру {referrer.id}")
        
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
        
        # Получаем IP адрес клиента (может быть через прокси)
        client_ip = None
        if request.client:
            client_ip = request.client.host
        # Проверяем заголовки для реального IP (если за прокси)
        if not client_ip:
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                client_ip = forwarded_for.split(",")[0].strip()
        if not client_ip:
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                client_ip = real_ip
        
        # Логируем только метаданные, не полное тело (безопасность)
        try:
            import json
            data_preview = json.loads(body_str)
            webhook_logger.info(f"Вебхук от IP {client_ip}, тип: {data_preview.get('type', 'unknown')}, событие: {data_preview.get('event', 'unknown')}")
        except:
            webhook_logger.info(f"Вебхук от IP {client_ip}, размер: {len(body_str)} байт")
        
        # Валидация подписи вебхука (IP + структура)
        from utils.payment import verify_yookassa_signature
        
        if not verify_yookassa_signature(body_str, client_ip):
            webhook_logger.warning(f"Вебхук не прошёл валидацию от IP {client_ip}")
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
        metadata = payment.metadata or {}
        
        # P2.1: ВАЛИДАЦИЯ ВХОДНЫХ ДАННЫХ
        # Проверяем валюту
        currency = payment.amount.currency if hasattr(payment.amount, 'currency') else None
        if currency != 'RUB':
            webhook_logger.error(f"Неверная валюта платежа {payment_id}: {currency} (ожидается RUB)")
            return  # Отклоняем платеж с неверной валютой
        
        # P1.1: Используем Decimal для денежных сумм
        from decimal import Decimal, ROUND_HALF_UP
        amount_decimal = Decimal(str(payment.amount.value))
        amount = int(amount_decimal.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        
        # Проверяем сумму
        if amount <= 0:
            webhook_logger.error(f"Неверная сумма платежа {payment_id}: {amount} (должна быть > 0)")
            return  # Отклоняем платеж с неверной суммой
        
        # Проверяем наличие user_id в метаданных
        user_id_from_meta = metadata.get("user_id")
        if not user_id_from_meta:
            webhook_logger.error(f"Нет user_id в metadata для платежа {payment_id}")
            return
        
        # P1.1: Сверяем сумму с ожидаемой (если указана в metadata)
        expected_amount = metadata.get("expected_amount")
        if expected_amount:
            expected_decimal = Decimal(str(expected_amount))
            # Допускаем расхождение до 1 копейки из-за округления
            diff = abs(amount_decimal - expected_decimal)
            if diff > Decimal('0.01'):
                webhook_logger.error(
                    f"Расхождение суммы для платежа {payment_id}: "
                    f"ожидалось {expected_amount}, получено {amount}, разница {diff}"
                )
                return  # Отклоняем платеж при значительном расхождении
        
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
        # P2.2: Маскируем чувствительные данные в логах
        from utils.helpers import mask_sensitive_data
        masked_metadata = {}
        for key, value in metadata.items():
            if key in ['payment_method_id', 'id', 'token']:  # Маскируем чувствительные поля
                masked_metadata[key] = mask_sensitive_data(str(value)) if value else None
            else:
                masked_metadata[key] = value
        webhook_logger.info(f"Метаданные: {masked_metadata}")
        if payment_datetime:
            webhook_logger.info(f"Время платежа от ЮКассы: {payment_datetime} (UTC)")
        else:
            webhook_logger.warning(f"Не удалось получить время платежа от ЮКассы")
        
        async with AsyncSessionLocal() as session:
            # Сначала проверяем, существует ли платеж
            payment_log = await get_payment_by_transaction_id(session, payment_id)
            
            # P0.2: ПРОВЕРКА ИДЕМПОТЕНТНОСТИ - если платеж уже обработан, выходим
            if payment_log and payment_log.status == "success" and payment_log.is_confirmed:
                webhook_logger.info(f"Платеж {payment_id} уже обработан (идемпотентность), пропускаем")
                return  # Идемпотентность - не обрабатываем повторно
            
            # Если платеж не найден, создаем его (редкий случай)
            # user_id_from_meta уже проверен в валидации выше
            if not payment_log:
                webhook_logger.warning(f"Платеж {payment_id} не найден в БД, создаем новую запись")
                
                # Находим пользователя (user_id_from_meta уже проверен)
                user = await get_user_by_telegram_id(session, int(user_id_from_meta))
                if not user:
                    webhook_logger.error(f"Пользователь telegram_id={user_id_from_meta} не найден!")
                    return
                
                # Получаем количество дней
                days = int(metadata.get("days", 30))
                
                # Создаем запись о платеже со статусом pending (будет обновлен в транзакции)
                payment_log = await create_payment_log(
                    session,
                    user_id=user.id,
                    amount=amount,
                    status="pending",  # Сначала pending, обновим в транзакции
                    payment_method="yookassa",
                    transaction_id=payment_id,
                    details=f"ЮКасса: {payment.description}",
                    payment_label=metadata.get("payment_label"),
                    days=days,
                    payment_datetime=payment_datetime,
                    commit=True  # Коммитим создание записи
                )
            
            # P0.3: ОБОРАЧИВАЕМ ВСЕ В ОДНУ ТРАНЗАКЦИЮ
            # P0.2: ИДЕМПОТЕНТНЫЙ UPDATE внутри транзакции для защиты от race condition
            async with session.begin():
                try:
                    from database.models import PaymentLog
                    
                    # ИДЕМПОТЕНТНЫЙ UPDATE - атомарно обновляем статус только если он не success
                    # Это защищает от race condition при одновременной обработке нескольких вебхуков
                    update_result = await session.execute(
                        update(PaymentLog)
                        .where(
                            PaymentLog.transaction_id == payment_id,
                            PaymentLog.status != "success"  # Обновляем только если статус НЕ success
                        )
                        .values(
                            status="success",
                            is_confirmed=True
                        )
                    )
                    
                    # Если rowcount == 0, значит другой процесс уже обработал платеж (race condition)
                    if update_result.rowcount == 0:
                        webhook_logger.info(f"Платеж {payment_id} уже обработан другим процессом (race condition), пропускаем")
                        return  # Идемпотентность - транзакция откатится автоматически
                    
                    # Успешно обновили статус - обновляем объект
                    await session.refresh(payment_log)
                    webhook_logger.info(f"Статус платежа обновлен идемпотентным UPDATE: PaymentLog ID={payment_log.id}")
                    
                    # Если есть реальное время от ЮКассы, обновляем его
                    if payment_datetime:
                        # Конвертируем UTC в MSK если нужно
                        if payment_datetime.tzinfo is not None:
                            try:
                                import pytz
                                msk_tz = pytz.timezone('Europe/Moscow')
                                payment_datetime = payment_datetime.astimezone(msk_tz).replace(tzinfo=None)
                            except ImportError:
                                payment_datetime = payment_datetime.replace(tzinfo=None)
                        
                        # Обновляем время только если оно отличается
                        if payment_log.created_at != payment_datetime:
                            payment_log.created_at = payment_datetime
                            webhook_logger.info(f"Обновлено время платежа на реальное от ЮКассы: {payment_datetime}")
                    
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
                    
                    if not success:
                        raise Exception("Ошибка обработки платежа в process_successful_payment")
                    
                    # Коммит произойдет автоматически при выходе из контекста session.begin()
                    webhook_logger.info(f"✅ Платеж {payment_id} успешно обработан")
                        
                except Exception as e:
                    # Откат транзакции при ошибке произойдет автоматически
                    webhook_logger.error(f"❌ Ошибка обработки платежа {payment_id}: {e}", exc_info=True)
                    raise  # Пробрасываем исключение дальше
        
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


async def send_referral_reward_choice(bot, referrer, referee, payment_amount):
    """
    Отправляет уведомление рефереру с выбором награды (деньги или дни)
    
    Args:
        bot: Экземпляр бота
        referrer: Объект пользователя-реферера
        referee: Объект пользователя-реферала
        payment_amount: Сумма платежа реферала
    """
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from utils.referral_helpers import (
            calculate_referral_bonus,
            get_loyalty_emoji,
            get_bonus_percent_for_level
        )
        from utils.referral_messages import get_reward_choice_text
        from database.crud import is_eligible_for_money_reward
        from database.config import AsyncSessionLocal
        
        # Формируем имя реферала
        referee_name = referee.first_name or ""
        if referee.last_name:
            referee_name += f" {referee.last_name}"
        if referee.username:
            referee_name = f"@{referee.username}"
        if not referee_name.strip():
            referee_name = f"ID: {referee.telegram_id}"
        
        # Рассчитываем бонус
        loyalty_level = referrer.current_loyalty_level or 'none'
        bonus_percent = get_bonus_percent_for_level(loyalty_level)
        money_amount = calculate_referral_bonus(payment_amount, loyalty_level)
        loyalty_emoji = get_loyalty_emoji(loyalty_level)
        
        # Проверяем право на денежные награды
        async with AsyncSessionLocal() as session:
            can_get_money = await is_eligible_for_money_reward(session, referrer.id)
        
        # Формируем текст
        text = get_reward_choice_text(
            referee_name,
            money_amount,
            bonus_percent,
            loyalty_emoji,
            can_get_money
        )
        
        # Формируем клавиатуру
        from utils.constants import REFERRAL_BONUS_DAYS
        keyboard_buttons = []
        
        # Кнопка денег (если доступна)
        if can_get_money:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"💰 Получить {money_amount:,}₽ на баланс",
                    callback_data=f"ref_reward_money:{referee.id}"
                )
            ])
        
        # Кнопка дней (всегда доступна)
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"📅 Получить {REFERRAL_BONUS_DAYS} дней подписки",
                callback_data=f"ref_reward_days:{referee.id}"
            )
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await bot.send_message(
            referrer.telegram_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        webhook_logger.info(f"Отправлено уведомление о выборе награды рефереру {referrer.id}")
        
    except Exception as e:
        webhook_logger.error(f"Ошибка при отправке уведомления о выборе награды: {e}", exc_info=True)


@app.get("/")
@app.get("/health")
async def health_check():
    """Проверяет работоспособность API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "system": "YooKassa"}


if __name__ == "__main__":
    # Запускаем сервер на порту 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
