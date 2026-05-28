from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.s3 import get_s3_service
from app.infra.db_depends import get_db
from app.services.excursion_service import ExcursionService
from app.services.s3_service import S3Service


async def get_excursion_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    s3: Annotated[S3Service, Depends(get_s3_service)],
) -> ExcursionService:
    """Промышленная фабрика зависимостей для домена экскурсий с внедрением S3."""
    # Исправлено: передаем s3=s3
    return ExcursionService(db=db, s3=s3)
