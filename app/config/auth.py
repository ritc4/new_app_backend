from pydantic import BaseModel, SecretStr


class AuthConfig(BaseModel):
    # Эти значения Pydantic подтянет из NEW__APP__AUTH__...
    secret_key: SecretStr = SecretStr("98e1b09cfbc158e45950c3b6c32fd22b351d485eafc386978f2f26d8cd53987b")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 3650
