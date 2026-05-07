import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.core.jwt import create_tokens  # Проверьте путь к функции создания токена
from app.main import app  # Импортируем ваше FastAPI приложение
from app.models.user import User


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(settings.db.async_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    # Создаем асинхронного клиента для запросов к API
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Создает обычного пользователя."""
    user = User(phone="+79620048696", first_name="Иван", last_name="Иванов", role="customer", is_active=True)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_token(test_user: User):
    """Генерирует токен для обычного пользователя."""
    return create_tokens(data={"sub": test_user.phone, "id": test_user.id, "role": "customer"})


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession):
    """Создает администратора."""
    admin = User(phone="+70000000000", first_name="Admin", role="admin", is_superuser=False, is_active=True)
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def admin_token(test_admin: User):
    """Генерирует токен для админа."""
    return create_tokens(data={"sub": test_admin.phone, "id": test_admin.id, "role": "admin"})


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(settings.redis.url, decode_responses=True)
    yield client
    await client.aclose()
