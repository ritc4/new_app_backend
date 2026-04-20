from pydantic import BaseModel, SecretStr

class S3Config(BaseModel):
    endpoint_url: str = "https://yandexcloud.net"
    bucket_name: str = "default_bucket"      # Добавили дефолт
    access_key: str = "default_key"          # Добавили дефолт
    secret_key: SecretStr = SecretStr("") # Добавили дефолт