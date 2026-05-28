from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies.excursion import get_excursion_service
from app.core.dependencies.user import get_current_customer, get_current_guide
from app.models.user import User
from app.schemas.excursions import (
    ExcursionCreateRequest,
    ExcursionResponse,
    ExcursionSlotCreateRequest,
    ExcursionSlotResponse,
)
from app.schemas.s3 import S3UploadResult
from app.schemas.transfers import CreateOrderHighloadResponse
from app.services.excursion_service import ExcursionService

router = APIRouter()

ExcursionServiceDep = Annotated[ExcursionService, Depends(get_excursion_service)]
CustomerDep = Annotated[User, Depends(get_current_customer)]
GuideDep = Annotated[User, Depends(get_current_guide)]


@router.post(
    "/guide/my-excursions",
    response_model=ExcursionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="2. Добавить новую экскурсию (Кабинет гида)",
)
async def create_excursion(
    data: ExcursionCreateRequest,
    current_guide: GuideDep,
    service: ExcursionServiceDep,
) -> ExcursionResponse:
    """Позволяет верифицированному гиду опубликовать свою авторскую программу."""
    return await service.create_new_excursion_by_guide(guide=current_guide, data=data)


@router.post(
    "/guide/slots",
    response_model=ExcursionSlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="4. Открыть новую дату выезда (Кабинет гида)",
)
async def create_calendar_slot(
    data: ExcursionSlotCreateRequest,
    current_guide: GuideDep,
    service: ExcursionServiceDep,
) -> ExcursionSlotResponse:
    """Позволяет гиду добавить в расписание новый день/время проведения экскурсии."""
    return await service.open_new_calendar_slot(guide=current_guide, data=data)


@router.patch(
    "/guide/orders/{order_id}/cancel",
    response_model=CreateOrderHighloadResponse,
    summary="6. Отменить забронированную экскурсию (Кабинет гида)",
)
async def cancel_excursion_order(
    order_id: int, current_guide: GuideDep, service: ExcursionServiceDep
) -> CreateOrderHighloadResponse:
    """Тонкий эндпоинт отмены экскурсии гидом: сразу делегирует задачу сервису."""
    return await service.cancel_order_by_guide(order_id=order_id, guide=current_guide)


@router.post(
    "/guide/my-excursions/{excursion_id}/presigned-gallery-upload",
    response_model=S3UploadResult,
    summary="8. Ссылка для безопасной загрузки/перезаписи фото в галерее (Кабинет гида)",
)
async def get_excursion_gallery_upload_url(
    current_guide: GuideDep,
    service: ExcursionServiceDep,
    excursion_id: int,
    position_index: int = Query(..., ge=0, le=9, description="Индекс позиции фото в карусели (0-9)"),
    content_type: str = Query(..., description="MIME-тип файла, например image/jpeg"),
) -> S3UploadResult:
    # Вызываем один объединенный метод сервиса
    return await service.get_excursion_photo_upload_params(
        guide=current_guide, excursion_id=excursion_id, position_index=position_index, content_type=content_type
    )

@router.delete(
    "/guide/my-excursions/{excursion_id}",
    response_model=CreateOrderHighloadResponse,
    summary="9. Полностью удалить авторскую экскурсию (Кабинет гида)",
)
async def delete_guide_excursion(
    excursion_id: int,
    current_guide: GuideDep,
    service: ExcursionServiceDep,
) -> CreateOrderHighloadResponse:
    """
    Полностью удаляет карточку экскурсии, её календарную сетку и связи из СУБД PostgreSQL.
    Тяжелая очистка физических бинарных файлов из S3-бакета улетает в фоновый воркер Celery.
    """
    return await service.delete_excursion_by_guide(guide=current_guide, excursion_id=excursion_id)
