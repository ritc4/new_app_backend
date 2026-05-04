import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings


@pytest_asyncio.fixture
async def db_session():
    # Используем вашу текущую БД для тестов (в будущем лучше создать отдельную)
    engine = create_async_engine(settings.db.async_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client():
    # Подключаемся к вашему Redis
    client = Redis.from_url(settings.redis.url, decode_responses=True)
    yield client
    await client.aclose()
