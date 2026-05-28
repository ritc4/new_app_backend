from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db_depends import get_db
from app.services.review_service import ReviewService


async def get_review_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ReviewService:
    return ReviewService(db=db)
