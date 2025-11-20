"""
Утилиты для досрочного продления подписки.

Позволяет пользователям продлевать подписку до её окончания с бонусными днями.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import get_active_subscription
from utils.constants import (
    SUBSCRIPTION_DAYS, 
    SUBSCRIPTION_DAYS_2MONTHS, 
    SUBSCRIPTION_DAYS_3MONTHS
)

logger = logging.getLogger(__name__)


# Настройки досрочного продления
EARLY_RENEWAL_BONUS_DAYS = 3  # Бонус за досрочное продление
EARLY_RENEWAL_THRESHOLD_DAYS = 7  # Продление за 7+ дней до окончания = бонус
AUTOPAY_PROTECTION_DAYS = 5  # Защита: не давать продлевать за 5 дней до автоплатежа


async def check_early_renewal_eligibility(
    session: AsyncSession,
    user_id: int
) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Проверяет возможность досрочного продления.
    
    Returns:
        Tuple[can_renew, reason, info]:
        - can_renew: True если можно продлить
        - reason: Причина отказа (если can_renew=False)
        - info: Информация о подписке для отображения
    """
    subscription = await get_active_subscription(session, user_id)
    
    if not subscription:
        # Нет активной подписки - можно купить новую
        return True, None, None
    
    now = datetime.now()
    days_left = (subscription.end_date - now).days
    
    # Информация о подписке
    info = {
        'end_date': subscription.end_date,
        'days_left': days_left,
        'has_autopay': subscription.next_retry_attempt_at is not None,
        'bonus_eligible': days_left >= EARLY_RENEWAL_THRESHOLD_DAYS,
        'subscription_id': subscription.id
    }
    
    # УМНАЯ ЛОГИКА: Автоплатеж автоматически сдвинется на новую дату!
    # Больше не блокируем продление - просто информируем
    if subscription.next_retry_attempt_at:
        days_until_autopay = (subscription.next_retry_attempt_at - now).days
        info['days_until_autopay'] = days_until_autopay
        logger.info(
            f"Досрочное продление с автоплатежом для user_id={user_id}: "
            f"автоплатеж через {days_until_autopay} дней, будет сдвинут автоматически"
        )
    
    # Всегда можно продлевать!
    logger.info(
        f"Досрочное продление доступно для user_id={user_id}: "
        f"осталось {days_left} дней, бонус={info['bonus_eligible']}"
    )
    return True, None, info


def calculate_new_end_date(
    current_end_date: datetime,
    days_to_add: int,
    bonus_eligible: bool
) -> Tuple[datetime, int, int]:
    """
    Рассчитывает новую дату окончания с учетом бонуса.
    
    Returns:
        Tuple[new_end_date, total_days, bonus_days]
    """
    bonus_days = EARLY_RENEWAL_BONUS_DAYS if bonus_eligible else 0
    total_days = days_to_add + bonus_days
    new_end_date = current_end_date + timedelta(days=total_days)
    
    return new_end_date, total_days, bonus_days


def format_subscription_status_message(
    days_left: int,
    end_date: datetime,
    has_autopay: bool
) -> str:
    """
    Форматирует сообщение о текущем статусе подписки.
    """
    # Эмодзи в зависимости от оставшихся дней
    if days_left > 14:
        status_emoji = "💎"
        status_text = "Подписка активна"
    elif days_left > 7:
        status_emoji = "✨"
        status_text = "Подписка активна"
    elif days_left > 3:
        status_emoji = "⚠️"
        status_text = "Скоро закончится"
    else:
        status_emoji = "🔴"
        status_text = "Заканчивается!"
    
    # Форматируем дату
    end_date_str = end_date.strftime("%d.%m.%Y")
    
    # Автопродление
    autopay_text = ""
    if has_autopay:
        autopay_text = "\n🔄 Автопродление включено"
    
    message = (
        f"{status_emoji} <b>{status_text}</b>\n\n"
        f"📅 Действует до: <b>{end_date_str}</b>\n"
        f"⏰ Осталось: <b>{days_left} дн.</b>"
        f"{autopay_text}"
    )
    
    return message


