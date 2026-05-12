from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ActionResponse
from app.schemas.user import UserShort


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


class OTPResponse(ActionResponse):
    """Ответ на запрос OTP. Содержит только статус и сообщение."""

    pass


class OTPVerifyRequest(BaseModel):
    phone: str = Field(
        ...,
        pattern=r"^\+?[1-9]\d{1,14}$",
        description="Телефон в формате 79001234567",
        examples=["+79620000000"],
    )
    # Оставляем только регулярку, если код всегда 4 цифры
    code: str = Field(..., pattern=r"^\d{4}$", examples=["7018"])


AUTH_STRATEGY = "bearer"


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = AUTH_STRATEGY
    is_new_user: bool


class GraceSessionData(BaseModel):
    """Внутренняя схема для типизации данных из Redis (Grace Period)."""

    access: str
    refresh: str
    is_new: bool


class AuthResult(BaseModel):
    access_token: str
    refresh_token: str
    is_new_user: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class CompleteRegistrationRequest(BaseModel):
    first_name: str = Field(..., pattern=r"^[^\s].*[^\s]$", min_length=2, max_length=50, examples=["Иван"])
    last_name: str | None = Field(None, max_length=50, examples=["Иванов"])


class RegistrationResponse(ActionResponse):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    user: UserShort  # Вкладываем существующую схему


class SessionInfo(BaseModel):
    session_id: str
    device: str
    ip: str
    is_current: bool
    created_at: str | None = None


class SessionData(BaseModel):
    device: str = "Unknown Device"
    ip: str = "Unknown IP"
    created_at: str | None = None


class LogoutResponse(ActionResponse):
    pass


class LogoutAllResponse(ActionResponse):
    pass
