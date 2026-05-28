import asyncio
import logging

from celery import Task

from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.infra.redis import redis_pool

logger = logging.getLogger(__name__)


@celery_app.task(name="generate_payment_link_task", base=Task)
def generate_payment_link_task(
    user_id: int, route_id: int, car_class: str, execution_at_iso: str, provider: str, order_id: int
) -> str:
    """Фоновая задача генерации ссылки с сохранением в Redis пуле."""
    try:
        asyncio.run(
            run_payment_generation(
                user_id=user_id,
                route_id=route_id,
                car_class=car_class,
                execution_at_iso=execution_at_iso,
                provider=provider,
                order_id=order_id,
            )
        )
        return f"Ссылка успешно сгенерирована для заказа {order_id}"
    except Exception as e:
        logger.error(f"Сбой фоновой генерации ссылки для заказа {order_id}: {e}", exc_info=True)
        raise


async def run_payment_generation(
    user_id: int, route_id: int, car_class: str, execution_at_iso: str, provider: str, order_id: int
) -> str:
    from datetime import datetime

    from app.models.spatial import CarClass
    from app.schemas.transfers import TransferOrderCreateRequest
    from app.services.transfer_service import TransferService

    exec_at = datetime.fromisoformat(execution_at_iso)
    async with async_session_maker() as session:
        transfer_service = TransferService(db=session)
        data_request = TransferOrderCreateRequest(
            route_id=route_id, car_class=CarClass(car_class), execution_at=exec_at
        )

        payment_url = await transfer_service.get_bank_url_for_existing_order(
            order_id=order_id, user_id=user_id, data=data_request, provider=provider
        )
        await redis_pool.setex(f"payment_url:{order_id}", 900, payment_url)
        return payment_url
