from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserRole(StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    TRIP_GUIDE = "trip_guide"


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    # Публичный ID всегда с примером
    uuid: UUID = Field(..., examples=["56f02c1b-fdac-4646-9b5b-1dd6e640f85d"])

    # Телефон маскируется, но пример показываем реальный для ясности формата
    phone: str = Field(..., examples=["+79620000096"], description="Маскированный номер телефона")

    # Убираем кракозябры из Swagger, ставим понятный пример
    username: str | None = Field(None, examples=["user_a1b2c"], description="Уникальный технический никнейм")

    first_name: str | None = Field(None, examples=["Иван"])
    last_name: str | None = Field(None, examples=["Иванов"])
    middle_name: str | None = Field(None, examples=["Иванович"])

    # Email тоже с примером
    email: str | None = Field(None, examples=["ivan****@yandex.ru"])
    is_email_verified: bool = Field(False, description="Статус подтверждения почты")

    photo_url: str | None = Field(
        None,
        examples=["https://yandexcloud.net"],
        description="Прямая ссылка на аватар в S3",
    )

    role: UserRole = Field(UserRole.CUSTOMER, examples=["customer"])
    is_banned: bool = Field(False, description="Статус блокировки пользователя")
    is_superuser: bool = Field(False, description="Флаг суперпользователя")

    created_at: datetime = Field(..., examples=["2026-05-04T18:35:48Z"])
    last_active: datetime = Field(..., examples=["2026-05-04T19:36:15Z"])

    is_available: bool = Field(True, description="Доступность (для водителей/гидов)")
    app_version: str | None = Field(None, examples=["1.0.2"], description="Версия клиента")
    deleted_at: datetime | None = Field(None, examples=["2026-06-10T18:35:48Z"], description="Дата пометки на удаление")


class ActionResponse(BaseModel):
    status: str = "success"
    message: str | None = None