def format_renewal_options_message(
    current_end_date: datetime,
    days_left: int,
    bonus_eligible: bool,
    has_autopay: bool = False
) -> str:
    """
    Форматирует сообщение с вариантами продления.
    """
    from utils.constants import (
        SUBSCRIPTION_PRICE,
        SUBSCRIPTION_PRICE_2MONTHS,
        SUBSCRIPTION_PRICE_3MONTHS
    )
    
    # Заголовок
    if bonus_eligible:
        header = (
            "🎁 <b>Продли сейчас и получи бонус!</b>\n\n"
            f"При продлении за {days_left} дней до окончания "
            f"ты получаешь <b>+{EARLY_RENEWAL_BONUS_DAYS} дня в подарок</b> 🤍\n\n"
        )
    else:
        header = "💎 <b>Выбери тариф для продления:</b>\n\n"
    
    # Если есть автопродление - добавляем информацию
    if has_autopay:
        header += (
            "🔄 <i>У тебя включено автопродление</i>\n"
            "✨ Мы автоматически перенесём следующий платёж\n"
            "   на новую дату окончания подписки\n\n"
        )
    
    # Рассчитываем новые даты
    options = []
    
    # 1 месяц
    new_date_1m, total_days_1m, bonus_1m = calculate_new_end_date(
        current_end_date, SUBSCRIPTION_DAYS, bonus_eligible
    )
    total_days_with_current_1m = days_left + total_days_1m
    options.append(
        f"📦 <b>1 месяц</b> — {SUBSCRIPTION_PRICE}₽\n"
        f"   → До {new_date_1m.strftime('%d.%m.%Y')} "
        f"({total_days_with_current_1m} дн.)"
    )
    if bonus_1m > 0:
        options[-1] += f" 🎁"
    
    # 2 месяца
    new_date_2m, total_days_2m, bonus_2m = calculate_new_end_date(
        current_end_date, SUBSCRIPTION_DAYS_2MONTHS, bonus_eligible
    )
    total_days_with_current_2m = days_left + total_days_2m
    savings_2m = (SUBSCRIPTION_PRICE * 2) - SUBSCRIPTION_PRICE_2MONTHS
    options.append(
        f"\n📦 <b>2 месяца</b> — {SUBSCRIPTION_PRICE_2MONTHS}₽ "
        f"💰 <i>Выгода {savings_2m}₽</i>\n"
        f"   → До {new_date_2m.strftime('%d.%m.%Y')} "
        f"({total_days_with_current_2m} дн.)"
    )
    if bonus_2m > 0:
        options[-1] += f" 🎁"
    
    # 3 месяца
    new_date_3m, total_days_3m, bonus_3m = calculate_new_end_date(
        current_end_date, SUBSCRIPTION_DAYS_3MONTHS, bonus_eligible
    )
    total_days_with_current_3m = days_left + total_days_3m
    savings_3m = (SUBSCRIPTION_PRICE * 3) - SUBSCRIPTION_PRICE_3MONTHS
    options.append(
        f"\n📦 <b>3 месяца</b> — {SUBSCRIPTION_PRICE_3MONTHS}₽ "
        f"💰 <i>Выгода {savings_3m}₽</i>\n"
        f"   → До {new_date_3m.strftime('%d.%m.%Y')} "
        f"({total_days_with_current_3m} дн.)"
    )
    if bonus_3m > 0:
        options[-1] += f" 🎁"
    
    footer = "\n\n✨ <i>Все оплаченные дни сохраняются и суммируются!</i>"
    
    return header + "".join(options) + footer


def format_payment_success_message(
    new_end_date: datetime,
    days_added: int,
    bonus_days: int,
    autopay_moved: bool = False
) -> str:
    """
    Форматирует сообщение об успешном продлении.
    """
    new_date_str = new_end_date.strftime("%d.%m.%Y")
    
    message = (
        "✅ <b>Подписка успешно продлена!</b>\n\n"
        f"📅 Новая дата окончания: <b>{new_date_str}</b>\n"
        f"➕ Добавлено дней: <b>{days_added}</b>"
    )
    
    if bonus_days > 0:
        message += f"\n🎁 Бонус за досрочное продление: <b>+{bonus_days} дн.</b>"
    
    if autopay_moved:
        message += (
            f"\n\n🔄 <b>Автопродление обновлено</b>\n"
            f"✨ Следующий платёж: <b>{new_date_str}</b>\n"
            f"💰 Никаких двойных списаний!"
        )
    
    message += (
        "\n\n💎 Спасибо, что с нами, красотка! 🤍\n"
        "Продолжай расти и вдохновлять ✨"
    )
    
    return message


async def should_give_bonus(
    session: AsyncSession,
    user_id: int
) -> bool:
    """
    Проверяет, нужно ли давать бонус за досрочное продление.
    """
    subscription = await get_active_subscription(session, user_id)
    
    if not subscription:
        return False
    
    now = datetime.now()
    days_left = (subscription.end_date - now).days
    
    return days_left >= EARLY_RENEWAL_THRESHOLD_DAYS
