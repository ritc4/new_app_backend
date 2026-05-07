import re

from pydantic import BaseModel, Field, field_validator

from app.schemas.user import UserRole, UserShort


class AdminSetRoleRequest(BaseModel):
    role: UserRole


class UserAdminView(UserShort):
    """Та же схема UserShort, но для глаз админа (без звездочек)."""

    @field_validator("phone", "email", mode="after")
    @classmethod
    def skip_masking(cls, v: str | None) -> str | None:
        return v  # Просто возвращаем оригинал из базы


class AdminActionResponse(BaseModel):
    status: str = "success"
    message: str
    user: UserAdminView


class AdminChangePhoneRequest(BaseModel):
    new_phone: str = Field(
        ..., description="Номер телефона в международном формате (от 7 до 15 цифр), например +79620001122"
    )

    @field_validator("new_phone")
    @classmethod
    def validate_phone_international(cls, v: str) -> str:
        # Паттерн: опциональный '+', первая цифра [1-9], затем от 6 до 14 цифр
        international_pattern = r"^\+?[1-9]\d{6,14}$"

        if not re.match(international_pattern, v):
            raise ValueError(
                "Некорректный формат номера. Используйте международный стандарт: "
                "от 7 до 15 цифр. Номер должен начинаться с '+' или цифры от 1 до 9."
            )
        return v
