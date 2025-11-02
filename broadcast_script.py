#!/usr/bin/env python3
"""
Скрипт массовой рассылки сообщений для Mom's Club

Функционал:
- Тестовый режим (только админам)
- Боевой режим (всем пользователям)
- Отчетность об отправке
- Обработка заблокированных пользователей
- HTML форматирование
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any
import time

# Добавляем текущую директорию в путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from database.config import AsyncSessionLocal
from database.crud import get_all_users_with_subscriptions, mark_user_as_blocked
from config import BOT_TOKEN
from utils.constants import ADMIN_IDS

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'broadcast_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)

# Путь к изображению для рассылки
BROADCAST_IMAGE_PATH = os.path.join("media", "сентябрьрассылка.PNG")

# Текст рассылки с правильным HTML форматированием
BROADCAST_TEXT = """новый сезон осень 🍂 
welcome, расписание на <b>СЕНТЯБРЬ</b> 🧺🧸

<i>*в библиотеке все темы за предыдущие месяца (а их там очень много)</i>

🤩 сентябрь будет очень насыщенным, потому что у нас абсолютно новая программа клуба, вас ждет:

— новый <b>CHALLENGE</b> и он будет по сторис > с заданиями & небольшими разборами > повышаем лояльность аудитории 🫂

— <b>ИДЕИ ДЛЯ КОНТЕНТА</b> > мудборды & референсы для ваших съемок (создадим эстетику в этом сезоне 🧺)

<blockquote>🌟 а так же разборы ваших съемок — создавай контент по референсам & получай обратную связь (это что тот самый контент-марафон? 🥹)</blockquote>

— важные подкасты о новой эре в инст > как теперь вести блог? и полезные статьи 🤌🏼

безусловно множество идей для ваших рилс и постов & огромная поддержка от <a href="tg://resolve?domain=polinadmitrenkoo">@polinadmitrenkoo</a> и <a href="tg://resolve?domain=OlyaGrishina92">@OlyaGrishina92</a> 🤎🧺🍂

<u>Готовы к новому сезону?</u>"""

class BroadcastStats:
    """Класс для сбора статистики рассылки"""
    
    def __init__(self):
        self.total_users = 0
        self.successful_sends = 0
        self.blocked_users = 0
        self.errors = 0
        self.error_details = []
        self.blocked_user_details = []
        self.start_time = None
        self.end_time = None
    
    def start(self):
        """Начало отсчета времени"""
        self.start_time = datetime.now()
        logger.info(f"🚀 Начало рассылки: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def finish(self):
        """Окончание отсчета времени"""
        self.end_time = datetime.now()
        duration = self.end_time - self.start_time
        logger.info(f"🏁 Окончание рассылки: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"⏱️ Общее время: {duration}")
    
    def add_success(self):
        """Учет успешной отправки"""
        self.successful_sends += 1
        if self.successful_sends % 10 == 0:
            logger.info(f"✅ Отправлено успешно: {self.successful_sends}/{self.total_users}")
    
    def add_blocked(self, user_id: int, username: str = None):
        """Учет заблокированного пользователя"""
        self.blocked_users += 1
        self.blocked_user_details.append({
            'user_id': user_id,
            'username': username,
            'time': datetime.now()
        })
        logger.warning(f"🚫 Пользователь {user_id} заблокировал бота (всего заблокированных: {self.blocked_users})")
    
    def add_error(self, user_id: int, error: str, username: str = None):
        """Учет ошибки отправки"""
        self.errors += 1
        self.error_details.append({
            'user_id': user_id,
            'username': username,
            'error': error,
            'time': datetime.now()
        })
        logger.error(f"❌ Ошибка отправки пользователю {user_id}: {error} (всего ошибок: {self.errors})")
    
    def get_report(self) -> str:
        """Формирует итоговый отчет"""
        duration = self.end_time - self.start_time if self.end_time else timedelta(0)
        
        success_rate = round((self.successful_sends / self.total_users * 100), 1) if self.total_users > 0 else 0
        
        report = f"""
📊 <b>ОТЧЕТ О РАССЫЛКЕ</b>

⏱️ <b>Время выполнения:</b> {duration}
📅 <b>Завершено:</b> {self.end_time.strftime('%Y-%m-%d %H:%M:%S') if self.end_time else 'Не завершено'}

📈 <b>ОБЩАЯ СТАТИСТИКА:</b>
👥 Всего пользователей: {self.total_users}
✅ Успешно отправлено: {self.successful_sends}
🚫 Заблокированных: {self.blocked_users}
❌ Ошибок: {self.errors}
📊 Успешность: {success_rate}%

