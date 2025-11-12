"""
Рассылка «СПИКЕР В КЛУБЕ» от 08.11.2025: картинка + текст + кнопка.
Запуск: python3 broadcast_update_20251108.py [admins|all]

- admins (по умолчанию): отправка только ADMIN_IDS для теста
- all: отправка всем пользователям (таблица users)
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

logger = logging.getLogger("broadcast_update")
logger.setLevel(logging.INFO)
_fh = logging.FileHandler(f"broadcast_update_20251108_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
_fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.handlers = []
logger.addHandler(_fh)
logger.addHandler(_sh)

bot = Bot(token=BOT_TOKEN)

IMAGE_PATH = Path("media/update08112025.jpg")

# Строгое HTML-форматирование (как на скрине)
BROADCAST_TEXT_HTML = (
    "Дорогие, welcome, в новую рубрику — <b>СПИКЕР В КЛУБЕ</b> 🎞️\n\n"
    "в ноябре, мы заметили, что многие увлеклись тренировками & питанием. Это прекрасно и для контента и "
    "<b>САМОЕ ГЛАВНОЕ</b> для вас 🥹🤎 <b>ведь это дает энергию и силу!</b>\n\n"
    "главное знать, как это делать правильно, поэтому "
    "<b>сегодня у участниц клуба есть возможность задать абсолютно любые вопросы нашему спикеру, "
    "<u>а завтра Кристина</u> (профессиональный тренер и нутрициолог) <u>запишет вам подробный подкаст-ответы</u></b>\n\n"
    "🎞️ приобрести подписку сейчас вы можете за 690₽"
)


def build_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🤎 Приобрести доступ", callback_data="subscribe")]]
    )


async def send_to_users(user_ids: Iterable[int]):
    if not IMAGE_PATH.exists():
        logger.error(f"Изображение не найдено: {IMAGE_PATH} (pwd={Path.cwd()})")
    photo = FSInputFile(str(IMAGE_PATH)) if IMAGE_PATH.exists() else None

    sent, skipped, blocked_count, error_count = 0, 0, 0, 0
    async with AsyncSessionLocal() as session:
        for tg_id in user_ids:
            try:
                result = await session.execute(select(User).where(User.telegram_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    skipped += 1
                    continue

                kb = build_keyboard()
                # 1) Сначала присылаем фото БЕЗ кнопки
                if photo:
                    await bot.send_photo(chat_id=tg_id, photo=photo)
                # 2) Затем присылаем текст С кнопкой
                await bot.send_message(
                    chat_id=tg_id,
                    text=BROADCAST_TEXT_HTML,
                    reply_markup=kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                msg = str(e)
                if "bot was blocked by the user" in msg or "USER_IS_BLOCKED" in msg:
                    blocked_count += 1
                    # отмечаем в БД
                    try:
                        if user:
                            await mark_user_as_blocked(session, user.id)
                    except Exception:
                        pass
                    logger.warning(f"Пользователь {tg_id} заблокировал бота")
                else:
                    error_count += 1
                    logger.error(f"Ошибка отправки пользователю {tg_id}: {e}")
                await asyncio.sleep(0.05)
    logger.info(f"ИТОГО: отправлено={sent}, пропущено={skipped}, заблокировано={blocked_count}, ошибок={error_count}")


async def send_to_admins():
    logger.info("Тестовая рассылка администраторам")
    await send_to_users(ADMIN_IDS)


async def send_to_all():
    logger.info("Боевая рассылка всем пользователям")
    async with AsyncSessionLocal() as session:
        # Только активные и не заблокированные
        result = await session.execute(select(User.telegram_id).where(User.is_blocked == 0))
        ids = [tg_id for (tg_id,) in result]
    await send_to_users(ids)


async def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "admins"
    if mode == "all":
        await send_to_all()
    else:
        await send_to_admins()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())