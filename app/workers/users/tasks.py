import asyncio
import logging

from app.core.dependencies.s3 import get_s3_service
from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.infra.redis import redis_pool
from app.services.auth_service import AuthService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


@celery_app.task(name="cleanup_inactive_users_task")
def cleanup_inactive_users_task():
    try:
        report = asyncio.run(run_cleanup())
        logger.info(f"ЕЖЕДНЕВНАЯ_ОЧИСТКА_ЗАВЕРШЕНА: {report}")
        return report
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ_ОШИБКА_ОЧИСТКИ: {e}", exc_info=True)
        raise


async def run_cleanup():
    """Оркестратор очистки (Clean Architecture)."""
    async with async_session_maker() as session:
        # Инициализируем зависимости
        s3 = await get_s3_service()
        auth = AuthService(db=session, redis_client=redis_pool)
        user_service = UserService(db=session, s3=s3, auth_service=auth)

        # Вызываем один высокоуровневый метод сервиса
        # Вся логика фильтров и параллельной очистки теперь внутри UserService
        return await user_service.perform_full_cleanup()
