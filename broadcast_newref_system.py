"""
Рассылка: Новая реферальная система (Ноябрь 2025)
Запуск: python3 broadcast_newref_system.py [admins|all]

- admins (по умолчанию): отправка только ADMIN_IDS для теста
- all: отправка всем пользователям (таблица users, не заблокированные)
"""

import asyncio
import logging
from datetime import datetime
import os
from pathlib import Path
from typing import Iterable

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from config import BOT_TOKEN
from database.config import AsyncSessionLocal
from database.models import User
from database.crud import mark_user_as_blocked
from utils.constants import ADMIN_IDS

logger = logging.getLogger("broadcast_newref")
logger.setLevel(logging.INFO)
_fh = logging.FileHandler(f"broadcast_newref_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
_fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.handlers = []
logger.addHandler(_fh)
logger.addHandler(_sh)

bot = Bot(token=BOT_TOKEN)

IMAGE_PATH = Path("media/newref.jpg")

# HTML форматирование текста рассылки
BROADCAST_TEXT_HTML = (
    "🤎 <b>Красотки, у нас обновление, от которого вы будете в шоке!</b>\n\n"
    
    "Мы полностью обновили реферальную программу — теперь это не бонус, а <b>реальный доход</b> 💰🧺\n\n"
    
    "<b>Что поменялось?</b>\n\n"
    
    "Теперь при КАЖДОЙ оплате подруги ты сама выбираешь награду:\n"
    "🎁 +7 дней подписки\n"
    "💸 или деньги на баланс (10–30%!)\n\n"
    
    "Да, настоящие деньги — можно:\n"
    "💳 оплатить свою подписку\n"
    "💸 вывести от 500₽\n"
    "🔄 получать каждый месяц при продлениях подруги — каждое продление твоей подруги = твой процент\n\n"
    
    "<b>Как начать:</b>\n\n"
    
    "Открой «Личный кабинет»\n\n"
    
    "«Реферальная программа»\n\n"
    
    "Скопируй ссылку и отправь подругам\n\n"
    
    "Получай: дни или деньги 🎁\n\n"
    
    "<b>Уровни:</b> 10% / 15% / 20% / 30% (Platinum)\n\n"
    
    "<b>Это реально выгодно:</b>\n"
    "✔ пассивный доход\n"
    "✔ можно ходить в клуб бесплатно\n"
    "✔ деньги приходят каждый месяц"
)


def build_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой покупки"""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🍯 Купить доступ", callback_data="subscribe")]]
    )


async def send_report_to_admins(sent: int, skipped: int, blocked: int, errors: int, mode: str):
    """Отправляет отчет о рассылке администраторам"""
    report_text = (
        f"📊 <b>Отчет о рассылке: Новая реферальная система</b>\n\n"
        f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"📡 Режим: {'ТЕСТ (только админы)' if mode == 'admins' else 'ВСЕ ПОЛЬЗОВАТЕЛИ'}\n\n"
        f"✅ Отправлено: <b>{sent}</b>\n"
        f"⏭ Пропущено: {skipped}\n"
        f"🚫 Заблокировали: {blocked}\n"
        f"❌ Ошибки: {errors}\n\n"
        f"📈 Успешность: {(sent / (sent + blocked + errors) * 100) if (sent + blocked + errors) > 0 else 0:.1f}%"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=report_text,
                parse_mode="HTML"
            )
            logger.info(f"Отчет отправлен админу {admin_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки отчета админу {admin_id}: {e}")


async def send_to_users(user_ids: Iterable[int], mode: str = "admins"):
    """Отправка рассылки пользователям"""
    if not IMAGE_PATH.exists():
        logger.error(f"Изображение не найдено: {IMAGE_PATH} (pwd={Path.cwd()})")
        return
    
    photo = FSInputFile(str(IMAGE_PATH))
    keyboard = build_keyboard()
    sent, skipped, blocked_count, error_count = 0, 0, 0, 0
    
    async with AsyncSessionLocal() as session:
        for tg_id in user_ids:
            try:
                # Проверяем, что пользователь существует
                result = await session.execute(select(User).where(User.telegram_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    skipped += 1
                    continue

                # 1) Сначала отправляем фото с текстом и кнопкой
                await bot.send_photo(
                    chat_id=user.telegram_id,
                    photo=photo,
                    caption=BROADCAST_TEXT_HTML,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                
                sent += 1
                logger.info(f"✅ Отправлено пользователю {tg_id} ({sent}/{len(list(user_ids))})")
                await asyncio.sleep(0.05)  # Задержка между пользователями
                
            except Exception as e:
                msg = str(e)
                if "bot was blocked by the user" in msg or "USER_IS_BLOCKED" in msg:
                    blocked_count += 1
                    # Отмечаем в БД
                    try:
                        if user:
                            await mark_user_as_blocked(session, user.id)
                    except Exception:
                        pass
                    logger.warning(f"🚫 Пользователь {tg_id} заблокировал бота")
                else:
                    error_count += 1
                    logger.error(f"❌ Ошибка отправки пользователю {tg_id}: {e}")
                await asyncio.sleep(0.05)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 ИТОГО: отправлено={sent}, пропущено={skipped}, заблокировано={blocked_count}, ошибок={error_count}")
    logger.info(f"{'='*60}\n")
    
    # Отправляем отчет админам
    await send_report_to_admins(sent, skipped, blocked_count, error_count, mode)


async def send_to_admins():
    """Тестовая рассылка администраторам"""
    logger.info("🧪 ТЕСТОВАЯ РАССЫЛКА: Новая реферальная система (только админы)")
    logger.info(f"Админы: {ADMIN_IDS}")
    await send_to_users(ADMIN_IDS, mode="admins")


async def send_to_all():
    """Полная рассылка всем пользователям"""
    logger.info("🚀 БОЕВАЯ РАССЫЛКА: Новая реферальная система (ВСЕ ПОЛЬЗОВАТЕЛИ)")
    async with AsyncSessionLocal() as session:
        # Только активные и не заблокированные
        result = await session.execute(
            select(User.telegram_id).where(User.is_blocked == 0)
        )
        ids = [tg_id for (tg_id,) in result]
    
    logger.info(f"Найдено пользователей: {len(ids)}")
    
    # Подтверждение перед отправкой всем
    confirmation = input(f"\n⚠️  ВНИМАНИЕ! Вы собираетесь отправить рассылку {len(ids)} пользователям.\nПродолжить? (yes/no): ")
    if confirmation.lower() != "yes":
        logger.info("❌ Рассылка отменена пользователем")
        return
    
    await send_to_users(ids, mode="all")


async def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "admins"
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📨 РАССЫЛКА: Новая реферальная система")
    logger.info(f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    logger.info(f"🎯 Режим: {mode}")
    logger.info(f"{'='*60}\n")
    
    if mode == "all":
        await send_to_all()
    else:
        await send_to_admins()
    
    await bot.session.close()
    logger.info("\n✅ Скрипт завершен")


if __name__ == "__main__":
    asyncio.run(main())
