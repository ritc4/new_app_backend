from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies.onboarding import get_onboarding_service
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.onboarding import (
    BankWebhookPayload,
    BankWebhookPayloadResponse,
    CancelCurrentApplicationResponse,
    OnboardingLinkResponse,
    OnboardingStart,
    OnboardingUploadResponse,
    SubmitSurveyResponse,
    SupplierSurvey,
    TripguideSurvey,
)
from app.services.onboarding_service import OnboardingService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_user)]
OnboardingServiceDep = Annotated[OnboardingService, Depends(get_onboarding_service)]


@router.post("/start", summary="Начать процесс регистрации", response_model=OnboardingLinkResponse)
async def start_onboarding(
    data: OnboardingStart,
    user: CurrentUserDep,
    service: OnboardingServiceDep,
) -> OnboardingLinkResponse:
    # Возвращает ссылку в банк
    return await service.create_application(user.id, data)


@router.post("/webhook/bank", summary="Вебхук от банка", response_model=BankWebhookPayloadResponse)
async def t_bank_webhook(
    payload: BankWebhookPayload,
    service: OnboardingServiceDep,
) -> BankWebhookPayloadResponse:
    return await service.process_bank_webhook(payload)


@router.get("/upload-link", summary="Получить ссылку для загрузки", response_model=OnboardingUploadResponse)
async def get_onboarding_link(
    user: CurrentUserDep,
    service: OnboardingServiceDep,
    file_type: Annotated[str, Query(description="Тип документа (photo_selfie, и т.д.)")],
    content_type: Annotated[str, Query(description="MIME-тип (image/jpeg, image/png)")],
) -> OnboardingUploadResponse:
    return await service.get_onboarding_upload_url(user.id, file_type, content_type)


@router.post("/submit-survey", summary="Отправить анкету", response_model=SubmitSurveyResponse)
async def submit_survey(
    # Теперь в Swagger будет выбор между анкетой водителя и гида
    data: SupplierSurvey | TripguideSurvey,
    user: CurrentUserDep,
    service: OnboardingServiceDep,
) -> SubmitSurveyResponse:
    return await service.submit_survey(user.id, data.model_dump())


@router.delete("/cancel", summary="Отменить текущую заявку", response_model=CancelCurrentApplicationResponse)
async def cancel_onboarding(user: CurrentUserDep, service: OnboardingServiceDep) -> CancelCurrentApplicationResponse:
    return await service.cancel_current_application(user.id)
