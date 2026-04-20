from fastapi import APIRouter

from app.api.v1 import auth, permissions, users

v1_router = APIRouter()

# Рекомендуется выносить теги в константы или настройки
v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
v1_router.include_router(users.router, prefix="/users", tags=["Users Profile"])
v1_router.include_router(
    permissions.router, prefix="/permissions", tags=["Access Control"]
)

# v1_router.include_router(chats_router, prefix="/chats", tags=["Chats"])
