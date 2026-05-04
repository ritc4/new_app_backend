from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class AvatarUploadResponse(BaseModel):
    """Схема ответа для подготовки загрузки файла напрямую в S3."""

    upload_data: dict  # Временная ссылка для PUT-запроса (от Яндекса)
    photo_url: str  # Финальная ссылка, которая уже записана в БД


class UserRole(StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    TRIP_GUIDE = "trip_guide"


class UserShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID 
    phone: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    email: EmailStr | None = None
    photo_url: str | None = None

    role: UserRole
    is_banned: bool
    is_superuser: bool

    created_at: datetime
    last_active: datetime
    is_available: bool
    app_version: str | None = None

    @field_validator("phone", mode="after")
    @classmethod
    def mask_phone_number(cls, v: str) -> str:
        """
        Маскирует номер телефона для логов и публичных ответов.
        Например: +79620001122 -> +7962****22
        """
        if len(v) > 8:
            return f"{v[:5]}****{v[-2:]}"
        return v

    @field_validator("email", mode="after")
    @classmethod
    def mask_email_address(cls, v: EmailStr | None) -> str | None:
        """
        Маскирует email.
        Например: ivan_ivanov@mail.ru -> ivan****@mail.ru
        """
        if v:
            name, domain = v.split("@")
            return f"{name[:3]}****@{domain}"
        return v
