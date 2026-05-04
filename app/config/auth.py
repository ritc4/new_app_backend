from pydantic import BaseModel, SecretStr


class AuthConfig(BaseModel):
    # Эти значения Pydantic подтянет из NEW__APP__AUTH__...
    secret_key: SecretStr = SecretStr("")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 3650
    