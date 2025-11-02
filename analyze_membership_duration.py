"""
Анализ времени пребывания пользователей в клубе
Группировка по периодам: 3, 6, 12+ месяцев
"""
import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from database.config import AsyncSessionLocal
from database.models import User, Subscription

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def analyze_membership_duration():
    """Анализирует время пребывания пользователей в клубе"""
    now = datetime.now()
    
    # Дата для исключения безлимитных подписок (больше 2099 года)
    unlimited_threshold = datetime(2099, 1, 1)
    
    async with AsyncSessionLocal() as session:
        # Получаем всех пользователей с активными подписками
        # (is_active=True и end_date > now, но не безлимитные)
        query = (
            select(User, Subscription)
            .join(Subscription, User.id == Subscription.user_id)
            .where(
                and_(
                    Subscription.is_active == True,
                    Subscription.end_date > now,
                    Subscription.end_date <= unlimited_threshold  # Исключаем безлимитные
                )
            )
            .options(selectinload(User.subscriptions))
        )
        
        result = await session.execute(query)
        user_sub_pairs = result.all()
        
        logger.info(f"Найдено {len(user_sub_pairs)} пользователей с активными подписками")
        
        # Группируем по пользователям (может быть несколько активных подписок)
        users_data = {}
        
        for user, subscription in user_sub_pairs:
            if user.id not in users_data:
                # Получаем все подписки пользователя для расчета общего времени
                all_subs_query = (
                    select(Subscription)
                    .where(
                        and_(
                            Subscription.user_id == user.id,
                            Subscription.end_date <= unlimited_threshold  # Исключаем безлимитные
                        )
                    )
                    .order_by(Subscription.start_date.asc())
                )
                all_subs_result = await session.execute(all_subs_query)
                all_subs = all_subs_result.scalars().all()
                
                # Находим первую подписку
                first_sub = min(all_subs, key=lambda s: s.start_date) if all_subs else subscription
                first_sub_date = first_sub.start_date
                
                # Вычисляем общее время в клубе (с первой подписки до текущего момента)
                membership_duration = now - first_sub_date
                membership_months = membership_duration.days / 30.44  # Среднее количество дней в месяце
                
                users_data[user.id] = {
                    'user': user,
                    'first_subscription_date': first_sub_date,
                    'membership_months': membership_months,
                    'membership_days': membership_duration.days,
                    'active_subscription': subscription,
                    'total_subscriptions': len(all_subs)
                }
        
        # Группируем по периодам
        groups = {
            '3_months': [],      # 0-3 месяца
            '6_months': [],      # 3-6 месяцев
            '12_months': [],     # 6-12 месяцев
            '12_plus_months': [] # 12+ месяцев
        }
        
        for user_id, data in users_data.items():
            months = data['membership_months']
            
            if months < 3:
                groups['3_months'].append(data)
            elif months < 6:
                groups['6_months'].append(data)
            elif months < 12:
                groups['12_months'].append(data)
            else:
                groups['12_plus_months'].append(data)
        
        # Выводим статистику
        print("\n" + "="*80)
        print("СТАТИСТИКА ПО ВРЕМЕНИ ПРЕБЫВАНИЯ В КЛУБЕ")
        print("="*80)
        print(f"Общее количество активных пользователей: {len(users_data)}")
        print(f"Дата анализа: {now.strftime('%d.%m.%Y %H:%M:%S')}")
        print("\n" + "-"*80)
        
        print(f"\n📊 0-3 месяца: {len(groups['3_months'])} пользователей")
        print(f"📊 3-6 месяцев: {len(groups['6_months'])} пользователей")
        print(f"📊 6-12 месяцев: {len(groups['12_months'])} пользователей")
        print(f"📊 12+ месяцев: {len(groups['12_plus_months'])} пользователей")
        
        # Детальная информация по группам
        print("\n" + "="*80)
        print("ДЕТАЛЬНАЯ ИНФОРМАЦИЯ")
        print("="*80)
        
        for group_name, users_list in groups.items():
            if not users_list:
                continue
                
            period_name = {
                '3_months': '0-3 месяца',
                '6_months': '3-6 месяцев',
                '12_months': '6-12 месяцев',
                '12_plus_months': '12+ месяцев'
            }[group_name]
            
            print(f"\n{'='*80}")
            print(f"👥 {period_name.upper()} ({len(users_list)} пользователей)")
            print(f"{'='*80}")
            
            # Сортируем по времени пребывания (от большего к меньшему)
            sorted_users = sorted(users_list, key=lambda x: x['membership_months'], reverse=True)
            
            for i, data in enumerate(sorted_users[:20], 1):  # Показываем топ-20
                user = data['user']
                months = data['membership_months']
                days = data['membership_days']
                first_date = data['first_subscription_date'].strftime('%d.%m.%Y')
                active_end = data['active_subscription'].end_date.strftime('%d.%m.%Y')
                
                username = f"@{user.username}" if user.username else f"ID:{user.telegram_id}"
                name = f"{user.first_name} {user.last_name or ''}".strip() or "Без имени"
                
                print(f"{i:2}. {name} ({username})")
                print(f"    📅 Первая подписка: {first_date}")
                print(f"    ⏱️  В клубе: {days} дней ({months:.1f} месяцев)")
                print(f"    📆 Подписка до: {active_end}")
                print(f"    🔢 Всего подписок: {data['total_subscriptions']}")
                print()
            
            if len(sorted_users) > 20:
                print(f"    ... и еще {len(sorted_users) - 20} пользователей")
        
        # ТОП-10 пользователей по времени пребывания
        print("\n" + "="*80)
        print("🏆 ТОП-10 ПОЛЬЗОВАТЕЛЕЙ ПО ВРЕМЕНИ ПРЕБЫВАНИЯ В КЛУБЕ")
        print("="*80)
        
        # Сортируем всех пользователей по времени пребывания
        all_users_sorted = sorted(users_data.values(), key=lambda x: x['membership_months'], reverse=True)
        top_10 = all_users_sorted[:10]
        
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i, data in enumerate(top_10, 1):
            user = data['user']
            months = data['membership_months']
            days = data['membership_days']
            first_date = data['first_subscription_date'].strftime('%d.%m.%Y')
            active_end = data['active_subscription'].end_date.strftime('%d.%m.%Y')
            
            username = f"@{user.username}" if user.username else f"ID:{user.telegram_id}"
            name = f"{user.first_name} {user.last_name or ''}".strip() or "Без имени"
            
            medal = medals[i-1] if i <= 10 else f"{i}."
            
            print(f"\n{medal} {name} ({username})")
            print(f"   📅 В клубе: {days} дней ({months:.1f} месяцев)")
            print(f"   🎯 Первая подписка: {first_date}")
            print(f"   📆 Текущая подписка до: {active_end}")
            print(f"   🔢 Всего продлений: {data['total_subscriptions']}")
        
        # Общая статистика
        print("\n" + "="*80)
        print("ОБЩАЯ СТАТИСТИКА")
        print("="*80)
        
        total_months = sum(d['membership_months'] for d in users_data.values())
        avg_months = total_months / len(users_data) if users_data else 0
        
        print(f"Среднее время пребывания: {avg_months:.1f} месяцев")
        
        total_days = sum(d['membership_days'] for d in users_data.values())
        avg_days = total_days / len(users_data) if users_data else 0
        print(f"Среднее время пребывания: {avg_days:.0f} дней")
        
        max_user = max(users_data.values(), key=lambda x: x['membership_months'])
        print(f"\n🏆 Самый долгий участник:")
        user = max_user['user']
        username = f"@{user.username}" if user.username else f"ID:{user.telegram_id}"
        name = f"{user.first_name} {user.last_name or ''}".strip() or "Без имени"
        print(f"    {name} ({username})")
        print(f"    В клубе: {max_user['membership_days']} дней ({max_user['membership_months']:.1f} месяцев)")
        print(f"    С: {max_user['first_subscription_date'].strftime('%d.%m.%Y')}")


if __name__ == "__main__":
    asyncio.run(analyze_membership_duration())

