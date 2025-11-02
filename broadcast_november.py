"""
Рассылка: расписание на ноябрь с картинкой и форматированным текстом.
Тестовый режим (по умолчанию) — только ADMIN_IDS. Режим "all" — всем пользователям.

Кнопка "Приобрести доступ" показывается только тем, у кого нет активной подписки.
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
from database.crud import has_active_subscription
from utils.constants import ADMIN_IDS

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

# Используем ASCII-путь на сервере, чтобы избежать проблем кодировки при отправке через aiohttp
IMAGE_PATH = Path("media/novemberfinal.jpg")

# HTML форматирование строго сохраняем по ТЗ
BROADCAST_TEXT_HTML = (
    "<b>Welcome в межсезонье — ноябрь 🥨🎞️</b>\n\n"
    "мы провели ребрендинг клуба, учли все пожелания 🫂🤎\n\n"
    "в этом месяце вас ждет:\n\n"
    "— <b>КОНТЕНТ МАРАФОН!</b> Да-да, тот самый! Пора готовиться к новому сезону по полной 🍯🥨\n"
    "<i>🎞️ 3 задания, обратная связь, идеи для контента, разборы трендов и антитрендов межсезонья</i>\n\n"
    "— <b>в ноябре мы готовимся к зиме & сделаем это вместе?</b>\n"
    "<i>🍯 подготовка блога к новому контенту, период нового сезона — это всегда про рост (для тех кто успевает)</i>\n\n"
    "— <b>КАЖДЫЙ ПОНЕДЕЛЬНИК новые идеи для рилс & постов</b> (адаптации, ugc идеи и многое другое)\n\n"
    "— <b>новая свежая рубрика УРОКИ МОНТАЖА</b> & разборы рилс > то, что нужно перед новым сезоном\n\n"
    "<blockquote>🥨🎞️ ВСТРЕЧА moms club в Москве, дата 15.11 🗓️</blockquote>\n"
    "<i>› еще обновления и сюрпризы вас ждут ниже 🧺</i>"
)


def build_keyboard(has_active: bool) -> InlineKeyboardMarkup | None:
    if has_active:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Приобрести доступ", callback_data="subscribe")]]
    )


async def send_to_users(user_ids: Iterable[int]):
    if not IMAGE_PATH.exists():
        logger.error(f"Изображение не найдено: {IMAGE_PATH} (pwd={Path.cwd()})")
    photo = FSInputFile(str(IMAGE_PATH))
    sent, skipped = 0, 0
    async with AsyncSessionLocal() as session:
        for tg_id in user_ids:
            try:
                # находим пользователя в БД по telegram_id
                result = await session.execute(select(User).where(User.telegram_id == tg_id))
                user: User | None = result.scalar_one_or_none()
                if not user:
                    skipped += 1
                    continue

                active = await has_active_subscription(session, user.id)
                kb = build_keyboard(active)

                # 1) картинка
                await bot.send_photo(chat_id=user.telegram_id, photo=photo)
                # 2) текст с форматированием и условной кнопкой
                await bot.send_message(
                    chat_id=user.telegram_id,
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
    logger.info("Тестовая рассылка администраторам")
    await send_to_users(ADMIN_IDS)


async def send_to_all():
    logger.info("Полная рассылка всем пользователям")
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


