from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies.excursion import get_excursion_service
from app.core.dependencies.user import get_current_customer, get_current_guide
from app.models.user import User
from app.schemas.excursions import (
    BookExcursionRequest,
    ExcursionResponse,
    ExcursionSlotResponse,
)
from app.schemas.transfers import CreateOrderHighloadResponse
from app.services.excursion_service import ExcursionService

router = APIRouter()

ExcursionServiceDep = Annotated[ExcursionService, Depends(get_excursion_service)]
CustomerDep = Annotated[User, Depends(get_current_customer)]
GuideDep = Annotated[User, Depends(get_current_guide)]


@router.get("/search", response_model=list[ExcursionResponse], summary="1. Поиск экскурсий в регионе для туриста")
async def list_excursions(
    service: ExcursionServiceDep,
    region_id: int = Query(..., description="ID курортного региона деятельности"),
) -> list[ExcursionResponse]:
    """Возвращает список проверенных модераторами экскурсий для витрины Flutter."""
    return await service.get_excursions_in_region(region_id)


@router.get(
    "/{excursion_id}/slots",
    response_model=list[ExcursionSlotResponse],
    summary="3. Посмотреть календарь доступных дат экскурсии (Для туриста)",
)
async def list_excursion_slots(excursion_id: int, service: ExcursionServiceDep) -> list[ExcursionSlotResponse]:
    """Возвращает календарную сетку будущих выездов со свободными местами."""
    return await service.get_active_slots_for_tourist(excursion_id)


@router.post(
    "/slots/book",
    response_model=CreateOrderHighloadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="5. Забронировать места на экскурсию (Highload Celery версия)",
)
async def book_excursion(
    data: BookExcursionRequest,
    current_user: CustomerDep,
    service: ExcursionServiceDep,
    provider: str = Query("tbank", description="Платежный провайдер: tbank или sberbank"),
) -> CreateOrderHighloadResponse:
    """Атомарно резервирует места в СУБД за 2мс и ставит задачу генерации ссылки в Celery."""
    return await service.process_highload_excursion_booking(user_id=current_user.id, data=data, provider=provider)
