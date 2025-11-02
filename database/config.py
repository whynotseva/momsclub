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
engine = create_async_engine(DATABASE_URL, echo=True, connect_args={"check_same_thread": False})

# Создание сессии для работы с базой данных
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Базовый класс для моделей
Base = declarative_base()

# Функция для получения сессии базы данных
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
        await session.close() 