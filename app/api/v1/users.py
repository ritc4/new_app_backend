from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies.auth import get_auth_service
from app.core.dependencies.user import (
    get_current_customer,
    get_current_worker,
    get_user_service,
)
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.auth import (
    CompleteRegistrationRequest,
    LogoutAllResponse,
    LogoutResponse,
    RegistrationResponse,
    SessionInfo,
)
from app.schemas.user import (
    AvailabilityResponse,
    AvatarUploadResponse,
    DeleteAccountResponse,
    FullProfileResponse,
    UpdateEmailRequest,
    UpdateEmailResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    UpdateUsernameRequest,
    UpdateUsernameResponse,
)
from app.services.auth_service import AuthService
from app.services.user_service import UserService

router = APIRouter()

# Обновленные алиасы типов
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
WorkerDep = Annotated[User, Depends(get_current_worker)]
CustomerDep = Annotated[User, Depends(get_current_customer)]


@router.patch(
    "/me/complete-registration",
    summary="Завершение регистрации",
    description="Установка имени и фамилии при первом входе",
    response_model=RegistrationResponse,
)
async def complete_registration(
    data: CompleteRegistrationRequest,
    current_user: CurrentUserDep,
    service: UserServiceDep,
) -> RegistrationResponse:
    return await service.complete_registration(current_user.id, data)


@router.get(
    "/me",
    summary="Получить мой профиль",
    description="Возвращает полную информацию о себе + специфические данные роли",
    response_model=FullProfileResponse,
)
async def read_current_user(current_user: CurrentUserDep, service: UserServiceDep) -> FullProfileResponse:
    return await service.get_full_profile(current_user)


@router.patch(
    "/me/update-profile",
    response_model=UpdateProfileResponse,
    summary="Обновить ФИО",
    description="Доступно только для клиентов. Водители и гиды меняют данные только через поддержку.",
)
async def update_profile(
    data: UpdateProfileRequest,
    current_user: CustomerDep,
    service: UserServiceDep,
) -> UpdateProfileResponse:
    return await service.update_profile(current_user.id, data)


@router.patch(
    "/me/update-username",
    summary="Сменить никнейм",
    description="Обновляет уникальное имя пользователя в системе",
    response_model=UpdateUsernameResponse,
)
async def update_username(
    data: UpdateUsernameRequest,
    current_user: CurrentUserDep,
    service: UserServiceDep,
) -> UpdateUsernameResponse:
    return await service.update_username(current_user.id, data.username)


@router.patch(
    "/me/update-email",
    summary="Привязать или изменить Email",
    description="Обновляет почту пользователя и сбрасывает статус верификации.",
    response_model=UpdateEmailResponse,
)
async def update_email(
    data: UpdateEmailRequest,
    current_user: CurrentUserDep,
    service: UserServiceDep,
) -> UpdateEmailResponse:
    return await service.update_email(current_user.id, data.email)


@router.post(
    "/me/avatar/upload-link",
    summary="Получить ссылку для загрузки аватара",
    description="Возвращает временную ссылку для загрузки напрямую в S3. Трафик не идет через бэкенд.",
    response_model=AvatarUploadResponse,
)
async def get_avatar_upload_link(
    current_user: CurrentUserDep,
    service: UserServiceDep,
    content_type: str = Query(...),
) -> AvatarUploadResponse:
    return await service.update_avatar(current_user, content_type)


@router.get(
    "/me/sessions",
    summary="Активные сессии",
    description="Список всех устройств, на которых выполнен вход",
    response_model=list[SessionInfo],
)
async def list_sessions(current_user: CurrentUserDep, service: AuthServiceDep) -> list[SessionInfo]:
    return await service.list_sessions(current_user, current_user.current_session_id)


@router.patch(
    "/me/availability",
    summary="Изменить статус доступности",
    description="Переключает режим 'На работе' / 'Отдыхаю'.",
    response_model=AvailabilityResponse,
)  # Добавили схему
async def update_availability(current_user: WorkerDep, service: UserServiceDep) -> AvailabilityResponse:
    # Теперь сервис возвращает готовый словарь
    return await service.toggle_work_status(current_user)


@router.post(
    "/me/logout",
    summary="Выйти из системы",
    description="Аннулирует текущую сессию (Refresh токен)",
    response_model=LogoutResponse,
)  # Добавили схему
async def logout(current_user: CurrentUserDep, service: AuthServiceDep) -> LogoutResponse:
    return await service.logout(current_user.id, current_user.current_session_id)


@router.post(
    "/me/logout-all",
    summary="Выйти со всех устройств",
    description="Сбрасывает абсолютно все активные сессии пользователя",
    response_model=LogoutAllResponse,
)  # Добавили схему
async def logout_all(current_user: CurrentUserDep, service: AuthServiceDep) -> LogoutAllResponse:
    return await service.logout_all(current_user.id)


@router.delete(
    "/me/delete-account",
    summary="Удалить аккаунт",
    description="Мягкое удаление профиля (Soft Delete) и всех связанных сессий",
    response_model=DeleteAccountResponse,
)  # Добавили схему
async def delete_account(current_user: CurrentUserDep, service: UserServiceDep) -> DeleteAccountResponse:
    return await service.delete_account(current_user)
