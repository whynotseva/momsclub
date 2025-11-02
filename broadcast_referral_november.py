"""
Рассылка: Особенная реферальная система Ноября 2025
Тестовый режим (по умолчанию) — только ADMIN_IDS. Режим "all" — всем пользователям.

1. Сначала отправляется видео-кружок refnovember.mp4
2. Затем текст с HTML форматированием
3. Три кнопки под текстом
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

# Путь к видео-кружку
VIDEO_PATH = Path("media/refnovember.mp4")

# HTML форматирование (используем \n для переносов, Telegram не поддерживает <br>)
BROADCAST_TEXT_HTML = (
    "<b>Девочки, красоточки 🌸</b>\n\n"
    
    "Думали, на этом наши акции закончились?\n"
    "Нееет 😏💕\n\n"
    
    "Мы правда хотим, чтобы вам здесь было максимально уютно, полезно и тепло — поэтому запускаем на ноябрь <b>уникальную реферальную систему Moms Club</b> ✨\n\n"
    
    "💖 <b>Как работает рефералка:</b>\n\n"
    
    "1️⃣ Делишься в сторис отзывом или любым контентом про Moms Club\n"
    "2️⃣ Приглашаешь подругу\n\n"
    
    "И <i>ты, и подруга</i> получаете\n"
    "🎁 <b>по +15 дней подписки бесплатно</b>\n\n"
    
    "После её оплаты просто пишешь нам в поддержку или мне в личку + прикладываешь скрин сторис и ник подруги — и мы начислим бонус ✨\n\n"
    
    "🔥 <b>Напоминаем:</b>\n"
    "Доступ на весь ноябрь стоит всего <b>690₽</b>\n"
    "Это всего <b>≈ 23₽ в день</b> 😳😁\n"
    "(меньше, чем чашка кофе ☕️ — и ты в сильном женском комьюнити каждый день!)\n\n"
    
    "Красота же? 😍\n"
    "Мы каждый день делаем Moms Club ещё уютнее, полезнее и вдохновляющим.\n\n"
    
    "Уверены, тебе есть что рассказать о нас в сторис 🫶\n"
    "Поехали дарить женскую поддержку дальше ✨"
)


def build_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру с тремя кнопками"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✨ Приобрести доступ", callback_data="subscribe")],
            [InlineKeyboardButton(text="📝 Я пригласила пользователя", url="https://t.me/momsclubsupport")],
            [InlineKeyboardButton(text="💌 Написать лично мне", url="https://t.me/polinadmitrenkoo")]
        ]
    )


async def send_to_users(user_ids: Iterable[int]):
    """Отправка рассылки пользователям"""
    if not VIDEO_PATH.exists():
        logger.error(f"Видео не найдено: {VIDEO_PATH} (pwd={Path.cwd()})")
        return
    
    video_note = FSInputFile(str(VIDEO_PATH))
    keyboard = build_keyboard()
    sent, skipped = 0, 0
    
    async with AsyncSessionLocal() as session:
        for tg_id in user_ids:
            try:
                # Проверяем, что пользователь существует
                result = await session.execute(select(User).where(User.telegram_id == tg_id))
                user = result.scalar_one_or_none()
                if not user:
                    skipped += 1
                    continue

                # 1) Видео-кружок
                await bot.send_video_note(
                    chat_id=user.telegram_id,
                    video_note=video_note
                )
                
                # Небольшая задержка между видео и текстом
                await asyncio.sleep(0.3)
                
                # 2) Текст с кнопками
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=BROADCAST_TEXT_HTML,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent += 1
                await asyncio.sleep(0.1)  # Задержка между пользователями
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {tg_id}: {e}")
                await asyncio.sleep(0.1)
    
    logger.info(f"Отправлено: {sent}, пропущено: {skipped}")


async def send_to_admins():
    """Тестовая рассылка администраторам"""
    logger.info("Тестовая рассылка реферальной системы администраторам")
    await send_to_users(ADMIN_IDS)


async def send_to_all():
    """Полная рассылка всем пользователям"""
    logger.info("Полная рассылка реферальной системы всем пользователям")
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

