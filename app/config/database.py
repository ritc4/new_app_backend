from pydantic import BaseModel, SecretStr
from sqlalchemy import URL


class SQLAlchemyConfig(BaseModel):
    pool_size: int = 50
    max_overflow: int = 10
    echo: bool = False
    pool_recycle: int = 3600


class DatabaseConfig(BaseModel):
    name: str = "app_db"
    user: str = "postgres"
    password: SecretStr = SecretStr("")
    host: str = "localhost"
    port: int = 5432

    sqla: SQLAlchemyConfig = SQLAlchemyConfig()

    @property
    def async_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            database=self.name,
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
        )
