from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth import get_auth_service
from app.core.dependencies.s3 import get_s3_service
from app.core.security import get_current_user
from app.infra.db_depends import get_db
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.s3_service import S3Service
from app.services.user_service import UserService


async def get_user_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    s3_service: Annotated[S3Service, Depends(get_s3_service)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserService:
    return UserService(db=db, s3=s3_service, auth_service=auth_service) 


async def get_current_worker(user: Annotated[User, Depends(get_current_user)]) -> User:
    """
    Проверяет, является ли пользователь персоналом (гид, водитель) или администратором.
    Уровень 20+ включает в себя: supplier(20), trip_guide(20), admin(50), superuser(100).
    """
    if user.level < 20:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешен только для персонала и администраторов",
        )
    return user
