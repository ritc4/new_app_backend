import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query

# Импортируем НОВЫЕ зависимости
from app.core.dependencies.auth import get_auth_service
from app.core.dependencies.user import get_current_worker, get_user_service
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.auth import (
    CompleteRegistrationRequest,
    SessionInfo,
    UpdateUsernameRequest,
)
from app.schemas.user import AvatarUploadResponse, UserShort
from app.services.auth_service import AuthService
from app.services.user_service import UserService

logger = logging.getLogger("app.api.users")
router = APIRouter()

# Обновленные алиасы типов
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
WorkerDep = Annotated[User, Depends(get_current_worker)]


@router.get(
    "/me",
    response_model=UserShort,
    summary="Получить мой профиль",
    description="Возвращает информацию о текущем авторизованном пользователе",
)
async def read_current_user(current_user: CurrentUserDep):
    return current_user


@router.patch(
    "/me/complete-registration",
    response_model=UserShort,
    summary="Завершить регистрацию",
    description="Установка имени и фамилии при первом входе",
)
async def complete_registration(
    data: CompleteRegistrationRequest,
    current_user: CurrentUserDep,
    service: UserServiceDep,  # Теперь используем UserService
):
    return await service.complete_registration(current_user.id, data)


@router.patch(
    "/me/update-username",
    response_model=UserShort,
    summary="Сменить никнейм",
    description="Обновляет уникальное имя пользователя в системе",
)
async def update_username(
    data: UpdateUsernameRequest,
    current_user: CurrentUserDep,
    service: UserServiceDep,
):

    return await service.update_username(current_user.id, data.username)


@router.post(
    "/me/avatar/upload-link",
    response_model=AvatarUploadResponse,
    summary="Получить ссылку для загрузки аватара",
    description="Возвращает временную ссылку для загрузки напрямую в S3. Трафик не идет через бэкенд.",
)
async def get_avatar_upload_link(
    current_user: CurrentUserDep,
    service: UserServiceDep,
    content_type: str = Query(..., description="MIME-тип (image/jpeg, image/png)", examples=["image/jpeg"]),
):
    return await service.update_avatar(current_user, content_type)


@router.get(
    "/me/sessions",
    response_model=list[SessionInfo],
    summary="Активные сессии",
    description="Список всех устройств, на которых выполнен вход",
)
async def list_sessions(
    current_user: CurrentUserDep,
    service: AuthServiceDep,  # Сессии остались в AuthService
):

    return await service.list_sessions(current_user, current_user.current_session_id)


@router.patch(
    "/me/availability",
    summary="Изменить статус доступности",
    description="Переключает режим 'На работе' / 'Отдыхаю'.",
)
async def update_availability(current_user: WorkerDep, service: UserServiceDep):
    is_available = await service.toggle_work_status(current_user)
    return {
        "status": "success",
        "message": f"Статус изменен на: {is_available}",
        "is_available": is_available,
        "role": current_user.role,
    }


@router.post(
    "/me/logout",
    summary="Выйти из системы",
    description="Аннулирует текущую сессию (Refresh токен)",
)
async def logout(current_user: CurrentUserDep, service: AuthServiceDep):
    await service.logout(current_user.id, current_user.current_session_id)
    return {"status": "success", "message": "Вышли из системы"}


@router.post(
    "/me/logout-all",
    summary="Выйти со всех устройств",
    description="Сбрасывает абсолютно все активные сессии пользователя",
)
async def logout_all(current_user: CurrentUserDep, service: AuthServiceDep):
    await service.logout_all(current_user.id)
    return {"status": "success", "message": "Вышли со всех устройств"}


@router.delete(
    "/me/delete-account",
    summary="Удалить аккаунт",
    description="Мягкое удаление профиля (Soft Delete) и всех связанных сессий",
)
async def delete_account(
    current_user: CurrentUserDep,
    service: UserServiceDep,  # Теперь используем UserService
):
    # Метод внутри UserService сам вызовет S3 и AuthService.logout_all
    await service.delete_account(current_user)
    return {"status": "success", "message": "Аккаунт будет удален в течение 30 дней"}