🚫 <b>ЗАБЛОКИРОВАННЫЕ ПОЛЬЗОВАТЕЛИ:</b>
"""
        
        if self.blocked_user_details:
            for blocked in self.blocked_user_details[:10]:  # Показываем первые 10
                username_info = f"@{blocked['username']}" if blocked['username'] else "без username"
                report += f"• ID: {blocked['user_id']} ({username_info})\n"
            
            if len(self.blocked_user_details) > 10:
                report += f"... и еще {len(self.blocked_user_details) - 10} пользователей\n"
        else:
            report += "Нет заблокированных пользователей\n"
        
        report += "\n❌ <b>ОШИБКИ ОТПРАВКИ:</b>\n"
        
        if self.error_details:
            for error in self.error_details[:5]:  # Показываем первые 5 ошибок
                username_info = f"@{error['username']}" if error['username'] else "без username"
                error_short = error['error'][:100] + "..." if len(error['error']) > 100 else error['error']
                report += f"• ID: {error['user_id']} ({username_info}): {error_short}\n"
            
            if len(self.error_details) > 5:
                report += f"... и еще {len(self.error_details) - 5} ошибок\n"
        else:
            report += "Нет ошибок отправки\n"
        
        return report

async def get_all_active_users():
    """Получает всех пользователей (кроме заблокированных) для рассылки"""
    async with AsyncSessionLocal() as session:
        try:
            # Получаем всех пользователей с подписками и без
            users_with_subs = await get_all_users_with_subscriptions(session)
            
            # Фильтруем заблокированных пользователей
            active_users = []
            for user, subscription in users_with_subs:
                if not user.is_blocked:  # Исключаем заблокированных
                    active_users.append(user)
            
            logger.info(f"Получено {len(active_users)} активных пользователей для рассылки")
            return active_users
            
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей: {e}")
            return []

async def send_broadcast_message(user, stats: BroadcastStats, test_mode: bool = False):
    """
    Отправляет сообщение рассылки одному пользователю
    
    Args:
        user: Объект пользователя из БД
        stats: Объект статистики для учета результатов
        test_mode: Флаг тестового режима
    """
    try:
        # Создаем инлайн-клавиатуру с кнопкой "Вступить"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💓 Вступить", callback_data="subscribe")]
            ]
        )
        
        # Проверяем наличие изображения
        if os.path.exists(BROADCAST_IMAGE_PATH):
            # Отправляем изображение с текстом
            photo = FSInputFile(BROADCAST_IMAGE_PATH)
            await bot.send_photo(
                chat_id=user.telegram_id,
                photo=photo,
                caption=BROADCAST_TEXT,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            # Если изображения нет, отправляем только текст
            logger.warning(f"Изображение {BROADCAST_IMAGE_PATH} не найдено, отправляем только текст")
            await bot.send_message(
                chat_id=user.telegram_id,
                text=BROADCAST_TEXT,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        
        stats.add_success()
        
        # Добавляем небольшую задержку для соблюдения лимитов Telegram
        await asyncio.sleep(0.05)  # 50ms между отправками
        
    except Exception as e:
        error_str = str(e)
        
        # Проверяем, заблокировал ли пользователь бота
        if 'bot was blocked by the user' in error_str or 'USER_IS_BLOCKED' in error_str:
            stats.add_blocked(user.telegram_id, user.username)
            
            # Отмечаем пользователя как заблокированного в БД
            if not test_mode:  # В боевом режиме обновляем БД
                async with AsyncSessionLocal() as session:
                    await mark_user_as_blocked(session, user.id)
        else:
            stats.add_error(user.telegram_id, error_str, user.username)

async def run_broadcast(test_mode: bool = False):
    """
    Запускает массовую рассылку
    
    Args:
        test_mode: Если True, отправляет только админам. Если False - всем пользователям.
    """
    
    # Проверяем наличие изображения
    if not os.path.exists(BROADCAST_IMAGE_PATH):
        logger.error(f"❌ Изображение для рассылки не найдено: {BROADCAST_IMAGE_PATH}")
        print(f"❌ Ошибка: Файл {BROADCAST_IMAGE_PATH} не найден!")
        return
    
    # Инициализируем статистику
    stats = BroadcastStats()
    stats.start()
    
    mode_name = "ТЕСТОВЫЙ" if test_mode else "БОЕВОЙ"
    logger.info(f"🚀 Запуск рассылки в {mode_name} режиме")
    print(f"🚀 Запуск рассылки в {mode_name} режиме")
    
    # Получаем список пользователей
    if test_mode:
        # В тестовом режиме отправляем только администраторам
        test_users = []
        async with AsyncSessionLocal() as session:
            from database.crud import get_user_by_telegram_id
            for admin_id in ADMIN_IDS:
                user = await get_user_by_telegram_id(session, admin_id)
                if user:
                    test_users.append(user)
        
        users = test_users
        logger.info(f"🧪 Тестовый режим: найдено {len(users)} администраторов")
        print(f"🧪 Тестовый режим: найдено {len(users)} администраторов")
    else:
        # В боевом режиме отправляем всем пользователям
        users = await get_all_active_users()
        logger.info(f"🌍 Боевой режим: найдено {len(users)} активных пользователей")
        print(f"🌍 Боевой режим: найдено {len(users)} активных пользователей")
    
    if not users:
        logger.error("❌ Пользователи для рассылки не найдены")
        print("❌ Пользователи для рассылки не найдены")
        return
    
    stats.total_users = len(users)
    
    # Подтверждение запуска
    print(f"\n📊 Готов к рассылке:")
    print(f"   • Режим: {mode_name}")
    print(f"   • Пользователей: {len(users)}")
    print(f"   • Изображение: {BROADCAST_IMAGE_PATH}")
    print(f"   • Текст: {len(BROADCAST_TEXT)} символов")
    
    if not test_mode:
        confirmation = input(f"\n⚠️  ВНИМАНИЕ! Вы запускаете БОЕВУЮ рассылку для {len(users)} пользователей!\nВведите 'YES' для подтверждения: ")
        if confirmation != 'YES':
            print("❌ Рассылка отменена")
            return
    
    print("\n🚀 Начинаем рассылку...")
    
    # Отправляем сообщения
    for i, user in enumerate(users, 1):
        try:
            logger.info(f"📤 Отправка {i}/{len(users)} пользователю {user.telegram_id}")
            
            # Показываем прогресс каждые 10 пользователей
            if i % 10 == 0 or i == len(users):
                print(f"📤 Прогресс: {i}/{len(users)} ({round(i/len(users)*100, 1)}%)")
            
            await send_broadcast_message(user, stats, test_mode)
            
        except Exception as e:
            logger.error(f"Критическая ошибка при отправке пользователю {user.telegram_id}: {e}")
            stats.add_error(user.telegram_id, str(e), user.username)
    
    # Завершаем подсчет времени
    stats.finish()
    
    # Формируем и отправляем отчет администраторам
    report = stats.get_report()
    logger.info("📊 Итоговая статистика рассылки:")
    logger.info(report)
    
    # Отправляем отчет всем администраторам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=report,
                parse_mode="HTML"
            )
            logger.info(f"📊 Отчет отправлен администратору {admin_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке отчета администратору {admin_id}: {e}")
    
    print(f"\n🎉 Рассылка завершена!")
    print(f"✅ Успешно: {stats.successful_sends}")
    print(f"🚫 Заблокированных: {stats.blocked_users}")
    print(f"❌ Ошибок: {stats.errors}")
    print(f"📊 Успешность: {round(stats.successful_sends/stats.total_users*100, 1) if stats.total_users > 0 else 0}%")

async def main():
    """Основная функция скрипта"""
    print("=" * 60)
    print("🌸 СКРИПТ МАССОВОЙ РАССЫЛКИ MOM'S CLUB 🌸")
    print("=" * 60)
    
    # Проверяем наличие изображения
    if not os.path.exists(BROADCAST_IMAGE_PATH):
        print(f"❌ ОШИБКА: Изображение не найдено: {BROADCAST_IMAGE_PATH}")
        print("Убедитесь, что файл существует и попробуйте снова.")
        return
    
    print("✅ Изображение для рассылки найдено")
    print(f"📱 Бот токен загружен: {'✅' if BOT_TOKEN else '❌'}")
    print(f"👨‍💼 Администраторов: {len(ADMIN_IDS)}")
    
    # Предпросмотр сообщения
    print(f"\n📄 ПРЕДПРОСМОТР СООБЩЕНИЯ:")
    print(f"🖼️ Изображение: {os.path.basename(BROADCAST_IMAGE_PATH)}")
    print(f"📝 Текст: {BROADCAST_TEXT[:200]}...")
    print(f"🔘 Кнопка: 'Вступить' → callback_data='subscribe'")
    
    # Выбор режима
    print(f"\n🎛️ ВЫБЕРИТЕ РЕЖИМ РАССЫЛКИ:")
    print("1 - 🧪 Тестовый режим (только администраторам)")
    print("2 - 🌍 Боевой режим (всем пользователям)")
    print("q - ❌ Отмена")
    
    while True:
        choice = input("\nВаш выбор (1/2/q): ").strip().lower()
        
        if choice == 'q':
            print("❌ Рассылка отменена")
            return
        elif choice == '1':
            print("🧪 Выбран тестовый режим")
            await run_broadcast(test_mode=True)
            break
        elif choice == '2':
            print("🌍 Выбран боевой режим")
            await run_broadcast(test_mode=False)
            break
        else:
            print("❌ Неверный выбор. Введите 1, 2 или q")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Рассылка прервана пользователем")
        logger.info("Рассылка прервана пользователем (Ctrl+C)")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        logger.error(f"Критическая ошибка в main(): {e}", exc_info=True)
