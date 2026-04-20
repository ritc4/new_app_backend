import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.config.settings import settings
from app.core.dependencies.auth import get_auth_service
from app.core.security import get_session_info
from app.schemas.auth import (
    AppConfigResponse,
    OTPRequest,
    OTPVerifyRequest,
    RefreshRequest,
    TokenPairOnlyResponse,
    TokenPairResponse,
)
from app.services.auth_service import AuthService

# Создаем логгер для слоя API
logger = logging.getLogger("app.api.auth")

router = APIRouter()

# ТИПИЗАЦИЯ ЗАВИСИМОСТИ: Чтобы не писать Annotated в каждом методе
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.get(
    "/config",
    response_model=AppConfigResponse,
    summary="Конфигурация мобильного приложения",
    description="Возвращает актуальные версии и ссылки для FlutterFlow",
)
async def get_app_config():
    return AppConfigResponse(
        min_required_version=settings.app.min_app_version,
        latest_version=settings.app.version,
        contact_support="https://t.me",
        update_url="https://google.com",
    )


@router.post(
    "/request-otp",
    status_code=status.HTTP_200_OK,
    summary="Запрос кода подтверждения",
    description="Инициирует Flash Call на указанный номер телефона",
)
async def request_otp(
    payload: OTPRequest,
    request: Request,
    service: AuthServiceDep,
):
    _, ip = get_session_info(request)
    await service.request_otp(payload.phone, ip)
    # Используем статус-коды FastAPI для чистоты кода
    return {"status": "success", "message": "Звонок выполняется"}


@router.post(
    "/verify-otp",
    response_model=TokenPairResponse,
    summary="Проверка кода и вход",
    description="Обменивает OTP код на пару Access/Refresh токенов",
)
async def verify_otp(
    payload: OTPVerifyRequest,
    request: Request,
    service: AuthServiceDep,
):
    # Координируем действия через сервис (Controller logic)
    await service.verify_otp_code(payload.phone, payload.code)

    access, refresh, is_new = await service.login_or_register(
        phone=payload.phone,
        request=request,
    )

    return TokenPairResponse(
        access_token=access,
        refresh_token=refresh,
        is_new_user=is_new,
    )


@router.post(
    "/refresh",
    response_model=TokenPairOnlyResponse,
    summary="Обновление сессии",
    description="Выдает новый Access токен по валидному Refresh токену",
)
async def refresh_access_token(
    payload: RefreshRequest,
    request: Request,
    service: AuthServiceDep,
):
    access, refresh = await service.refresh_tokens(
        refresh_token=payload.refresh_token,
        request=request,
    )
    return TokenPairOnlyResponse(access_token=access, refresh_token=refresh)
