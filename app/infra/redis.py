from redis.asyncio import Redis, from_url

from app.config.settings import settings

# Создаем пул один раз
redis_pool: Redis = from_url(settings.redis.url, decode_responses=True)


async def get_redis_client() -> Redis:
    return redis_pool
