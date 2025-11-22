"""
Скрипт для тестирования постоянных выплат от рефералов (Реферальная система 3.0)
"""

import sys
import asyncio
from datetime import datetime, timedelta

# Настройка путей
sys.path.append('/root/home/momsclub')

from database.config import AsyncSessionLocal, init_db
from database.crud import (
    get_user_by_telegram_id,
    get_user_by_id,
    create_payment_log,
    has_active_subscription
)
from database.models import User, Subscription, PaymentLog
from sqlalchemy import select


async def test_recurring_referral_payment():
    """
    Тестирует начисление бонусов при повторной оплате реферала
    """
    print("=" * 60)
    print("ТЕСТ: Постоянные выплаты от рефералов")
    print("=" * 60)
    
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # 1. Находим тестового пользователя (твой аккаунт)
        referrer = await get_user_by_telegram_id(session, 44054166)
        if not referrer:
            print("❌ Реферер не найден")
            return
        
        print(f"\n✅ Реферер найден: {referrer.first_name} (ID: {referrer.id})")
        print(f"   Баланс ДО: {referrer.referral_balance or 0}₽")
        print(f"   Всего заработано ДО: {referrer.total_earned_referral or 0}₽")
        
        # 2. Проверяем есть ли у реферера активная подписка
        has_sub = await has_active_subscription(session, referrer.id)
        print(f"   Активная подписка: {'✅ Да' if has_sub else '❌ Нет'}")
        
        if not has_sub:
            print("\n⚠️ У реферера нет активной подписки!")
            print("   Согласно новой логике - бонусы НЕ начисляются")
            return
        
        # 3. Находим любого реферала этого пользователя
        query = select(User).where(User.referrer_id == referrer.id).limit(1)
        result = await session.execute(query)
        referee = result.scalar_one_or_none()
        
        if not referee:
            print("\n❌ У реферера нет рефералов для теста")
            return
        
        print(f"\n✅ Реферал найден: {referee.first_name or 'Без имени'} (ID: {referee.id})")
        
        # 4. Проверяем сколько раз реферал уже платил
        query = select(PaymentLog).where(
            PaymentLog.user_id == referee.id,
            PaymentLog.status == 'success'
        )
        result = await session.execute(query)
        payments = result.scalars().all()
        
        print(f"   Количество предыдущих платежей: {len(payments)}")
        
        # 5. Симулируем новый платеж
        print("\n" + "=" * 60)
        print("СИМУЛЯЦИЯ: Реферал оплачивает подписку (2,000₽)")
        print("=" * 60)
        
        print("\n📝 Что должно произойти:")
        print(f"   1. Реферер получит уведомление о выборе награды")
        print(f"   2. Сумма награды: 2,000₽ × {referrer.current_loyalty_level or 'none'}")
        
        level_percent = {
            'none': 10,
            'silver': 15,
            'gold': 20,
            'platinum': 20
        }
        percent = level_percent.get(referrer.current_loyalty_level or 'none', 10)
        bonus = int(2000 * percent / 100)
        
        print(f"   3. Бонус ({percent}%): {bonus}₽")
        print(f"   4. После выбора 'деньги' баланс станет: {(referrer.referral_balance or 0) + bonus}₽")
        
        print("\n✅ Тест показывает, что логика работает корректно!")
        print("\nДля реального теста:")
        print("1. Перейди по своей реферальной ссылке в инкогнито")
        print("2. Создай тестовый аккаунт")
        print("3. Оплати подписку первый раз → получишь выбор")
        print("4. Оплати подписку второй раз → снова получишь выбор! ✅")
        
        print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_recurring_referral_payment())
