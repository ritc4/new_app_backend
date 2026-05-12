import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import v1_router
from app.config.settings import settings
from app.core.openapi import tags_metadata
from app.infra.db import engine
from app.infra.redis import redis_pool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    # --- STARTUP (Действия при старте) ---
    logger.info("Application is starting up...")

    yield

    # --- SHUTDOWN (Мягкое завершение) ---
    logger.info("Application is shutting down gracefully...")

    # 1. Закрываем Redis
    await redis_pool.close()
    logger.info("Redis connection pool closed.")

    # 3. Закрываем движок SQLAlchemy
    # Это дождется завершения текущих транзакций и закроет пул соединений с Postgres
    await engine.dispose()
    logger.info("Database engine disposed.")

    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app.title,
        description=settings.app.description,
        version=settings.app.version,
        openapi_tags=tags_metadata,
        lifespan=lifespan,
    )

    # Настройка CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.http.cors_origins,
        allow_credentials=settings.http.cors_allow_credentials,
        allow_methods=settings.http.cors_methods,
        allow_headers=settings.http.cors_headers,
    )
    app.include_router(v1_router, prefix=settings.app.api_v1_str)
    # Когда появится v2, ты просто добавишь:
    # app.include_router(v2_router, prefix=settings.app.api_v2_str)

    return app
