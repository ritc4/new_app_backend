from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db_depends import get_db
from app.infra.redis import get_redis_client
from app.services.auth_service import AuthService


async def get_auth_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> AuthService:
    return AuthService(db=db, redis_client=redis_client) 
