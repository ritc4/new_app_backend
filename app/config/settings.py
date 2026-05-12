from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from app.config.app import AppConfig
from app.config.auth import AuthConfig
from app.config.celery import CeleryConfig
from app.config.database import DatabaseConfig
from app.config.db_redis import RedisConfig
from app.config.http import HttpConfig
from app.config.log_config import LoggingConfig
from app.config.rabbitmq import RabbitMQConfig
from app.config.s3 import S3Config
from app.config.sigma import SigmaConfig

# settings.py находится в app/config/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 1. parent = config/
# 2. parent.parent = app/
# 3. parent.parent.parent = корень проекта


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEW__APP__",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
        env_file=(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        yaml_config_section="app",
        yaml_file=(BASE_DIR / "default.yml"),
    )

    auth: AuthConfig = AuthConfig()
    app: AppConfig = AppConfig()
    db: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    rabbitmq: RabbitMQConfig = RabbitMQConfig()
    celery: CeleryConfig = CeleryConfig()
    sigma: SigmaConfig = SigmaConfig()
    s3: S3Config = S3Config()
    http: HttpConfig = HttpConfig()
    logging: LoggingConfig = LoggingConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            dotenv_settings,
            env_settings,
            file_secret_settings,
            YamlConfigSettingsSource(  # 4. Файл .yaml (НИЗКИЙ ПРИОРИТЕТ)
                settings_cls,
            ),
            # pydantic > 2.12.0 required
            # deep_merge=True)
        )


settings = Settings()
# print(settings)
# print(settings.model_dump_json(indent=2))
# print("db password:", settings.db.password.get_secret_value())
# print("Путь к .env:", BASE_DIR / ".env")
# print("db url:", str(settings.db.async_url))
# print("redis url:", str(settings.redis.url))
# print("redis url:", str(settings.redis.url))
# print(f"RabbitMQ URL: {settings.rabbitmq.url}")
# print(f"CORS Origins: {settings.http.cors_origins}")
# print("auth secret key:", settings.auth.secret_key.get_secret_value())
