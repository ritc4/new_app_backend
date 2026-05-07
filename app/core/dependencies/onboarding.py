from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.s3 import get_s3_service
from app.infra.db_depends import get_db
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.services.onboarding_service import OnboardingService
from app.services.s3_service import S3Service


async def get_onboarding_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    s3: Annotated[S3Service, Depends(get_s3_service)],  # FastAPI сам дождется async и вернет инстанс
) -> OnboardingService:
    user_repo = UserRepository(db)
    onboarding_repo = OnboardingRepository(db)

    return OnboardingService(
        db=db,
        s3=s3,  # Используем уже созданный Singleton
        user_repo=user_repo,
        onboarding_repo=onboarding_repo,
    )
