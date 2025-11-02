"""
Тестовый скрипт для проверки уведомлений после оплаты
Симулирует успешную оплату для пользователя с Telegram ID 44054166
"""
import asyncio
import logging
from datetime import datetime, timedelta
from database.config import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id,
    get_active_subscription,
    create_subscription,
    extend_subscription,
    create_payment_log,
    get_user_by_id
)
from handlers.webhook_handlers import send_payment_success_notification, process_successful_payment
from database.models import PaymentLog
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TEST_TELEGRAM_ID = 44054166
TEST_AMOUNT = 690  # Рубли
TEST_DAYS = 30
TEST_TRANSACTION_ID = f"test_payment_{int(datetime.now().timestamp())}"

async def test_payment_notification():
    """Тестирует отправку всех уведомлений после успешной оплаты"""
    logger.info("="*60)
    logger.info("ТЕСТИРОВАНИЕ УВЕДОМЛЕНИЙ ПОСЛЕ ОПЛАТЫ")
    logger.info("="*60)
    
    async with AsyncSessionLocal() as session:
        # 1. Находим пользователя
        logger.info(f"\n1. Поиск пользователя с Telegram ID: {TEST_TELEGRAM_ID}")
        user = await get_user_by_telegram_id(session, TEST_TELEGRAM_ID)
        
        if not user:
            logger.error(f"❌ Пользователь с Telegram ID {TEST_TELEGRAM_ID} не найден!")
            return
        
        logger.info(f"✅ Найден пользователь:")
        logger.info(f"   ID в БД: {user.id}")
        logger.info(f"   Имя: {user.first_name} {user.last_name or ''}")
        logger.info(f"   Username: @{user.username if user.username else 'нет'}")
        logger.info(f"   Email: {user.email or 'не указан'}")
        logger.info(f"   Телефон: {user.phone or 'не указан'}")
        
        # 2. Проверяем текущую подписку
        logger.info(f"\n2. Проверка текущей подписки...")
        active_sub = await get_active_subscription(session, user.id)
        if active_sub:
            logger.info(f"   ✅ Активная подписка найдена:")
            logger.info(f"      Действует до: {active_sub.end_date.strftime('%d.%m.%Y')}")
            logger.info(f"      Будет продлена")
        else:
            logger.info(f"   ℹ️ Активной подписки нет, будет создана новая")
        
        # 3. Создаем тестовую запись о платеже
        logger.info(f"\n3. Создание тестовой записи о платеже...")
        payment_log = await create_payment_log(
            session,
            user_id=user.id,
            amount=TEST_AMOUNT,
            status="success",
            payment_method="yookassa",
            transaction_id=TEST_TRANSACTION_ID,
            details=f"ТЕСТОВЫЙ ПЛАТЕЖ - {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            days=TEST_DAYS
        )
        logger.info(f"✅ Создана запись о платеже ID: {payment_log.id}")
        logger.info(f"   Сумма: {TEST_AMOUNT} руб")
        logger.info(f"   Дней: {TEST_DAYS}")
        logger.info(f"   Transaction ID: {TEST_TRANSACTION_ID}")
        
        # 4. Обрабатываем успешный платеж (создаем/продлеваем подписку)
        logger.info(f"\n4. Обработка успешного платежа (создание/продление подписки)...")
        
        # Симулируем данные от ЮКассы (без payment_method для простоты)
        yookassa_data = None
        
        success = await process_successful_payment(session, payment_log, yookassa_data)
        
        if success:
            logger.info(f"✅ Платеж успешно обработан!")
            
            # Проверяем обновленную подписку
            updated_sub = await get_active_subscription(session, user.id)
            if updated_sub:
                logger.info(f"   Подписка обновлена:")
                logger.info(f"      Действует до: {updated_sub.end_date.strftime('%d.%m.%Y')}")
        else:
            logger.error(f"❌ Ошибка обработки платежа!")
            return
        
        # 5. Функция send_payment_success_notification вызывается внутри process_successful_payment
        # Но можно вызвать отдельно для проверки:
        logger.info(f"\n5. Уведомления должны быть отправлены автоматически")
        logger.info(f"   Проверьте Telegram пользователя {TEST_TELEGRAM_ID}")
        logger.info(f"   Ожидаемые сообщения:")
        logger.info(f"   1. 🎥 Видео-кружок (videoposlepay.mp4)")
        logger.info(f"   2. 📱 Текст: '🎉 Поздравляем! Ваш платеж успешно прошел...'")
        logger.info(f"   3. 📱 Текст: '✨ Дополнительно для участниц Mom's Club...'")
        logger.info(f"   ")
        logger.info(f"   Админам:")
        logger.info(f"   📱 Уведомление о платеже")
        
        logger.info(f"\n" + "="*60)
        logger.info("✅ ТЕСТ ЗАВЕРШЕН")
        logger.info("="*60)

if __name__ == "__main__":
    asyncio.run(test_payment_notification())

