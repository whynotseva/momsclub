"""
Рассылка промо-акции: картинка price690.jpg + текст (строгое HTML форматирование).
Тестовый запуск (по умолчанию) — ADMIN_IDS; режим "all" — всем пользователям.
Всегда показываем кнопку "🍯 приобрести доступ" (callback_data=subscribe).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from sqlalchemy import select

from database.config import AsyncSessionLocal
from database.models import User
from utils.constants import ADMIN_IDS

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

IMAGE_PATH = Path("media/price690.jpg")

# Строгое форматирование (соответствует скрину)
BROADCAST_TEXT_HTML = (
    "🍯 нуууу мёд, изменения в клубе:\n\n"
    "Время творить акции, иначе межсезонье будет совсем скучным:\n\n"
    "🎞️ <b>для всех кто в moms club или когда-то был в клубе:</b> стоимость участия в ноябре = <b>690 рублей</b>\n\n"
    "🎞️ <b>для всех новеньких, кто никогда не был в клубе:</b> первый месяц подписки = <b>690 рублей</b>\n\n"
    "<i>MOMS CLUB</i>\n"
    "— каждый понедельник новые идеи для рилс & постов\n\n"
    "— reels challenge & контент-марафоны\n\n"
    "— уютное коммьюнити мам-блогеров, коллаборации и возможность найти сотрудничества с брендами\n\n"
    "— огромная библиотеке знаний про блогинг, контент & сьемки\n\n"
    "<i>Успевай присоединиться к нам 🍯🤎🫂</i>"
)


def build_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🍯 приобрести доступ", callback_data="subscribe")]]
    )


async def send_to_users(user_ids: Iterable[int]):
    if not IMAGE_PATH.exists():
        logger.error(f"Изображение не найдено: {IMAGE_PATH} (pwd={Path.cwd()})")
    photo = FSInputFile(str(IMAGE_PATH))
    sent, skipped = 0, 0
    async with AsyncSessionLocal() as session:
        for tg_id in user_ids:
            try:
                # проверяем, что пользователь существует
                result = await session.execute(select(User).where(User.telegram_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    skipped += 1
                    continue

                kb = build_keyboard()
                # 1) фото
                await bot.send_photo(chat_id=tg_id, photo=photo)
                # 2) текст
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
                logger.error(f"Ошибка отправки пользователю {tg_id}: {e}")
                await asyncio.sleep(0.05)
    logger.info(f"Отправлено: {sent}, пропущено: {skipped}")


async def send_to_admins():
    logger.info("Тестовая промо-рассылка администраторам")
    await send_to_users(ADMIN_IDS)


async def send_to_all():
    logger.info("Промо-рассылка всем пользователям")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.telegram_id))
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
