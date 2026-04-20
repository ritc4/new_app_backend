import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies.auth import get_auth_service
from app.core.security import get_current_user
from app.schemas.user import UserRole, UserShort
from app.services.auth_service import AuthService

logger = logging.getLogger("app.api.permissions")
router = APIRouter()

# Алиас для сервиса
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
# Алиас для текущего юзера
CurrentUserDep = Annotated[dict, Depends(get_current_user)]


@router.patch("/admin/set-role/{user_id}", response_model=UserShort)
async def set_user_role(
    user_id: int,
    role: UserRole,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    """Установка роли (только админ). Сбрасывает сессии пользователя."""
    user = await service.set_user_role(current_user, user_id, role)
    return user


@router.patch("/admin/user-ban/{user_id}")
async def toggle_user_ban(
    user_id: int,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    """Полный бан/разбан (только админ). Мгновенно обрывает доступ."""
    is_banned = await service.toggle_user_ban(current_user, user_id)
    return {"status": "success", "is_banned": is_banned}


@router.post("/admin/change-user-phone")
async def admin_change_phone(
    target_user_id: int,
    new_phone: str,
    current_user: CurrentUserDep,
    service: AuthServiceDep,
):
    """Смена телефона администратором. Вызывает logout_all для пользователя."""
    await service.admin_change_phone(current_user, target_user_id, new_phone)
    return {"status": "success", "message": f"Номер изменен на {new_phone}"}
