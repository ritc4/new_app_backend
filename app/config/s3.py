from pydantic import BaseModel, SecretStr


class S3Config(BaseModel):
    endpoint_url: str = "https://storage.yandexcloud.net"
    bucket_name: str = "default_bucket"  # Добавили дефолт
    access_key: SecretStr = SecretStr("")  # Добавили дефолт
    secret_key: SecretStr = SecretStr("")  # Добавили дефолт
    region: str = "ru-central1"
