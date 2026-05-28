from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies.transfer import get_transfer_service
from app.core.dependencies.user import get_current_supplier
from app.models.user import User
from app.schemas.base import ActionResponse
from app.schemas.transfers import AcceptOrderResponse, AvailableOrderResponse
from app.services.transfer_service import TransferService

router = APIRouter()

TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]
SuplierDep = Annotated[User, Depends(get_current_supplier)]


@router.get(
    "/available-orders", response_model=list[AvailableOrderResponse], summary="Посмотреть доступные трансферы (Биржа)"
)
async def list_available_orders(
    current_driver: SuplierDep, service: TransferServiceDep
) -> list[AvailableOrderResponse]:
    """Возвращает список оплаченных заказов, доступных для взятия в регионе водителя."""
    return await service.get_available_orders_for_driver(current_driver)


@router.patch(
    "/orders/{order_id}/accept", response_model=AcceptOrderResponse, summary="Нажать кнопку 'Принять трансфер'"
)
async def accept_order(order_id: int, current_driver: SuplierDep, service: TransferServiceDep) -> AcceptOrderResponse:
    """Атомарно закрепляет заказ за водителем. Защищено от Race Condition."""
    return await service.accept_order_by_driver(order_id=order_id, driver=current_driver)


@router.patch("/orders/{order_id}/cancel", response_model=ActionResponse, summary="Отменить принятый трансфер")
async def cancel_accepted_transfer(
    order_id: int, current_driver: SuplierDep, service: TransferServiceDep
) -> ActionResponse:
    """Тонкий эндпоинт отмены: принимает запрос и сразу делегирует его сервису."""
    return await service.cancel_order_by_driver(order_id=order_id, driver=current_driver)
