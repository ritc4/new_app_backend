import re
from enum import StrEnum

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import ActionResponse, UserBase


class AdminTargetRoleRequest(StrEnum):
    ADMIN = "admin"
    CUSTOMER = "customer"


class UserAdminView(UserBase):
    """Та же схема UserBase, но для глаз админа (без звездочек)."""

    pass


class AdminRoleChangeResponse(ActionResponse):
    """Ответ при успешном изменении роли пользователя."""

    user: UserAdminView


class AdminToggleBanResponse(ActionResponse):
    is_banned: bool | None = None
    user: UserAdminView


class AdminChangePhoneResponse(ActionResponse):
    """Ответ после принудительной смены номера телефона."""

    user: UserAdminView


class AdminApproveOnboardingResponse(ActionResponse):
    """Ответ при успешном одобрении партнера (водителя/гида)."""

    user: UserAdminView


class AdminRejectOnboardingResponse(ActionResponse):
    """Ответ при успешном отклонении заявки партнера."""

    user: UserAdminView
    application_id: int = Field(..., description="ID отклоненной заявки")
    reason: str = Field(..., description="Причина отклонения")


class CountryView(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int = Field(..., description="Сгенерированный СУБД числовой ID страны")
    iso_code: str
    name: str
    currency: str
    phone_code: str
    license_regex: str
    is_allowed_for_ru_onboarding: bool
    is_active: bool


class AdminCountryResponse(ActionResponse):
    country: CountryView = Field(..., description="Полные данные созданной страны")


class AdminCountryView(CountryView):
    """Представление данных страны в общем списке админ-панели."""

    pass


class AdminChangePhoneRequest(BaseModel):
    new_phone: str = Field(
        ...,
        description="Номер телефона в международном формате, например +79620001122",
    )

    @field_validator("new_phone")
    @classmethod
    def validate_phone_via_libphonenumber(cls, v: str) -> str:
        try:
            # Парсим номер телефона
            parsed_phone = phonenumbers.parse(v, None)

            # Проверяем, существует ли такой номер в плане нумерации стран мира
            if not phonenumbers.is_valid_number(parsed_phone):
                raise ValueError("Данный номер телефона не существует или имеет неверную длину")

            # Возвращаем строго отформатированную строку в формате E164 (+79620001122)
            return phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164)
        except Exception as e:
            if isinstance(e, ValueError):
                raise e
            raise ValueError("Неверный формат номера. Телефон должен начинаться с '+' и содержать код страны") from e


class AdminCountryCreate(BaseModel):
    iso_code: str = Field(
        ..., min_length=2, max_length=2, description="ISO-код страны", examples=["RU", "KZ", "BY", "AE"]
    )
    name: str = Field(..., min_length=2, max_length=100, examples=["ОАЭ"])
    currency: str = Field(..., min_length=3, max_length=3, examples=["AED"])
    phone_code: str = Field(..., min_length=2, max_length=5, examples=["+971"])
    license_regex: str = Field(r"^[0-9]{2,15}$", description="Регулярка для проверки прав новой страны")
    is_allowed_for_ru_onboarding: bool = Field(
        default=False, description="Разрешена ли работа в РФ по правам этой страны"
    )
    is_active: bool = Field(default=True)

    @field_validator("iso_code", mode="before")
    @classmethod
    def validate_iso(cls, v: str) -> str:
        # Сначала очищаем от пробелов и приводим к верхнему регистру,
        # чтобы проверка min_length/max_length отработала корректно
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        # Автоматически приводим валюту к верхнему регистру ("usd" -> "USD")
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("license_regex")
    @classmethod
    def validate_regex_syntax(cls, v: str) -> str:
        # Проверяем, компилируется ли регулярное выражение
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Невалидный синтаксис регулярного выражения: {e.msg}") from e
        return v
