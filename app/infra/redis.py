from typing import TYPE_CHECKING

from redis.asyncio import Redis, from_url

from app.config.settings import settings

# 1. Используем TYPE_CHECKING. Этот блок видит ТОЛЬКО MyPy.
if TYPE_CHECKING:
    RedisClient = Redis[str]
else:
    # Этот блок видит Python при запуске приложения и тестов.
    RedisClient = Redis

# 2. Теперь используем наш "умный" псевдоним
redis_pool: RedisClient = from_url(
    settings.redis.url,
    decode_responses=True,
    max_connections=settings.redis.max_connections,
    socket_timeout=settings.redis.socket_timeout,
    socket_connect_timeout=settings.redis.connect_timeout,
    retry_on_timeout=settings.redis.retry_on_timeout,
)


# 3. FastAPI увидит чистый Redis и не упадет, а MyPy увидит Redis[str]
async def get_redis_client() -> RedisClient:
    return redis_pool


# from __future__ import annotations

# from redis.asyncio import Redis, from_url

# from app.config.settings import settings

# redis_pool: Redis[str] = from_url(
#     settings.redis.url,
#     decode_responses=True,
#     max_connections=settings.redis.max_connections,
#     socket_timeout=settings.redis.socket_timeout,
#     socket_connect_timeout=settings.redis.connect_timeout,
#     retry_on_timeout=settings.redis.retry_on_timeout,
# )


# async def get_redis_client() -> Redis[str]:
#     return redis_pool
