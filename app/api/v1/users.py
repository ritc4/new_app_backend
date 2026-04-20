import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies.auth import get_auth_service
from app.core.security import get_current_user
from app.schemas.auth import (
    CompleteRegistrationRequest,
    SessionInfo,
    UpdateUsernameRequest,
)
from app.schemas.user import UserShort
from app.services.auth_service import AuthService

# Логгер для слоя API пользователей
logger = logging.getLogger("app.api.users")
router = APIRouter()

# Алиасы типов для чистоты кода (Dependency Injection Aliases)
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
CurrentUserDep = Annotated[dict, Depends(get_current_user)]


@router.get(
    "/me",
    response_model=UserShort,
    summary="Получить мой профиль",
    description="Возвращает информацию о текущем авторизованном пользователе",
)
async def read_current_user(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    return await service.get_user_by_id(current_user["id"])


@router.patch(
    "/complete-registration",
    response_model=UserShort,
    summary="Завершить регистрацию",
    description="Установка имени и фамилии при первом входе",
)
async def complete_registration(
    data: CompleteRegistrationRequest,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    return await service.complete_registration(current_user["id"], data)


@router.patch(
    "/update-username",
    summary="Сменить никнейм",
    description="Обновляет уникальное имя пользователя в системе",
)
async def update_username(
    data: UpdateUsernameRequest,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    await service.update_username(current_user["id"], data.username)
    return {"status": "success", "username": data.username}


@router.get(
    "/sessions",
    response_model=list[SessionInfo],
    summary="Активные сессии",
    description="Список всех устройств, на которых выполнен вход",
)
async def list_sessions(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    sessions = await service.list_sessions(current_user)
    return [SessionInfo(**s) for s in sessions]


@router.post(
    "/logout",
    summary="Выйти из системы",
    description="Аннулирует текущую сессию (Refresh токен)",
)
async def logout(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    await service.logout(current_user)
    return {"status": "success"}


@router.post(
    "/logout-all",
    summary="Выйти со всех устройств",
    description="Сбрасывает абсолютно все активные сессии пользователя",
)
async def logout_all(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    await service.logout_all(current_user)
    return {"status": "success"}


@router.delete(
    "/delete-account",
    status_code=status.HTTP_200_OK,
    summary="Удалить аккаунт",
    description="Полное удаление профиля и всех связанных сессий",
)
async def delete_account(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    await service.delete_account(current_user)
    return {"message": "Удалено"}
