import asyncio
import logging

from celery import Task

from app.core.dependencies.s3 import get_s3_service
from app.infra.celery_app import celery_app
from app.infra.db import async_session_maker
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.services.onboarding_service import OnboardingService

logger = logging.getLogger(__name__)


@celery_app.task(name="cleanup_expired_onboarding_task", base=Task)
def cleanup_expired_onboarding_task() -> str:  # ИСПРАВЛЕНО: убрали | None для MyPy
    """Фоновая задача Celery для удаления просроченного онбординга и его S3-файлов."""
    try:
        report = asyncio.run(run_onboarding_cleanup())
        logger.info(f"НОЧНАЯ_ОЧИСТКА_ОНБОРДИНГА_ЗАВЕРШЕНА: {report}")
        return report
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ_ОШИБКА_ОЧИСТКИ_ОНБОРДИНГА: {e}", exc_info=True)
        raise


async def run_onboarding_cleanup() -> str:
    """Оркестратор очистки домена онбординга."""
    async with async_session_maker() as session:
        s3 = await get_s3_service()

        # 1. Инициализируем репозитории, передавая им сессию БД
        user_repo = UserRepository(session)
        onboarding_repo = OnboardingRepository(session)

        # 2. Передаем ВСЕ требуемые зависимости в конструктор OnboardingService
        onboarding_service = OnboardingService(db=session, s3=s3, user_repo=user_repo, onboarding_repo=onboarding_repo)
        return await onboarding_service.purge_expired_onboarding_applications()
