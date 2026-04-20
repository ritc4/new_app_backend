import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete

from app.config.settings import settings
from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.infra.httpx_client import httpx_client
from app.models.user import User

logger = logging.getLogger(__name__)


@celery_app.task(name="send_flash_call", bind=True, max_retries=3, rate_limit="10/m")
def send_flash_call_task(self, phone: str, code: str):
    """Задача для звонка Flash Call через SigmaSMS по официальной схеме"""

    # Извлекаем данные из конфига
    url = settings.sigma.api_url
    token = settings.sigma.token.get_secret_value()
    sender = settings.sigma.sender.get_secret_value()

    # Формируем тело запроса по документации SigmaSMS
    payload = {
        "recipient": phone,
        "type": "flashcall",
        "payload": {
            "sender": sender,  # Внутреннее имя отправителя
            "text": code,  # Код (последние 4 цифры) 
        },
    }

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    try:
        # Используем Singleton-клиент. Передаем url позиционно.
        response = httpx_client.post(url, json=payload, headers=headers)

        # ВАЖНО: выбрасываем исключение, если статус не 2xx
        response.raise_for_status()

        logger.info(f"Flash Call успешно заказан через SigmaSMS на номер {phone}")
        return {"status": "success", "phone": phone}

    except httpx.HTTPStatusError as exc:
        # Ошибки уровня API (4xx, 5xx)
        status_code = exc.response.status_code

        # Если ошибка на стороне Sigma (5xx) — пробуем еще раз
        if status_code >= 500:
            logger.warning(
                f"SigmaSMS временно недоступен (Status: {status_code}). Ретрай..."
            )
            raise self.retry(exc=exc, countdown=30) from exc

        # Если 4xx (ошибка данных, баланса или токена) — логируем и прекращаем
        logger.error(f"Ошибка SigmaSMS API {status_code}: {exc.response.text}")
        raise exc

    except httpx.RequestError as exc:
        # Сетевые ошибки (таймаут, DNS, разрыв соединения)
        logger.warning(f"Сетевая ошибка при связи с SigmaSMS: {exc}. Ретрай...")
        raise self.retry(exc=exc, countdown=15) from exc
    except Exception as exc:
        # Непредвиденные ошибки
        logger.error(f"Критическая ошибка в задаче Flash Call: {exc}")
        raise exc


@celery_app.task(name="cleanup_inactive_users_task", max_retries=3)
def cleanup_inactive_users_task():
    """Периодическая задача: очистка неактивных пользователей."""
    return asyncio.run(delete_old_users())


async def delete_old_users():
    """Удаляем тех, кто не заходил 180 дней и не завершил регистрацию."""
    async with async_session_maker() as session:
        threshold = datetime.now(UTC) - timedelta(days=180)

        stmt = delete(User).where(
            User.last_active < threshold,
            User.first_name.is_(None),
            User.is_admin.is_(False),
            User.is_banned.is_(False),
        )

        try:
            result = await session.execute(stmt)
            await session.commit()
            count = result.rowcount
            logger.info(f"Очистка завершена: удалено {count} неактивных пользователей.")
            return f"Удалено пользователей: {count}"
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при очистке пользователей: {e}")
            raise
