import asyncio
import logging

from celery import Task

from app.core.dependencies.s3 import get_s3_service
from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.infra.redis import redis_pool

# ИСПРАВЛЕНО: Импортируем строго правильное имя схемы, которое ожидает сервис
from app.schemas.excursions import BookExcursionRequest
from app.services.excursion_service import ExcursionService

logger = logging.getLogger(__name__)


@celery_app.task(name="generate_excursion_payment_link_task", base=Task)
def generate_excursion_payment_link_task(
    user_id: int, slot_id: int, pax_count: int, provider: str, order_id: int
) -> str:
    """Фоновое холдирование денег в банке для бронирования экскурсии."""
    try:
        payment_url = asyncio.run(
            run_excursion_payment_generation(
                user_id=user_id, slot_id=slot_id, pax_count=pax_count, provider=provider, order_id=order_id
            )
        )
        return f"Ссылка успешно сгенерирована для заказа {order_id}: {payment_url}"
    except Exception as e:
        logger.error(f"Сбой генерации ссылки для экскурсии №{order_id}: {e}", exc_info=True)
        raise


async def run_excursion_payment_generation(
    user_id: int, slot_id: int, pax_count: int, provider: str, order_id: int
) -> str:
    """Оркестратор фонового обращения к банку (Clean Architecture)."""
    async with async_session_maker() as session:
        # ИСПРАВЛЕНО ДЛЯ MYPY: Получаем экземпляр S3Service
        s3_instance = await get_s3_service()

        # ИСПРАВЛЕНО ДЛЯ MYPY: Передаем s3 в конструктор ExcursionService
        excursion_service = ExcursionService(db=session, s3=s3_instance)

        # ИСПРАВЛЕНО ДЛЯ MATCHING С СЕРВИСОМ: Собираем строго BookExcursionRequest
        request_data = BookExcursionRequest(slot_id=slot_id, pax_count=pax_count)

        # Вызываем метод, передавая именованный аргумент data= (как определено в сервисе)
        payment_url = await excursion_service.get_bank_url_for_existing_excursion_order(
            order_id=order_id,
            user_id=user_id,
            data=request_data,  # Передаем объект схемы
            provider=provider,
        )

        # Кладем в Redis на 15 минут (900 секунд).
        await redis_pool.setex(f"payment_url:{order_id}", 900, payment_url)
        return payment_url
