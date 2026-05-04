from fastapi import APIRouter, Depends

from app.api.v1 import auth, permissions, users
from app.core.openapi import RouteTag
from app.core.security import get_current_admin

v1_router = APIRouter()

# Рекомендуется выносить теги в константы или настройки
v1_router.include_router(auth.router, prefix="/auth", tags=[RouteTag.AUTH])
v1_router.include_router(users.router, prefix="/users", tags=[RouteTag.USERS])
v1_router.include_router(
    permissions.router, prefix="/admin", tags=[RouteTag.ADMIN], dependencies=[Depends(get_current_admin)]
)

# v1_router.include_router(chats_router, prefix="/chats", tags=["Chats"])
