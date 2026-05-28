from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db_depends import get_db
from app.services.payment_service import PaymentService


async def get_payment_service(db: Annotated[AsyncSession, Depends(get_db)]) -> PaymentService:
    """Глобальная фабрика для биллинг-системы."""
    return PaymentService(db=db)
