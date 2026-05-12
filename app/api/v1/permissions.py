from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

# Импортируем НОВУЮ зависимость для админа
from app.core.dependencies.admin import get_admin_service
from app.core.security import get_current_admin
from app.models.user import User
from app.schemas.admin import AdminActionResponse, AdminChangePhoneRequest
from app.schemas.base import UserRole
from app.schemas.onboarding import OnboardingAppShort, RejectApplicationRequest
from app.services.admin_service import AdminService

router = APIRouter()

# Алиас для НОВОГО сервиса
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
CurrentAdminDep = Annotated[User, Depends(get_current_admin)]


@router.patch(
    "/role/{user_uuid}",
    summary="Изменить рабочую роль (Aдмин/Клиент)",
    response_model=AdminActionResponse,
)
async def set_user_role(
    user_uuid: UUID,
    role: UserRole,
    admin: CurrentAdminDep,
    service: AdminServiceDep,
) -> AdminActionResponse:
    return await service.set_user_role(admin, user_uuid, role)


@router.patch(
    "/ban/{user_uuid}",
    summary="Заблокировать/Разблокировать пользователя",
    response_model=AdminActionResponse,
)
async def toggle_user_ban(user_uuid: UUID, admin: CurrentAdminDep, service: AdminServiceDep) -> AdminActionResponse:
    return await service.toggle_user_ban(admin, user_uuid)


@router.post(
    "/change-phone/{user_uuid}",
    summary="Принудительная смена номера телефона пользователя",
    response_model=AdminActionResponse,
)
async def admin_change_phone(
    user_uuid: UUID,
    data: AdminChangePhoneRequest,
    admin: CurrentAdminDep,
    service: AdminServiceDep,
) -> AdminActionResponse:
    return await service.admin_change_phone(admin, user_uuid, data.new_phone)


@router.patch(
    "/onboarding/{application_id}/approve",
    summary="Одобрить заявку партнера",
    response_model=AdminActionResponse,
)
async def approve_onboarding(
    application_id: int,
    admin: CurrentAdminDep,
    service: AdminServiceDep,
) -> AdminActionResponse:
    return await service.approve_partner_application(admin, application_id)


@router.patch(
    "/onboarding/{application_id}/reject",
    summary="Отклонить заявку партнера",
    response_model=AdminActionResponse,
)
async def reject_onboarding(
    application_id: int,
    data: RejectApplicationRequest,  # Обязательная причина
    admin: CurrentAdminDep,
    service: AdminServiceDep,
) -> AdminActionResponse:
    return await service.reject_partner_application(admin, application_id, data.reason)


@router.get(
    "/onboarding/pending",
    summary="Список заявок на модерацию",
    description="Возвращает список заявок в статусе on_moderation. Самые старые — первые.",
    response_model=list[OnboardingAppShort],
)
async def list_pending_onboarding(
    admin: CurrentAdminDep,
    service: AdminServiceDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[OnboardingAppShort]:
    return await service.get_pending_applications(admin, limit, offset)
