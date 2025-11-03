"""
Миграция: перенос разовых скидок лояльности в постоянные
Для пользователей, которые уже выбрали discount_5 или discount_10 до изменения логики
"""
import asyncio
import sys
import os
import json
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.config import AsyncSessionLocal
from database.models import User, LoyaltyEvent

logging_enabled = True

def log(message: str):
    """Логирование с временной меткой"""
    if logging_enabled:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message}")


async def migrate_discounts():
    """
    Переносит разовые скидки лояльности (5% и 10%) в постоянные для пользователей,
    которые уже выбирали эти бонусы через систему лояльности.
    """
    log("=" * 80)
    log("🚀 ЗАПУСК МИГРАЦИИ: Перенос разовых скидок лояльности в постоянные")
    log("=" * 80)
    log("")
    
    async with AsyncSessionLocal() as session:
        stats = {
            'total_users_checked': 0,
            'users_with_one_time_5': 0,
            'users_with_one_time_10': 0,
            'migrated_5': 0,
            'migrated_10': 0,
            'skipped_no_benefit_event': 0,
            'skipped_already_has_lifetime': 0,
            'errors': 0
        }
        
        # Находим всех пользователей с разовой скидкой 5% или 10%
        log("1️⃣ Поиск пользователей с разовыми скидками 5% или 10%...")
        query = select(User).where(
            (User.one_time_discount_percent == 5) | (User.one_time_discount_percent == 10)
        )
        
        result = await session.execute(query)
        users = result.scalars().all()
        
        stats['total_users_checked'] = len(users)
        log(f"   Найдено пользователей с разовыми скидками: {len(users)}")
        log("")
        
        if not users:
            log("   ✅ Нет пользователей для миграции")
            log("=" * 80)
            return
        
        # Обрабатываем каждого пользователя
        log("2️⃣ Проверка и перенос скидок...")
        log("-" * 80)
        
        for idx, user in enumerate(users, 1):
            try:
                discount = user.one_time_discount_percent
                
                if discount == 5:
                    stats['users_with_one_time_5'] += 1
                    benefit_code = 'discount_5'
                elif discount == 10:
                    stats['users_with_one_time_10'] += 1
                    benefit_code = 'discount_10'
                else:
                    continue
                
                log(f"[{idx}/{len(users)}] user_id={user.id} (telegram_id={user.telegram_id})")
                log(f"   Текущая разовая скидка: {discount}%")
                log(f"   Текущая постоянная скидка: {user.lifetime_discount_percent}%")
                
                # Проверяем, выбирал ли пользователь этот бонус через систему лояльности
                benefit_query = select(LoyaltyEvent).where(
                    LoyaltyEvent.user_id == user.id,
                    LoyaltyEvent.kind == 'benefit_chosen',
                    LoyaltyEvent.payload.like(f'%"{benefit_code}"%')
                ).order_by(LoyaltyEvent.created_at.desc())
                
                benefit_result = await session.execute(benefit_query)
                benefit_event = benefit_result.scalar_one_or_none()
                
                if not benefit_event:
                    log(f"   ⏭️  Пропуск: нет записи о выборе бонуса {benefit_code} (возможно, промокод)")
                    stats['skipped_no_benefit_event'] += 1
                    continue
                
                # Если уже есть постоянная скидка больше или равна, пропускаем
                if user.lifetime_discount_percent >= discount:
                    log(f"   ⏭️  Пропуск: уже есть постоянная скидка {user.lifetime_discount_percent}% >= {discount}%")
                    stats['skipped_already_has_lifetime'] += 1
                    continue
                
                # Если есть постоянная скидка меньше, увеличиваем её
                if user.lifetime_discount_percent > 0 and user.lifetime_discount_percent < discount:
                    log(f"   ⚠️  Обновление: постоянная скидка {user.lifetime_discount_percent}% → {discount}%")
                    new_lifetime_discount = discount
                else:
                    log(f"   ✅ Перенос: {discount}% → постоянная скидка")
                    new_lifetime_discount = discount
                
                # Обновляем пользователя
                await session.execute(
                    update(User)
                    .where(User.id == user.id)
                    .values(
                        lifetime_discount_percent=new_lifetime_discount,
                        one_time_discount_percent=0,
                        updated_at=datetime.now()
                    )
                )
                
                # Обновляем payload в событии, чтобы отразить изменение типа
                try:
                    payload_data = json.loads(benefit_event.payload)
                    payload_data["type"] = "lifetime"
                    payload_data["migrated_at"] = datetime.now().isoformat()
                    
                    await session.execute(
                        update(LoyaltyEvent)
                        .where(LoyaltyEvent.id == benefit_event.id)
                        .values(payload=json.dumps(payload_data, ensure_ascii=False))
                    )
                except Exception as e:
                    log(f"   ⚠️  Не удалось обновить payload события: {e}")
                
                if discount == 5:
                    stats['migrated_5'] += 1
                else:
                    stats['migrated_10'] += 1
                
                log(f"   ✅ Мигрировано успешно")
                log("")
                
            except Exception as e:
                stats['errors'] += 1
                log(f"   ❌ Ошибка при обработке user_id={user.id}: {e}")
                log("")
                await session.rollback()
                continue
        
        # Коммитим все изменения
        await session.commit()
        
        # Финальная статистика
        log("=" * 80)
        log("📊 ИТОГОВАЯ СТАТИСТИКА МИГРАЦИИ")
        log("=" * 80)
        log(f"👥 Всего пользователей проверено: {stats['total_users_checked']}")
        log(f"📊 С разовой скидкой 5%: {stats['users_with_one_time_5']}")
        log(f"📊 С разовой скидкой 10%: {stats['users_with_one_time_10']}")
        log("")
        log(f"✅ Мигрировано 5%: {stats['migrated_5']}")
        log(f"✅ Мигрировано 10%: {stats['migrated_10']}")
        log(f"⏭️  Пропущено (нет события бонуса): {stats['skipped_no_benefit_event']}")
        log(f"⏭️  Пропущено (уже есть постоянная): {stats['skipped_already_has_lifetime']}")
        log(f"❌ Ошибок: {stats['errors']}")
        log("=" * 80)
        log("✅ МИГРАЦИЯ ЗАВЕРШЕНА")
        log("=" * 80)


if __name__ == "__main__":
    asyncio.run(migrate_discounts())

