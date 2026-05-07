from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UpdateProfileRequest(BaseModel):
    """Схема для обновления профиля."""
    model_config = ConfigDict(str_strip_whitespace=True)
    first_name: str | None = Field(None, pattern=r"^[^\s].*[^\s]$", min_length=2, max_length=100, examples=["Иван"])
    last_name: str | None = Field(None, max_length=50, examples=["Иванов"])
    middle_name: str | None = Field(None, max_length=50, examples=["Иванович"])


class UpdateUsernameRequest(BaseModel):
    # Валидация ника: латиница, цифры, подчеркивание
    username: str = Field(..., min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")


class AvatarUploadResponse(BaseModel):
    """Схема ответа для подготовки загрузки файла напрямую в S3."""

    upload_data: dict  # Временная ссылка для PUT-запроса (от Яндекса)
    photo_url: str  # Финальная ссылка, которая уже записана в БД


class UpdateEmailRequest(BaseModel):
    """Схема для привязки или смены почты."""

    email: EmailStr = Field(..., examples=["ivanov@yandex.ru"])


class UserRole(StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    TRIP_GUIDE = "trip_guide"


class UserShort(BaseModel):
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
        None, examples=["https://yandexcloud.net"], description="Прямая ссылка на аватар в S3"
    )

    role: UserRole = Field(UserRole.CUSTOMER, examples=["customer"])
    is_banned: bool = Field(False, description="Статус блокировки пользователя")
    is_superuser: bool = Field(False, description="Флаг суперпользователя")

    created_at: datetime = Field(..., examples=["2026-05-04T18:35:48Z"])
    last_active: datetime = Field(..., examples=["2026-05-04T19:36:15Z"])

    is_available: bool = Field(True, description="Доступность (для водителей/гидов)")
    app_version: str | None = Field(None, examples=["1.0.2"], description="Версия клиента")

    @field_validator("phone", mode="after")
    @classmethod
    def mask_phone_number(cls, v: str) -> str:
        if len(v) > 8:
            return f"{v[:5]}****{v[-2:]}"
        return v

    @field_validator("email", mode="after")
    @classmethod
    def mask_email_address(cls, v: str | None) -> str | None:
        """Маскируем почту только при выводе пользователю."""
        if v and "@" in v:
            # Если почта уже замаскирована (например, достали из кэша), не трогаем
            if "****" in v:
                return v

            name, domain = v.split("@")
            prefix = name[:3] if len(name) > 3 else name[0]
            return f"{prefix}****@{domain}"
        return v


class AdminSchema(BaseModel):
    """Данные только для админа."""
    model_config = ConfigDict(from_attributes=True)
    access_level: int = Field(..., description="Уровень в иерархии (50-100)")


class CustomerSchema(BaseModel):
    """Данные только для клиента (пассажира/туриста)."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    onboarding_status: str | None = Field(None, examples=["on_moderation"])
    onboarding_error: str | None = Field(None, alias="admin_comment")


class SupplierSchema(BaseModel):
    """Данные только для водителя."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    rating: float = Field(5.0)
    car_model: str | None = None
    car_number: str | None = None


class TripguideSchema(BaseModel):
    """Данные только для гида."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    rating: float = Field(5.0)
    languages: list[str] = Field(default_factory=list, examples=[["RU", "EN"]])


# --- 3. НОВОЕ: Итоговая "Матрешка" для /me ---
class FullProfileResponse(BaseModel):
    """Композитная схема профиля (Путь Яндекса)."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    user: UserShort

    # Расширения. Если роль не совпадает, придет null
    admin_data: AdminSchema | None = None
    customer_data: CustomerSchema | None = None
    supplier_data: SupplierSchema | None = None
    trip_guide_data: TripguideSchema | None = None
