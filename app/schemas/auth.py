from pydantic import BaseModel, Field


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


class SessionInfo(BaseModel):
    session_id: str
    device: str
    ip: str
    is_current: bool


class ActionResponse(BaseModel):
    """Универсальный ответ для действий без возврата данных (OTP, Logout и т.д.)"""

    status: str = "success"
    message: str
