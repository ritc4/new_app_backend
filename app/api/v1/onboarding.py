from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies.onboarding import get_onboarding_service
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.onboarding import OnboardingStart
from app.services.onboarding_service import OnboardingService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_user)]
OnboardingServiceDep = Annotated[OnboardingService, Depends(get_onboarding_service)]


@router.post("/start", summary="Начать процесс регистрации")
async def start_onboarding(data: OnboardingStart, user: CurrentUserDep, service: OnboardingServiceDep):
    # Возвращает ссылку в банк
    return await service.create_application(user.id, data)


@router.post("/webhook/bank", summary="Вебхук от банка")
async def t_bank_webhook(data: dict, service: OnboardingServiceDep):
    # Этот эндпоинт вызывает БАНК, а не юзер
    return await service.process_bank_webhook(data)


@router.get("/upload-link", summary="Получить ссылку для загрузки")
async def get_onboarding_link(
    type: str,
    content_type: str,
    user: CurrentUserDep,
    service: OnboardingServiceDep,
):
    return await service.get_onboarding_upload_url(user.id, type, content_type)


@router.post("/submit-survey", summary="Отправить анкету")
async def submit_survey(data: dict, user: CurrentUserDep, service: OnboardingServiceDep):
    # Вызывается из Flutter после возвращения из банка
    return await service.submit_survey(user.id, data)
