import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

# Импортируем НОВУЮ зависимость для админа
from app.core.dependencies.admin import get_admin_service
from app.core.security import get_current_admin
from app.models.user import User
from app.schemas.auth import AdminActionResponse, AdminChangePhoneRequest
from app.schemas.user import UserRole
from app.services.admin_service import AdminService

logger = logging.getLogger("app.api.permissions")
router = APIRouter()

# Алиас для НОВОГО сервиса
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
CurrentAdminDep = Annotated[User, Depends(get_current_admin)]


@router.patch("/role/{user_uuid}", response_model=AdminActionResponse)
async def set_user_role(user_uuid: UUID, role: UserRole, admin: CurrentAdminDep, service: AdminServiceDep):
    return await service.set_user_role(admin, user_uuid, role)


@router.patch("/ban/{user_uuid}", response_model=AdminActionResponse)
async def toggle_user_ban(user_uuid: UUID, admin: CurrentAdminDep, service: AdminServiceDep):
    return await service.toggle_user_ban(admin, user_uuid)


@router.post("/change-phone/{user_uuid}", response_model=AdminActionResponse)
async def admin_change_phone(
    user_uuid: UUID, data: AdminChangePhoneRequest, admin: CurrentAdminDep, service: AdminServiceDep
):
    return await service.admin_change_phone(admin, user_uuid, data.new_phone)


# @router.patch(
#     "/role/{user_uuid}",
#     response_model=UserShort,
#     summary="Изменить рабочую роль (Aдмин/Клиент/Гид/Водитель)",
# )
# async def set_user_role(
#     user_uuid: UUID,
#     role: UserRole,
#     current_admin: CurrentAdminDep,
#     service: AdminServiceDep,
# ):
#     logger.info(f"Админ {current_admin.id} пытается установить роль {role} для {user_uuid}")
#     # Теперь возвращаем объект пользователя целиком, как того требует response_model=UserShort
#     return await service.set_user_role(current_admin, user_uuid, role)


# @router.patch(
#     "/ban/{user_uuid}",
#     summary="Заблокировать/Разблокировать пользователя",
# )
# async def toggle_user_ban(
#     user_uuid: UUID,
#     current_admin: CurrentAdminDep,
#     service: AdminServiceDep,
# ):
#     is_banned = await service.toggle_user_ban(current_admin, user_uuid)
#     return {
#         "status": "success",
#         "message": "Пользователь заблокирован" if is_banned else "Пользователь разблокирован",
#         "is_banned": is_banned,
#     }


# @router.post(
#     "/change-phone/{user_uuid}",
#     summary="Принудительная смена номера телефона",
# )
# async def admin_change_phone(
#     user_uuid: UUID,
#     data: AdminChangePhoneRequest,
#     current_admin: CurrentAdminDep,
#     service: AdminServiceDep,  # Используем AdminService
# ):
#     # Передаем данные из схемы
#     await service.admin_change_phone(current_admin, user_uuid, data.new_phone)
#     return {"status": "success", "message": f"Номер изменен на {data.new_phone}"}


# @router.patch(
#     "/role/{user_uuid}",
#     summary="Изменить рабочую роль",
#     response_model=AdminActionResponse, # Используем новую схему
# )
# async def set_user_role(user_uuid: UUID, role: UserRole, admin: CurrentAdminDep, service: AdminServiceDep):
#     updated_user = await service.set_user_role(admin, user_uuid, role)
#     return {
#         "message": f"Роль изменена на {role}",
#         "user": updated_user
#     }

# @router.patch(
#     "/ban/{user_uuid}",
#     summary="Блокировка/Разблокировка",
#     response_model=AdminActionResponse, # Используем новую схему
# )
# async def toggle_user_ban(user_uuid: UUID, admin: CurrentAdminDep, service: AdminServiceDep):
#     is_banned, target_user = await service.toggle_user_ban(admin, user_uuid)
#     action = "заблокирован" if is_banned else "разблокирован"
#     return {
#         "message": f"Пользователь успешно {action}",
#         "user": target_user
#     }

# @router.post(
#     "/change-phone/{user_uuid}",
#     summary="Смена номера телефона",
#     response_model=AdminActionResponse, # Используем новую схему
# )
# async def admin_change_phone(user_uuid: UUID, data: AdminChangePhoneRequest,
#   admin: CurrentAdminDep, service: AdminServiceDep):
#     updated_user = await service.admin_change_phone(admin, user_uuid, data.new_phone)
#     return {
#         "message": f"Номер телефона изменен на {data.new_phone}",
#         "user": updated_user
#     }
