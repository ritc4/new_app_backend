import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.admin import UserAdminView


class BankType(StrEnum):
    SBER = "sber"
    T_BANK = "t_bank"


class OnboardingStart(BaseModel):
    target_role: str  # supplier / trip_guide
    bank: BankType


class SupplierSurvey(BaseModel):
    """Анкета водителя (Шаг 3)."""

    car_model: str = Field(..., min_length=2, max_length=100, examples=["Kia Rio"])
    car_number: str = Field(..., min_length=6, max_length=15, examples=["А777АА77"])
    license_number: str = Field(..., min_length=8, max_length=20, examples=["9901 123456"])
    photo_car_front: str = Field(..., description="Фото авто спереди")
    photo_sts_front: str = Field(..., description="Фото СТС (лицевая)")
    photo_license: str = Field(..., description="Фото водительского удостоверения")

    @field_validator("car_number")
    @classmethod
    def validate_car_number(cls, v: str):
        # Простая проверка: только буквы и цифры, без спецсимволов
        if not re.match(r"^[A-Za-zА-Яа-я0-9\s]+$", v):
            raise ValueError("Некорректный формат госномера")
        return v.upper().replace(" ", "")


class TripguideSurvey(BaseModel):
    """Анкета гида (Шаг 3)."""

    bio: str = Field(..., min_length=20, max_length=1000, description="Рассказ о себе и опыте")
    languages: list[str] = Field(default_factory=list, examples=[["RU", "EN"]])
    specialization: str = Field(..., examples=["Пешие походы", "История архитектуры"])
    photo_certificate: str | None = None


class OnboardingAppShort(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    user_id: int
    target_role: str
    inn: str | None
    bank_type: str | None
    survey_payload: dict | None
    status: str
    admin_comment: str | None = Field(None, alias="onboarding_error")
    created_at: datetime
    # Теперь здесь полные данные без звездочек
    user: UserAdminView


class RejectApplicationRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=255, examples=["Плохое качество фото СТС"])
