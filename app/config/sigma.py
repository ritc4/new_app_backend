from pydantic import BaseModel, SecretStr


class SigmaConfig(BaseModel):
    token: SecretStr = SecretStr("")
    sender: SecretStr = SecretStr("test")
    api_url: str = "https://user.sigmasms.ru/api/sendings"
