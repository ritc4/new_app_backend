from pydantic import BaseModel, SecretStr


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr = SecretStr("")

    @property
    def url(self) -> str:
        # Извлекаем реальное значение пароля через .get_secret_value()
        password_val = self.password.get_secret_value()

        # Если пароль пустой, не добавляем блок авторизации
        auth = f":{password_val}@" if password_val else ""

        return f"redis://{auth}{self.host}:{self.port}/{self.db}"
