import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import settings
from app.infra.db import Base
from app.models.admin_log import AdminLog
from app.models.onboarding import OnboardingApplication
from app.models.user import User
from app.models.user_profiles import SupplierProfile, TripGuideProfile

MODELS = (User, OnboardingApplication, AdminLog, SupplierProfile, TripGuideProfile)

target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Это поможет избежать проблем с именованием индексов
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """Создаем движок напрямую из твоего async_url"""
    connectable = create_async_engine(
        settings.db.async_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_offline():
    """Для генерации SQL-логов без подключения к базе"""
    context.configure(
        url=str(settings.db.async_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
