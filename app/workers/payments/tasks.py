import asyncio
import logging

from celery import Task

from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


@celery_app.task(name="process_bank_refund_task", base=Task)
def process_bank_refund_task(order_id: int) -> str:
    """Фоновый Celery-таск для отправки HTTP-команд отмены холда в Т-Банк / Сбербанк."""
    try:
        status_str = asyncio.run(run_bank_refund(order_id=order_id))
        return f"Refund выполнен для заказа {order_id}: {status_str}"
    except Exception as e:
        logger.error(f"Критический сбой API возврата Celery для заказа {order_id}: {e}", exc_info=True)
        raise


async def run_bank_refund(order_id: int) -> str:
    async with async_session_maker() as session:
        payment_service = PaymentService(db=session)
        return await payment_service.execute_bank_api_refund(order_id=order_id)
