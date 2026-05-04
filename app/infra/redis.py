from redis.asyncio import Redis, from_url

from app.config.settings import settings

# Создаем пул один раз
redis_pool: Redis = from_url(
    settings.redis.url,
    decode_responses=True,
    max_connections=settings.redis.max_connections,
    socket_timeout=settings.redis.socket_timeout,
    socket_connect_timeout=settings.redis.connect_timeout,
    retry_on_timeout=settings.redis.retry_on_timeout,
)


async def get_redis_client() -> Redis:
    return redis_pool
