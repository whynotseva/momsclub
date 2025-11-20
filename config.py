import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Токен бота Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Проверка наличия токена
if not BOT_TOKEN:
    raise ValueError("Не задан токен бота. Укажите BOT_TOKEN в .env файле")

# Конфигурация платежной системы ЮКасса
# КРИТИЧНО: Не используем значения по умолчанию для безопасности
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
YOOKASSA_WEBHOOK_URL = os.getenv("YOOKASSA_WEBHOOK_URL", "https://momsclubwebhook.ru/webhook")

# Проверка наличия обязательных параметров ЮКассы
if not YOOKASSA_SHOP_ID:
    raise ValueError("КРИТИЧНО: Не задан YOOKASSA_SHOP_ID. Укажите в .env файле")
if not YOOKASSA_SECRET_KEY:
    raise ValueError("КРИТИЧНО: Не задан YOOKASSA_SECRET_KEY. Укажите в .env файле")

YOOKASSA_CONFIG = {
    "shop_id": YOOKASSA_SHOP_ID,
    "secret_key": YOOKASSA_SECRET_KEY,
    "webhook_url": YOOKASSA_WEBHOOK_URL
}
