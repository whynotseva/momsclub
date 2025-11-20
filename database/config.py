from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Путь к файлу SQLite
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "momsclub.db")

# URL для подключения к базе данных SQLite
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

# Создание движка базы данных
# SQL-логирование отключено по умолчанию для безопасности (не логируем SQL в продакшене)
# Для отладки можно включить через переменную окружения SQL_ECHO=true
SQL_ECHO = os.getenv("SQL_ECHO", "False").lower() == "true"
engine = create_async_engine(DATABASE_URL, echo=SQL_ECHO, connect_args={"check_same_thread": False})

# Создание сессии для работы с базой данных
# ИСПРАВЛЕНО: expire_on_commit=False для предотвращения greenlet ошибок
# С expire_on_commit=False объекты НЕ становятся expired после commit
# Это безопасно в контексте async кода, так как каждый запрос использует свою сессию
# КРИТИЧНО для работы с циклами где используется commit внутри итерации
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Базовый класс для моделей
Base = declarative_base()

# Функция для получения сессии базы данных
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
        await session.close() 