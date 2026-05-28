from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies.onboarding import get_onboarding_service
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.onboarding import (
    BankWebhookPayload,
    BankWebhookPayloadResponse,
    CancelCurrentApplicationResponse,
    GlobalLanguageResponse,
    OnboardingCountryPickerResponse,
    OnboardingDraftResponse,
    OnboardingFileType,
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
    file_type: Annotated[OnboardingFileType, Query(description="Тип документа (photo_selfie, и т.д.)")],
    content_type: Annotated[str, Query(description="MIME-тип (image/jpeg, image/png)")],
) -> OnboardingUploadResponse:
    return await service.get_onboarding_upload_url(
        user.id, user_uuid=str(user.uuid), file_type=file_type.value, content_type=content_type
    )


@router.get(
    "/guide-languages",
    response_model=list[GlobalLanguageResponse],
    summary="[Справочник] Список языков мира для анкеты гида (Яндекс-стайл)",
    description="Вызывается Flutter перед открытием экрана анкеты. "
    "Язык текущего пользователя автоматически встанет на позицию №1 в блоке популярных.",
)
async def get_guide_languages(
    service: OnboardingServiceDep,
    user: CurrentUserDep,  # Автоматический разбор JWT-токена пользователя
) -> Sequence[GlobalLanguageResponse]:
    # Прокидываем пользователя напрямую в бизнес-логику
    return await service.get_all_world_languages(client_user=user)


@router.get(
    "/countries",
    response_model=list[OnboardingCountryPickerResponse],
    summary="[Справочник] Список стран для выбора в анкете водителя",
    description="Вызывается Flutter при отрисовке экрана документов водителя для Dropdown-выбора страны прав.",
)
async def get_allowed_countries_for_picker(
    service: OnboardingServiceDep,
    user: CurrentUserDep,
) -> Sequence[OnboardingCountryPickerResponse]:
    return await service.get_allowed_countries_for_picker(client_user=user)


@router.post("/submit-survey", summary="Отправить анкету", response_model=SubmitSurveyResponse)
async def submit_survey(
    # Теперь в Swagger будет выбор между анкетой водителя и гида
    data: SupplierSurvey | TripguideSurvey,
    user: CurrentUserDep,
    service: OnboardingServiceDep,
) -> SubmitSurveyResponse:
    return await service.submit_survey(user.id, data.model_dump())


@router.get("/draft", summary="Получить текущий черновик онбординга", response_model=OnboardingDraftResponse)
async def get_onboarding_draft(
    user: CurrentUserDep,  # Зависимость, достающая юзера из JWT-токена
    service: OnboardingServiceDep,  # Наш инжект OnboardingService
) -> OnboardingDraftResponse:
    return await service.get_current_draft(user.id)


@router.delete("/cancel", summary="Отменить текущую заявку", response_model=CancelCurrentApplicationResponse)
async def cancel_onboarding(user: CurrentUserDep, service: OnboardingServiceDep) -> CancelCurrentApplicationResponse:
    return await service.cancel_current_application(user.id)
