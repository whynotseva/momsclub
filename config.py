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
YOOKASSA_CONFIG = {
    "shop_id": os.getenv("YOOKASSA_SHOP_ID", "1081645"),
    "secret_key": os.getenv("YOOKASSA_SECRET_KEY", "live_QVOOyvhM_1UYh2svWeqfccXKD742b8P227YkwI_WW6I"),
    "webhook_url": os.getenv("YOOKASSA_WEBHOOK_URL", "https://momsclubwebhook.ru/webhook")
}

# Проверка наличия обязательных параметров ЮКассы
if not YOOKASSA_CONFIG["shop_id"] or not YOOKASSA_CONFIG["secret_key"]:
    raise ValueError("Не заданы параметры ЮКассы. Укажите YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в .env файле")
