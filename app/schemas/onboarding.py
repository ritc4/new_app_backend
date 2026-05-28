import re
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.spatial import CarClass
from app.schemas.admin import UserAdminView
from app.schemas.base import ActionResponse, UserRole
from app.schemas.s3 import S3PresignedPost


class BankType(StrEnum):
    SBER = "sber"
    T_BANK = "t_bank"


class OnboardingStart(BaseModel):
    target_role: Literal[UserRole.SUPPLIER, UserRole.TRIP_GUIDE] = Field(
        ..., description="Выбранная роль пользователя (доступны только исполнители)"
    )
    bank: BankType
    target_region_id: int = Field(..., description="ID операционного региона (хаба) начала деятельности")


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

    role_type: Literal[UserRole.SUPPLIER] = UserRole.SUPPLIER

    # --- Данные водителя ---
    languages: list[str] = Field(
        default_factory=lambda: ["RU"],
        examples=[["RU", "EN"]],
        description="Список языков, на которых водитель может общаться с пассажиром (ISO 639-1)",
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

    # --- Документы ---
    license_number: str = Field(
        ..., min_length=8, max_length=20, examples=["9901 123456"], description="Номер водительского удостоверения"
    )
    license_expiry_date: date = Field(..., examples=["2022-01-01"], description="Дата окончания срока действия прав")
    license_country: str = Field(
        default="RU", min_length=2, max_length=2, description="Страна выдачи водительского удостоверения"
    )

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

    @field_validator("languages")
    @classmethod
    def validate_and_normalize_languages(cls, v: list[str]) -> list[str]:
        """Проверяет коды языков водителя по международному стандарту ISO 639-1."""
        cleaned_langs = [lang.strip().upper() for lang in v if lang.strip()]
        if not cleaned_langs:
            raise ValueError("Список языков общения водителя не может быть пустым")

        for lang_code in cleaned_langs:
            iso_language = pycountry.languages.get(alpha_2=lang_code.lower())
            if not iso_language:
                raise ValueError(f"Код языка '{lang_code}' не существует в международном стандарте ISO 639-1")
        return cleaned_langs

    @field_validator("license_country")
    @classmethod
    def validate_and_uppercase_country(cls, v: str) -> str:
        """
        Автоматически превращает 'kz ' или 'ru' в строго валидные 'KZ' и 'RU'.
        Защищает SQL-запросы в OnboardingService от пустых результатов.
        """
        return v.upper().strip()

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
        current_year = datetime.now().year
        # Добавляем динамическую защиту от слишком будущего года выпуска:
        if self.car_year > current_year + 1:
            raise ValueError(f"Год выпуска авто не может быть позже {current_year + 1}")

        if current_year - self.car_year > 15:
            raise ValueError("Автомобиль старше 15 лет не допускается к работе")
        return self

    @field_validator("experience_years")
    @classmethod
    def validate_experience(cls, v: int) -> int:
        if v < 3:
            raise ValueError("Минимальный стаж вождения для регистрации — 3 года")
        return v


class GlobalLanguageResponse(BaseModel):
    """Схема элемента международного языкового справочника Яндекс-стайл."""

    code: str = Field(..., description="ISO 639-1 код в верхнем регистре (RU, EN)")
    name: str = Field(..., description="Название языка")
    is_popular: bool = Field(..., description="Флаг популярности для разделения блоков во Flutter")


class OnboardingCountryPickerResponse(BaseModel):
    """Схема элемента выпадающего списка стран для мобильного приложения Flutter."""

    model_config = ConfigDict(from_attributes=True)

    iso_code: str = Field(..., description="Двухбуквенный международный ISO-код страны (RU, KZ, BY)")
    name: str = Field(..., description="Понятное название страны для отображения пользователю")
    is_popular: bool = Field(..., description="Флаг популярности для разделения блоков во Flutter")


class TripguideSurvey(BaseModel):
    """Анкета гида (Шаг 3) с поддержкой глобального стандарта ISO 639-1."""

    role_type: Literal[UserRole.TRIP_GUIDE] = UserRole.TRIP_GUIDE

    bio: str = Field(
        ..., min_length=20, max_length=1000, description="Рассказ о себе, опыте, ключевых маршрутах и фишках"
    )
    languages: list[str] = Field(
        default_factory=list,
        examples=[["RU", "EN"]],
        description="Список языков ведения экскурсий по международному стандарту ISO 639-1",
    )
    specialization: str = Field(..., min_length=2, max_length=255, examples=["Пешие походы"])
    photo_certificate: str | None = Field(
        None, min_length=10, max_length=500, description="Ссылка на фото лицензии в S3"
    )

    @field_validator("photo_certificate")
    @classmethod
    def validate_certificate_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_clean = v.strip()
        return v_clean if v_clean else None

    @field_validator("languages")
    @classmethod
    def validate_and_normalize_languages(cls, v: list[str]) -> list[str]:
        """
        ГЛОБАЛЬНАЯ ВАЛИДАЦИЯ: Проверяет коды языков по международному стандарту ISO 639-1.
        Поддерживает работу приложения в любой точке мира.
        """
        # 1. Очищаем пробелы и переводим в верхний регистр (стандарт ISO)
        cleaned_langs = [lang.strip().upper() for lang in v if lang.strip()]
        if not cleaned_langs:
            raise ValueError("Список поддерживаемых языков не может быть пустым")

        # 2. ДИНАМИЧЕСКАЯ ПРОВЕРКА ПО МЕЖДУНАРОДНОМУ РЕЕСТРУ
        for lang_code in cleaned_langs:
            # pycountry ожидает коды в нижнем регистре для стандарта alpha_2 (ru, en)
            iso_language = pycountry.languages.get(alpha_2=lang_code.lower())
            if not iso_language:
                raise ValueError(f"Код языка '{lang_code}' не существует в международном стандарте ISO 639-1")

        return cleaned_langs


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
    target_region_id: int = Field(..., description="ID операционного региона подачи заявки")
    target_role: UserRole = Field(..., description="Роль, на которую подана заявка")
    inn: str | None
    bank_type: BankType | None = None
    survey_payload: SupplierSurvey | TripguideSurvey = Field(..., discriminator="role_type")
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
    upload_data: S3PresignedPost = Field(
        ..., description="Данные для загрузки: url бакета и секретные поля авторизации"
    )
    file_url: str = Field(..., description="Будущая постоянная публичная ссылка на файл после загрузки")


class CancelCurrentApplicationResponse(ActionResponse):
    pass


class SubmitSurveyResponse(ActionResponse):
    pass


class OnboardingDraftResponse(BaseModel):
    """
    [ENTERPRISE STANDARD]: Финальная схема ответа черновика для мобильного приложения.
    Содержит все бизнес-поля (регион, банк, ИНН) и полиморфный payload анкеты.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    application_id: int = Field(..., description="ID текущей заявки в СУБД")
    status: OnboardingStatus = Field(..., description="Текущий статус онбординга (например, filling_survey)")
    target_role: UserRole = Field(..., description="Выбранная роль (supplier или trip_guide)")
    target_region_id: int = Field(..., description="ID операционного региона (хаба) начала деятельности")

    # ДОБАВЛЕНО ПОЛЕ БАНКА: Полная копия из OnboardingAppShort
    bank_type: BankType | None = Field(None, description="Тип банка, выбранный для юридической привязки")

    inn: str | None = Field(None, description="ИНН пользователя, верифицированный банком")

    # Магия Pydantic v2 для полиморфного payload
    payload: SupplierSurvey | TripguideSurvey | dict[str, object] = Field(
        default_factory=dict, description="Данные частично заполненного черновика анкеты"
    )


class OnboardingFileType(StrEnum):
    """Список всех типов файлов документов для онбординга."""

    PHOTO_SELFIE = "photo_selfie"
    PHOTO_CAR_SIDE = "photo_car_side"
    PHOTO_CAR_INTERIOR = "photo_car_interior"
    PHOTO_CAR_FRONT = "photo_car_front"
    PHOTO_CAR_BACK = "photo_car_back"
    PHOTO_STS_FRONT = "photo_sts_front"
    PHOTO_STS_BACK = "photo_sts_back"
    PHOTO_LICENSE = "photo_license"
    PHOTO_CERTIFICATE = "photo_certificate"


ROLE_SURVEY_SCHEMAS = {
    "supplier": SupplierSurvey,
    "trip_guide": TripguideSurvey,
}


ROLE_ALLOWED_PHOTOS = {
    UserRole.SUPPLIER: {
        OnboardingFileType.PHOTO_SELFIE,
        OnboardingFileType.PHOTO_CAR_SIDE,
        OnboardingFileType.PHOTO_CAR_INTERIOR,
        OnboardingFileType.PHOTO_CAR_FRONT,
        OnboardingFileType.PHOTO_CAR_BACK,
        OnboardingFileType.PHOTO_STS_FRONT,
        OnboardingFileType.PHOTO_STS_BACK,
        OnboardingFileType.PHOTO_LICENSE,
    },
    UserRole.TRIP_GUIDE: {OnboardingFileType.PHOTO_CERTIFICATE},
}
