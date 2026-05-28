from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db_depends import get_db
from app.services.transfer_service import TransferService


async def get_transfer_service(db: Annotated[AsyncSession, Depends(get_db)]) -> TransferService:
    """Промышленная фабрика зависимостей для сервиса трансферов."""
    return TransferService(db=db)
