"""
Конфигурация приложения LibriMomsClub Backend
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    """Настройки приложения"""
    
    # База данных
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR.parent}/momsclub.db"  # Для локальной разработки
    )
    
    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7  # Токен живёт 7 дней
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "momsclub_bot")
    
    # Notification API (для отправки пушей через бота)
    NOTIFICATION_API_KEY: str = os.getenv("NOTIFICATION_API_KEY", "")
    NOTIFICATION_API_URL: str = os.getenv("NOTIFICATION_API_URL", "http://localhost:8000/api/send_notification")
    
    # CORS
    ALLOWED_ORIGINS: list = os.getenv(
        "ALLOWED_ORIGINS",
        "https://librarymomsclub.ru,http://localhost:3000"
    ).split(",")
    
    # Загрузка файлов
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", f"{BASE_DIR}/uploads"))
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", 10485760))  # 10MB
    
    # Режим разработки
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # API
    API_V1_PREFIX: str = "/api"
    PROJECT_NAME: str = "LibriMomsClub API"
    VERSION: str = "1.0.0"
    
    def __init__(self):
        # Создать директорию для загрузок, если не существует
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# Создаём экземпляр настроек
settings = Settings()
