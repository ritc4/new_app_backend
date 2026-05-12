from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth import get_auth_service
from app.infra.db_depends import get_db
from app.repositories.admin_log_repository import AdminLogRepository
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService


async def get_admin_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AdminService:
    # 1. Создаем репозитории на основе текущей сессии БД
    user_repo = UserRepository(db)
    log_repo = AdminLogRepository(db)
    onboarding_repo = OnboardingRepository(db)

    # 2. Передаем всё в конструктор сервиса (Инъекция зависимостей)
    return AdminService(
        db=db,
        auth_service=auth_service,
        onboarding_repo=onboarding_repo,
        user_repo=user_repo,
        log_repo=log_repo,
    )
