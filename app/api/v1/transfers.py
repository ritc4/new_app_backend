from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies.transfer import get_transfer_service
from app.core.dependencies.user import get_current_customer
from app.models.user import User
from app.schemas.transfers import (
    CreateOrderHighloadResponse,
    HubResponse,
    PaymentStatusResponse,
    RouteCalculateResponse,
    TransferOrderCreateRequest,
)
from app.services.transfer_service import TransferService

router = APIRouter()

TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]
CustomerDep = Annotated[User, Depends(get_current_customer)]


@router.get("/hubs/search", response_model=list[HubResponse], summary="1. Поиск хабов (Ввод Откуда/Куда)")
async def search_hubs(service: TransferServiceDep, query: str = Query(..., min_length=2)) -> list[HubResponse]:
    return await service.search_location_hubs(query)


@router.get(
    "/routes/calculate", response_model=RouteCalculateResponse, summary="2. Калькуляция цен и выбор класса авто"
)
async def calculate_route(
    service: TransferServiceDep, from_hub_id: int = Query(...), to_hub_id: int = Query(...)
) -> RouteCalculateResponse:
    return await service.calculate_price(from_hub_id, to_hub_id)


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    summary="Оформить заказ (Highload Celery версия)",
    response_model=CreateOrderHighloadResponse,
)
async def create_order(
    data: TransferOrderCreateRequest,
    current_user: CustomerDep,
    service: TransferServiceDep,
    provider: str = Query("tbank", description="Платежный провайдер: tbank или sberbank"),
) -> CreateOrderHighloadResponse:
    """Инициализирует создание заказа и делегирует генерацию ссылки фоновому воркеру."""
    return await service.process_highload_order_creation(user_id=current_user.id, data=data, provider=provider)


@router.get(
    "/orders/{order_id}/payment-status",
    summary="Опрос готовности ссылки из Redis",
    response_model=PaymentStatusResponse,
)
async def check_payment_url_ready(order_id: int, service: TransferServiceDep) -> PaymentStatusResponse:
    """Опрашивает статус готовности платежной ссылки через сервисный слой."""
    return await service.check_order_payment_status(order_id)
