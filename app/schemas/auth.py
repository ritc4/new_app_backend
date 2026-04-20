from pydantic import BaseModel, Field


class AppConfigResponse(BaseModel):
    min_required_version: str
    latest_version: str
    contact_support: str
    update_url: str


class OTPRequest(BaseModel):
    # Валидация формата телефона
    phone: str = Field(
        ...,
        pattern=r"^\+?[1-9]\d{1,14}$",
        description="Телефон в формате 79001234567",
        examples=["+79620000000"],
    )


class OTPVerifyRequest(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=6)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    is_new_user: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPairOnlyResponse(BaseModel):
    access_token: str
    refresh_token: str


class CompleteRegistrationRequest(BaseModel):
    first_name: str = Field(..., min_length=2, max_length=50)
    last_name: str | None = Field(None, max_length=50)


class UpdateUsernameRequest(BaseModel):
    # Валидация ника: латиница, цифры, подчеркивание
    username: str = Field(..., pattern=r"^[a-zA-Z0-9_]+$", min_length=3, max_length=20)


class SessionInfo(BaseModel):
    session_id: str
    device: str
    ip: str
    is_current: bool


class AdminChangePhoneRequest(BaseModel):
    target_user_id: int
    new_phone: str = Field(..., pattern=r"^\+?[1-9]\d{1,14}$")
