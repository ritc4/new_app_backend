import random
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.core.jwt import create_tokens

# Импортируем МОДУЛИ инфраструктуры для прямого патчинга переменных
from app.infra import db as db_module
from app.infra import redis as redis_module
from app.models.onboarding import OnboardingApplication
from app.models.user import User


@pytest_asyncio.fixture
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Создает тестовый движок БД."""
    engine = create_async_engine(settings.db.async_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    """Создает тестовый клиент Redis."""
    client: Redis = Redis.from_url(settings.redis.url, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def patch_infra(test_engine: AsyncEngine, redis_client: Redis) -> AsyncGenerator[None, None]:
    """
    ГЛАВНЫЙ ФИКС: Подменяет глобальные объекты в модулях infra.
    Теперь всё приложение будет использовать тестовые пулы в правильном цикле.
    """
    # Сохраняем оригиналы
    old_engine = getattr(db_module, "engine", None)
    old_session_maker = getattr(db_module, "async_session_maker", None)
    old_redis_pool = getattr(redis_module, "redis_pool", None)

    # Принудительно подменяем переменные в модулях
    db_module.engine = test_engine
    db_module.async_session_maker = async_sessionmaker(bind=test_engine, expire_on_commit=False, class_=AsyncSession)
    redis_module.redis_pool = redis_client

    yield

    # Восстанавливаем после тестов
    db_module.engine = old_engine
    db_module.async_session_maker = old_session_maker
    redis_module.redis_pool = old_redis_pool


@pytest_asyncio.fixture(autouse=True)
async def override_dependencies(db_session: AsyncSession, redis_client: Redis) -> AsyncGenerator[None, None]:
    """Подменяет зависимости FastAPI."""
    # Локальный импорт, чтобы app не инициализировался раньше патчинга
    from app.infra.db_depends import get_db
    from app.infra.redis import get_redis_client
    from app.main import app

    async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _get_test_redis() -> Redis:
        return redis_client

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_redis_client] = _get_test_redis
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Фикстура для работы с БД в тестах."""
    async with test_engine.begin() as conn:
        await conn.execute(OnboardingApplication.__table__.delete())
        await conn.execute(User.__table__.delete())

    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Тестовый клиент API."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    random_phone = f"+7962{random.randint(1000000, 9999999)}"
    user = User(phone=random_phone, first_name="Иван", role="customer", is_active=True)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession) -> User:
    random_admin_phone = f"+7000{random.randint(1000000, 9999999)}"
    admin = User(phone=random_admin_phone, first_name="Admin", role="admin", is_active=True)
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def user_token(test_user: User, redis_client: Redis) -> str:
    access, _ = await create_tokens(user=test_user, device_info="pytest", ip_address="127.0.0.1", r=redis_client)
    return access


@pytest_asyncio.fixture
async def admin_token(test_admin: User, redis_client: Redis) -> str:
    access, _ = await create_tokens(user=test_admin, device_info="pytest", ip_address="127.0.0.1", r=redis_client)
    return access
