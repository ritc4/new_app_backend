import re
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.admin import UserAdminView
from app.schemas.base import ActionResponse


class BankType(StrEnum):
    SBER = "sber"
    T_BANK = "t_bank"


class OnboardingStart(BaseModel):
    target_role: str  # supplier / trip_guide
    bank: BankType


class BankWebhookPayload(BaseModel):
    user_id: int
    phone: str
    inn: str = Field(..., min_length=10, max_length=12)  # Защита от мусора
    full_name: str

    @field_validator("inn")
    @classmethod
    def validate_inn_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("ИНН должен состоять только из цифр")
        return v


class BankWebhookPayloadResponse(ActionResponse):
    pass


class SupplierSurvey(BaseModel):
    """Расширенная анкета водителя (Enterprise Standard)."""

    # --- Данные авто ---
    car_brand: str = Field(..., min_length=2, max_length=50, examples=["Tesla"])
    car_model: str = Field(..., min_length=2, max_length=100, examples=["Model 3"])
    car_year: int = Field(..., ge=1990, le=datetime.now().year + 1, description="Год выпуска авто")
    car_number: str = Field(..., min_length=6, max_length=15, examples=["А777АА77"])
    car_color: str = Field(..., min_length=2, max_length=30, examples=["Белый"])
    vin_number: str | None = Field(None, min_length=17, max_length=17, description="VIN-код")

    # --- Документы ---
    license_number: str = Field(..., min_length=8, max_length=20, examples=["9901 123456"])
    license_expiry_date: date = Field(..., description="Дата окончания срока действия прав")
    license_country: str = Field(default="RU", min_length=2, max_length=50, examples=["Страна выдачи прав"])

    experience_years: int = Field(..., ge=0, le=60)

    # --- Фото-контроль ---
    photo_selfie: str = Field(..., description="Селфи водителя")
    photo_car_side: str = Field(..., description="Фото авто с боковой стороны")
    photo_car_interior: str = Field(..., description="Фото салона авто")
    photo_car_front: str = Field(..., description="Фото авто спереди")
    photo_car_back: str = Field(..., description="Фото авто сзади (видны номера)")
    photo_sts_front: str = Field(..., description="Фото СТС (лицевая)")
    photo_sts_back: str = Field(..., description="Фото СТС (оборотная)")
    photo_license: str = Field(..., description="Фото водительского удостоверения")

    # --- Валидаторы ---

    @field_validator("car_number")
    @classmethod
    def validate_car_number(cls, v: str) -> str:
        trans_map = {
            "A": "А",
            "B": "В",
            "E": "Е",
            "K": "К",
            "M": "М",
            "H": "Н",
            "O": "О",
            "P": "Р",
            "C": "С",
            "T": "Т",
            "Y": "У",
            "X": "Х",
        }
        v = v.upper().replace(" ", "")
        for eng, rus in trans_map.items():
            v = v.replace(eng, rus)
        if not re.match(r"^[А-Я0-9]+$", v):
            raise ValueError("Номер содержит недопустимые символы")
        return v

    @field_validator("vin_number")
    @classmethod
    def validate_vin(cls, v: str | None) -> str | None:
        if v:
            v = v.upper().replace(" ", "")
            # Исключаем I, O, Q (стандарт VIN)
            if not re.match(r"^[A-HJ-NPR-Z0-9]{17}$", v):
                raise ValueError("Некорректный VIN (запрещены буквы I, O, Q)")
        return v

    @field_validator("license_expiry_date")
    @classmethod
    def check_license_valid(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("Срок действия водительского удостоверения истек")
        return v

    @model_validator(mode="after")
    def check_car_age(self) -> "SupplierSurvey":
        # Машина не старше 15 лет (Enterprise требование)
        current_year = datetime.now().year
        if current_year - self.car_year > 15:
            raise ValueError("Автомобиль старше 15 лет не допускается к работе")
        return self

    @model_validator(mode="after")
    def validate_license_format(self) -> "SupplierSurvey":
        # 1. Приводим к верхнему регистру и убираем пробелы для чистоты
        val = self.license_number.upper().replace(" ", "")
        country = self.license_country.upper()

        # 2. Словарь правил (Regex) для разных стран
        patterns = {
            "RU": r"^\d{10}$",  # РФ: 10 цифр (серия + номер)
            "BY": r"^[1-9][A-Z]{2}\d{7}$",  # Беларусь: цифра, 2 буквы, 7 цифр
            "KZ": r"^[A-Z]{2}\d{6,9}$",  # Казахстан: 2 буквы и цифры
        }

        # 3. Выполняем проверку, если страна есть в списке
        if country in patterns:
            if not re.match(patterns[country], val):
                error_msg = {
                    "RU": "Номер прав РФ должен состоять из 10 цифр",
                    "BY": "Неверный формат прав Беларуси",
                    "KZ": "Неверный формат прав Казахстана",
                }.get(country, "Неверный формат номера прав")
                raise ValueError(error_msg)

        # Перезаписываем очищенное значение (без пробелов) обратно в модель
        self.license_number = val
        return self

    @field_validator("experience_years")
    @classmethod
    def validate_experience(cls, v: int) -> int:
        if v < 3:
            raise ValueError("Минимальный стаж вождения для регистрации — 3 года")
        return v


class TripguideSurvey(BaseModel):
    """Анкета гида (Шаг 3)."""

    bio: str = Field(..., min_length=20, max_length=1000, description="Рассказ о себе и опыте")
    languages: list[str] = Field(default_factory=list, examples=[["RU", "EN"]])
    specialization: str = Field(..., examples=["Пешие походы", "История архитектуры"])
    photo_certificate: str | None = None


class OnboardingStatus(StrEnum):
    PENDING_LEGAL = "pending_legal"
    FILLING_SURVEY = "filling_survey"
    ON_MODERATION = "on_moderation"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELED = "canceled"


class OnboardingAppShort(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    user_id: int
    target_role: str
    inn: str | None
    bank_type: str | None
    survey_payload: SupplierSurvey | TripguideSurvey | None = None
    status: OnboardingStatus
    admin_comment: str | None = Field(None, alias="onboarding_error")
    created_at: datetime
    # Теперь здесь полные данные без звездочек
    user: UserAdminView


class RejectApplicationRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=255, examples=["Плохое качество фото СТС"])


class OnboardingLinkResponse(ActionResponse):
    link: str


class OnboardingUploadResponse(BaseModel):
    upload_data: dict[str, str]
    file_url: str


class CancelCurrentApplicationResponse(ActionResponse):
    pass


class SubmitSurveyResponse(ActionResponse):
    pass


ROLE_SURVEY_SCHEMAS = {
    "supplier": SupplierSurvey,
    "trip_guide": TripguideSurvey,
}


ROLE_ALLOWED_PHOTOS = {
    "supplier": {
        "photo_selfie",
        "photo_car_side",
        "photo_car_interior",
        "photo_car_front",
        "photo_car_back",
        "photo_sts_front",
        "photo_sts_back",
        "photo_license",
    },
    "trip_guide": {"photo_certificate"},
}
