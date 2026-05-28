import asyncio
import logging

from celery import Task

from app.core.dependencies.s3 import get_s3_service
from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.infra.redis import redis_pool
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


@celery_app.task(name="cleanup_inactive_users_task", base=Task)
def cleanup_inactive_users_task() -> str | None:
    """Периодический ночной крон для поиска и удаления просроченных аккаунтов."""
    try:
        report = asyncio.run(run_cleanup())
        logger.info(f"ЕЖЕДНЕВНАЯ_ОЧИСТКА_ЗАВЕРШЕНА: {report}")
        return report
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ_ОШИБКА_ОЧИСТКИ: {e}", exc_info=True)
        raise


async def run_cleanup() -> str:
    """Оркестратор очистки с единым стандартом внедрения репозиториев."""
    from app.repositories.excursion_repository import ExcursionRepository
    from app.repositories.onboarding_repository import OnboardingRepository
    from app.repositories.user_repository import UserRepository
    from app.services.user_service import UserService

    async with async_session_maker() as session:
        s3 = await get_s3_service()
        auth = AuthService(db=session, redis_client=redis_pool)

        # Инкапсулируем создание обоих репозиториев на слое оркестрации
        user_repo = UserRepository(db=session)
        excursion_repo = ExcursionRepository(db=session)
        onboarding_repo = OnboardingRepository(db=session)

        # Передаем все готовые кирпичики в конструктор сервиса
        user_service = UserService(
            db=session,
            s3=s3,
            auth_service=auth,
            user_repo=user_repo,
            excursion_repo=excursion_repo,
            onboarding_repo=onboarding_repo,
        )

        return await user_service.purge_abandoned_and_deleted_users()


@celery_app.task(name="delete_user_s3_resources_task", base=Task)
def delete_user_s3_resources_task(prefixes: list[str]) -> str:
    """Фоновая асинхронная зачистка всех S3 папок (префиксов) удаленного пользователя."""
    if not prefixes:
        return "Список префиксов пуст, удаление не требуется."
    try:
        deleted_count = asyncio.run(run_s3_prefixes_delete(prefixes))
        return f"Фоновый клининг S3 завершен. Физически удалено объектов: {deleted_count}"
    except Exception as e:
        logger.error(f"Ошибка Celery при фоновом удалении папок пользователя: {e}", exc_info=True)
        raise


async def run_s3_prefixes_delete(prefixes: list[str]) -> int:
    """Асинхронный коннектор к постраничному методу S3Service внутри воркера."""
    s3_service = await get_s3_service()

    total_deleted = 0
    for prefix in prefixes:
        # Пакетное удаление объектов внутри виртуальной директории (по 1000 шт. за раз)
        deleted_count = await s3_service.delete_directory_by_prefix(prefix)
        total_deleted += deleted_count

    return total_deleted
