# import re

# from pydantic import BaseModel, Field, field_validator

# from app.schemas.user import UserRole, UserShort


from pydantic import BaseModel, Field

# class AdminSetRoleRequest(BaseModel):
#     role: UserRole


class AppConfigResponse(BaseModel):
    min_required_version: str
    latest_version: str
    contact_support: str
    update_url: str
    maintenance_mode: bool = False


class OTPRequest(BaseModel):
    # Валидация формата телефона
    phone: str = Field(
        ...,
        pattern=r"^\+?[1-9]\d{1,14}$",
        description="Телефон в формате 79001234567",
        examples=["+79620000000"],
    )


class OTPVerifyRequest(BaseModel):
    phone: str = Field(
        ...,
        pattern=r"^\+?[1-9]\d{1,14}$",
        description="Телефон в формате 79001234567",
        examples=["+79620000000"],
    )
    # Оставляем только регулярку, если код всегда 4 цифры
    code: str = Field(..., pattern=r"^\d{4}$", examples=["7018"])


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    is_new_user: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class CompleteRegistrationRequest(BaseModel):
    first_name: str = Field(..., pattern=r"^[^\s].*[^\s]$", min_length=2, max_length=50, examples=["Иван"])
    last_name: str | None = Field(None, max_length=50, examples=["Иванов"])


# class UpdateUsernameRequest(BaseModel):
#     # Валидация ника: латиница, цифры, подчеркивание
#     username: str = Field(..., min_length=3, max_length=20)

#     @field_validator("username")
#     @classmethod
#     def validate_username_format(cls, v: str):
#         if not re.match(r"^[a-zA-Z0-9_]+$", v):
#             raise ValueError("Никнейм может содержать только латиницу, цифры и подчеркивание")
#         return v


class SessionInfo(BaseModel):
    session_id: str
    device: str
    ip: str
    is_current: bool


# class AdminChangePhoneRequest(BaseModel):
#     new_phone: str = Field(
#         ..., description="Номер телефона в международном формате (от 7 до 15 цифр), например +79620001122"
#     )

#     @field_validator("new_phone")
#     @classmethod
#     def validate_phone_international(cls, v: str) -> str:
#         # Паттерн: опциональный '+', первая цифра [1-9], затем от 6 до 14 цифр
#         international_pattern = r"^\+?[1-9]\d{6,14}$"

#         if not re.match(international_pattern, v):
#             raise ValueError(
#                 "Некорректный формат номера. Используйте международный стандарт: "
#                 "от 7 до 15 цифр. Номер должен начинаться с '+' или цифры от 1 до 9."
#             )
#         return v


class ActionResponse(BaseModel):
    """Универсальный ответ для действий без возврата данных (OTP, Logout и т.д.)"""

    status: str = "success"
    message: str


# class AdminActionResponse(BaseModel):
#     status: str = "success"
#     message: str
#     user: UserShort


# class RejectApplicationRequest(BaseModel):
#     reason: str = Field(..., min_length=5, max_length=255, examples=["Плохое качество фото СТС"])
