from datetime import date, datetime
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.spatial import CarClass
from app.schemas.base import ActionResponse, UserBase


class UserShort(UserBase):
    """Схема для обычного пользователя. Накладываем маскировку."""

    @field_validator("phone", "email", mode="after")
    @classmethod
    def apply_masking(cls, v: str | None) -> str | None:
        # Защита от AttributeError, если поле в базе равно NULL (None)
        if v is None:
            return None

        if not v or "****" in v:
            return v
        if "@" in v:
            name, domain = v.split("@")
            return f"{name[:2]}****@{domain}"
        return f"{v[:5]}****{v[-2:]}"


class UpdateProfileRequest(BaseModel):
    """Схема для обновления профиля."""

    model_config = ConfigDict(str_strip_whitespace=True)
    first_name: str | None = Field(None, min_length=2, max_length=100, examples=["Иван"])
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

    rating: float = Field(default=5.0, examples=[4.95], description="Рейтинг водителя")
    base_region_id: int = Field(..., description="ID базового региона выполнения трансферов")
    languages: list[str] = Field(
        default_factory=list,
        examples=[["RU", "EN"]],
        description="Список кодов языков общения водителя по стандарту ISO 639-1",
    )
    # --- Данные авто ---
    car_brand: str = Field(..., min_length=2, max_length=50, examples=["Tesla"])
    car_model: str = Field(..., min_length=2, max_length=100, examples=["Model 3"])
    car_class: CarClass = Field(
        default=CarClass.ECONOMY, description="Класс автомобиля для расчета стоимости трансфера"
    )
    car_year: int = Field(..., ge=1990, description="Год выпуска авто")
    car_number: str = Field(..., min_length=6, max_length=15, examples=["А777АА77"])
    car_color: str = Field(..., min_length=2, max_length=30, examples=["Белый"])
    vin_number: str | None = Field(None, min_length=17, max_length=17, description="VIN-код")

    # Документы
    license_number: str = Field(..., examples=["9901 123456"], description="Номер водительского удостоверения")
    license_expiry_date: date = Field(
        ..., examples=["2022-01-01"], description="Дата окончания действия водительского удостоверения"
    )
    experience_years: int = Field(..., ge=0, le=60, examples=[5], description="Стаж водителя")
    license_country: str = Field(
        default="RU", min_length=2, max_length=2, description="Страна выдачи водительского удостоверения"
    )

    # Ссылки на фото (уже публичные URL из S3)
    photo_selfie: str = Field(...)
    photo_car_side: str = Field(..., description="Фото авто с боковой стороны")
    photo_car_interior: str = Field(..., description="Фото салона авто")
    photo_car_front: str = Field(..., description="Фото авто спереди")
    photo_car_back: str = Field(..., description="Фото авто сзади (видны номера)")
    photo_sts_front: str = Field(..., description="Фото sts спереди")
    photo_sts_back: str = Field(..., description="Фото sts сзади")
    photo_license: str = Field(..., description="Фото водительского удостоверения")

    @model_validator(mode="after")
    def check_future_year(self) -> "SupplierSchema":
        current_year = datetime.now().year
        if self.car_year > current_year + 1:
            raise ValueError(f"Год выпуска авто не может быть позже {current_year + 1}")
        return self


class TripguideSchema(BaseModel):
    """Данные только для гида."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    rating: float = Field(5.0, examples=[4.95], description="Рейтинг гида")
    base_region_id: int = Field(..., description="ID домашнего региона проведения пеших экскурсий")
    languages: list[str] = Field(default_factory=list, examples=[["RU", "EN"]], description="Список кодов языков")

    # Добавляем недостающие поля, чтобы они не пропадали
    bio: str | None = Field(None, max_length=1000, description="Описание гида")
    specialization: str | None = Field(None, max_length=255, description="Специализация гида")
    photo_certificate: str | None = Field(None, max_length=500, description="Ссылка на фото лицензии в S3")


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
