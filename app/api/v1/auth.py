from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.dependencies.auth import get_auth_service

# from app.core.security import get_session_info
from app.core.jwt import get_session_info
from app.schemas.auth import (
    ActionResponse,
    AppConfigResponse,
    OTPRequest,
    OTPVerifyRequest,
    RefreshRequest,
    TokenPairResponse,
)
from app.services.auth_service import AuthService

router = APIRouter()

# ТИПИЗАЦИЯ ЗАВИСИМОСТИ: Чтобы не писать Annotated в каждом методе
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.get(
    "/config",
    summary="Конфигурация мобильного приложения",
    description="Возвращает актуальные версии и ссылки",
    response_model=AppConfigResponse,
)
async def get_app_config(service: AuthServiceDep):
    # Теперь даже конфиг может отдавать сервис, чтобы в роутере не было логики settings
    return await service.get_app_config()


@router.post(
    "/request-otp",
    summary="Запрос кода подтверждения",
    description="Инициирует Flash Call на указанный номер телефона",
    response_model=ActionResponse,
)
async def request_otp(payload: OTPRequest, request: Request, service: AuthServiceDep):
    _, ip = get_session_info(request)
    return await service.request_otp(payload.phone, ip)


@router.post(
    "/verify-otp",
    summary="Проверка кода и вход",
    description="Обменивает OTP код на пару Access/Refresh токенов",
    response_model=TokenPairResponse,
)
async def verify_otp(payload: OTPVerifyRequest, request: Request, service: AuthServiceDep):
    # Сервис сам проверит код и выполнит логин, вернув готовый TokenPairResponse
    return await service.verify_otp_and_login(payload, request)


@router.post(
    "/refresh",
    summary="Обновление сессии",
    description="Выдает новый Access токен по валидному Refresh токену",
    response_model=TokenPairResponse,
)
async def refresh_access_token(payload: RefreshRequest, request: Request, service: AuthServiceDep):
    return await service.refresh_tokens(payload.refresh_token, request)
