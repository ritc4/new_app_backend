import asyncio
import logging

import httpx

from app.config.settings import settings
from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.infra.httpx_client import httpx_client
from app.infra.redis import redis_pool
from app.services.auth_service import AuthService
from app.services.s3_service import S3Service
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


@celery_app.task(name="send_flash_call", bind=True, max_retries=3, rate_limit="10/m")
def send_flash_call_task(self, phone: str, code: str):
    """Задача для звонка Flash Call (Чистый транспортный слой)."""

    # 1. Инкапсуляция формирования запроса
    url, headers, payload = _prepare_sigma_request(phone, code)

    try:
        response = httpx_client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        logger.info(f"Flash Call успешно заказан на номер {phone}")
        return {"status": "success"}

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise self.retry(exc=exc, countdown=30) from exc
        logger.error(f"SigmaSMS API Error {exc.response.status_code}: {exc.response.text}")
        raise exc
    except httpx.RequestError as exc:
        raise self.retry(exc=exc, countdown=15) from exc


def _prepare_sigma_request(phone: str, code: str):
    """Приватный метод для сборки данных провайдера (Clean Code)."""
    return (
        settings.sigma.api_url,
        {"Authorization": settings.sigma.token.get_secret_value(), "Content-Type": "application/json"},
        {
            "recipient": phone,
            "type": "flashcall",
            "payload": {
                "sender": settings.sigma.sender.get_secret_value(),
                "text": code,
            },
        },
    )


@celery_app.task(name="cleanup_inactive_users_task")
def cleanup_inactive_users_task():
    """Периодическая задача: делегирует работу сервису."""
    return asyncio.run(run_cleanup())


async def run_cleanup():
    """Оркестратор очистки (Clean Architecture)."""
    async with async_session_maker() as session:
        # Инициализируем зависимости
        s3 = S3Service()
        auth = AuthService(db=session, redis_client=redis_pool)
        user_service = UserService(db=session, s3=s3, auth_service=auth)

        # Вызываем один высокоуровневый метод сервиса
        # Вся логика фильтров и параллельной очистки теперь внутри UserService
        return await user_service.perform_full_cleanup()
