from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth import get_auth_service
from app.core.dependencies.s3 import get_s3_service
from app.core.security import get_current_user
from app.infra.db_depends import get_db
from app.models.user import User
from app.repositories.excursion_repository import ExcursionRepository
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.s3_service import S3Service
from app.services.user_service import UserService


async def get_user_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    s3_service: Annotated[S3Service, Depends(get_s3_service)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    # ИДЕАЛЬНО ДЛЯ FASTAPI: Фреймворк сам создаст ExcursionRepository, заглянув в его __init__ и передав туда db
) -> UserService:
    """Промышленная фабрика зависимостей для UserService с явным внедрением через DI."""
    # Создаем репозиторий пользователей на месте из сессии
    user_repo = UserRepository(db=db)
    excursion_repo = ExcursionRepository(db=db)
    onboarding_repo = OnboardingRepository(db=db)

    # Передаем абсолютно все зависимости снаружи через конструктор
    return UserService(
        db=db,
        s3=s3_service,
        auth_service=auth_service,
        user_repo=user_repo,
        excursion_repo=excursion_repo,
        onboarding_repo=onboarding_repo,
    )


async def get_current_worker(user: Annotated[User, Depends(get_current_user)]) -> User:
    """
    Разрешает доступ СТРОГО воркеру (уровень 20).
    Клиенты (10) и Админы (50+) получают отказ.
    """
    # Если уровень НЕ равен 20, значит это либо клиент, либо админ
    if user.level != 20:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Эта функция доступна только для водителей и гидов",
        )
    return user


async def get_current_supplier(user: Annotated[User, Depends(get_current_worker)]) -> User:
    """Разрешает доступ только исполнителям с ролью водителя (supplier)."""
    if user.role != "supplier":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Эта функция доступна только для водителей")
    return user


async def get_current_guide(user: Annotated[User, Depends(get_current_worker)]) -> User:
    """Разрешает доступ только исполнителям с ролью пешего гида (trip_guide)."""
    if user.role != "trip_guide":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Эта функция доступна только для гидов")
    return user


async def get_current_customer(user: Annotated[User, Depends(get_current_user)]) -> User:
    """
    Разрешает редактирование ФИО только обычным клиентам (level 10).
    Персонал (20+) и забаненные не проходят.
    """
    # Если уровень 20 и выше — это уже верифицированный персонал или админ
    if user.level >= 20:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Верифицированные данные профиля можно изменить только через поддержку",
        )

    # Дополнительная страховка: если уровень меньше 10 (например, 0),
    # возможно, это гость или неактивный юзер
    if user.level < 10:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ ограничен",
        )

    return user
