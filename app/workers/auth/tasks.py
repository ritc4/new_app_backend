import logging

import requests

from app.config.settings import settings
from app.infra.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="send_flash_call", bind=True, max_retries=3, rate_limit="10/m")
def send_flash_call_task(self, phone: str, code: str):
    """Задача для звонка Flash Call на requests (Синхронно и надежно)."""

    url, headers, payload = _prepare_sigma_request(phone, code)

    try:
        # requests.post сам управляет соединением, не создавая проблем для Event Loop
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        # Генерирует исключение для кодов 4xx и 500
        response.raise_for_status()

        logger.info(f"Flash Call успешно заказан на номер {phone}")
        return {"status": "success"}

    except requests.exceptions.HTTPError as exc:
        # Если ошибка на стороне сервера (5xx), пробуем еще раз
        if exc.response.status_code >= 500:
            raise self.retry(exc=exc, countdown=30) from exc
        logger.error(f"SigmaSMS API Error {exc.response.status_code}: {exc.response.text}")
        raise
    except requests.exceptions.RequestException as exc:
        # Сетевые ошибки (таймауты и т.д.) — ретрай через 15 сек
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
