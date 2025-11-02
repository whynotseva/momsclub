"""
Скрипт рассылки анонса InstaBot для Mom's Club
"""
import asyncio
import logging
import os
from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.models import User
from dotenv import load_dotenv
from utils.constants import ADMIN_IDS
from sqlalchemy import select

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)

BROADCAST_TEXT = """Дорогие, у нас большая новость 🎞️🥹

Я так ждала этого момента, чтобы поделиться с вами — теперь в <b>Mom's Club</b> появилось то, о чём вы давно просили 🤎

<b>✨ Встречайте — InstaBot! ✨</b>
Наш собственный <b>AI-помощник</b>, созданный специально для участниц клуба.

Знаю, как часто мы с вами обсуждали:
— <i>«Что сегодня выложить?»</i>
— <i>«Какой Reels снять, чтобы залетел?»</i>
— <i>«Где брать свежие идеи и вдохновение?»</i>

Теперь можно выдохнуть. <b>InstaBot берёт это на себя</b> 💫

Он поможет:
💡 Придумать идеи для постов и Reels
📝 Писать цепляющие тексты и заголовки
🎨 Работать с оформлением профиля
🖼 Создавать картинки для контента и лид-магнитов
🎙 Расшифровывать аудио и видео в текст

Это твой личный <b>AI-ассистент</b>, который понимает блогинг, формат мам-контента и стиль клуба.
Он экономит время и возвращает вдохновение, чтобы ты могла больше быть в моменте с собой и семьёй 🌸

💌 Новый шаг для нашего клуба теперь в <b>Mom's Club</b> не только разборы, идеи, поддержка и челленджи
но и свой <b>AI-помощник для блогинга — InstaBot!</b>

Доступ открыт уже сейчас внутри клуба 🫶"""

IMAGE_PATH = 'media/instabot.jpg'

keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text='✨ Открыть InstaBot', url='https://t.me/instaio_bot')]]
)

async def send_to_admins():
    """Тестовая отправка админам"""
    logger.info('='*50)
    logger.info('ТЕСТОВАЯ РАССЫЛКА АДМИНАМ')
    logger.info('='*50)
    success = 0
    
    for admin_id in ADMIN_IDS:
        try:
            # Отправляем фото
            photo = FSInputFile(IMAGE_PATH)
            await bot.send_photo(chat_id=admin_id, photo=photo)
            
            # Отправляем текст с кнопкой
            await bot.send_message(
                chat_id=admin_id,
                text=BROADCAST_TEXT,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            success += 1
            logger.info(f'✅ Отправлено админу {admin_id}')
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f'❌ Ошибка отправки админу {admin_id}: {e}')
    
    logger.info(f'Успешно отправлено: {success}/{len(ADMIN_IDS)}')

async def send_to_all():
    """Полная рассылка всем пользователям"""
    logger.info('='*50)
    logger.info('ПОЛНАЯ РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ')
    logger.info('='*50)
    
    success, error, blocked = 0, 0, 0
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        total = len(users)
        
        logger.info(f'Всего пользователей: {total}')
        
        for i, user in enumerate(users, 1):
            try:
                # Отправляем фото
                photo = FSInputFile(IMAGE_PATH)
                await bot.send_photo(chat_id=user.telegram_id, photo=photo)
                
                # Отправляем текст с кнопкой
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=BROADCAST_TEXT,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
                
                success += 1
                
                if i % 10 == 0:
                    logger.info(f'Прогресс: {i}/{total} ({round(i/total*100, 1)}%)')
                
                await asyncio.sleep(0.1)  # Увеличили задержку из-за 2 сообщений
                
            except Exception as e:
                error_str = str(e)
                if 'blocked' in error_str or 'deactivated' in error_str:
                    blocked += 1
                else:
                    error += 1
                    logger.error(f'Ошибка отправки пользователю {user.telegram_id}: {e}')
    
    logger.info('='*50)
    logger.info(f'✅ Успешно: {success}')
    logger.info(f'⚠️  Заблокировали бота: {blocked}')
    logger.info(f'❌ Ошибки: {error}')
    logger.info(f'📊 Процент доставки: {round(success/(success+blocked+error)*100, 1)}%')
    logger.info('='*50)

async def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        await send_to_all()
    else:
        await send_to_admins()
    
    await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())

