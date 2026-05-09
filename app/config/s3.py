from pydantic import BaseModel, SecretStr


class S3Config(BaseModel):
    endpoint_url: str = "https://storage.yandexcloud.net"
    bucket_name: str = "default_bucket"
    access_key: SecretStr = SecretStr("") 
    secret_key: SecretStr = SecretStr("")
    region: str = "ru-central1"
