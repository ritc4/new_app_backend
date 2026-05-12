from datetime import date, datetime
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.base import ActionResponse, UserBase


class UserShort(UserBase):
    """Схема для обычного пользователя. Накладываем маскировку."""

    @field_validator("phone", "email", mode="after")
    @classmethod
    def apply_masking(cls, v: str | None) -> str | None:
        if not v or "****" in v:
            return v
        if "@" in v:
            name, domain = v.split("@")
            return f"{name[:2]}****@{domain}"
        return f"{v[:5]}****{v[-2:]}"


class UpdateProfileRequest(BaseModel):
    """Схема для обновления профиля."""

    model_config = ConfigDict(str_strip_whitespace=True)
    first_name: str | None = Field(None, pattern=r"^[^\s].*[^\s]$", min_length=2, max_length=100, examples=["Иван"])
    last_name: str | None = Field(None, max_length=50, examples=["Иванов"])
    middle_name: str | None = Field(None, max_length=50, examples=["Иванович"])


class UpdateProfileResponse(ActionResponse):
    user: UserShort


class UpdateUsernameRequest(BaseModel):
    # Валидация ника: латиница, цифры, подчеркивание
    username: str = Field(..., min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")


class UpdateUsernameResponse(ActionResponse):
    # Валидация ника: латиница, цифры, подчеркивание
    user: UserShort


class UpdateEmailRequest(BaseModel):
    """Схема для привязки или смены почты."""

    email: EmailStr = Field(..., examples=["ivanov@yandex.ru"])


class UpdateEmailResponse(ActionResponse):
    user: UserShort


class S3UploadData(TypedDict):
    url: str
    fields: dict[str, str]


class AvatarUploadResponse(ActionResponse):
    """Схема ответа для подготовки загрузки файла напрямую в S3."""

    upload_data: S3UploadData  # Временная ссылка для PUT-запроса (от Яндекса)
    photo_url: str  # Финальная ссылка, которая уже записана в БД


class AvailabilityResponse(ActionResponse):
    is_available: bool


class DeleteAccountResponse(ActionResponse):
    restore_until_days: int
    # Конкретная дата, понятная пользователю
    restore_until_date: datetime
    user: UserShort


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
    """
    Публичный профиль водителя (Response DTO).
    Валидаторы здесь не нужны, так как данные уже проверены при заполнении анкеты.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    rating: float = Field(default=5.0, examples=[4.95])

    # Данные авто
    car_model: str = Field(..., examples=["Tesla Model 3"])
    car_year: int = Field(..., examples=[2022])
    car_number: str = Field(..., examples=["А777АА77"])
    car_color: str = Field(..., examples=["Белый"])
    vin_number: str | None = Field(None, examples=["1YVHP8CB123456789"])

    # Документы
    license_number: str = Field(..., examples=["9901 123456"])
    license_expiry_date: date = Field(...)
    experience_years: int = Field(..., ge=0)

    # Ссылки на фото (уже публичные URL из S3)
    photo_selfie: str = Field(...)
    photo_car_front: str = Field(...)
    photo_car_back: str = Field(...)
    photo_sts_front: str = Field(...)
    photo_sts_back: str = Field(...)
    photo_license: str = Field(...)


class TripguideSchema(BaseModel):
    """Данные только для гида."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    rating: float = Field(5.0)
    languages: list[str] = Field(default_factory=list, examples=[["RU", "EN"]])

    # Добавляем недостающие поля, чтобы они не пропадали
    bio: str | None = Field(None, max_length=1000)
    specialization: str | None = Field(None, max_length=255)
    photo_certificate: str | None = Field(None)


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
