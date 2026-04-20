from pydantic import BaseModel, SecretStr

class RabbitMQConfig(BaseModel):
    host: str = "localhost"
    port: int = 5672
    user: str = "guest"
    password: SecretStr = SecretStr("")

    @property
    def url(self) -> str:
        # Извлекаем строку из SecretStr
        pw = self.password.get_secret_value()
        # Формируем URL. Если пароль есть, ставим его, если нет — оставляем только юзера
        auth = f"{self.user}:{pw}@" if pw else f"{self.user}@"
        return f"amqp://{auth}{self.host}:{self.port}//"