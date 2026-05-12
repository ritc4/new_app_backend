from pydantic import BaseModel


class AppConfig(BaseModel):
    title: str = "Transfer App"
    description: str = "API для сервиса трансферов и экскурсий"
    version: str = "1.0.0"
    api_v1_str: str = "/api/v1"
    contact_support: str = "https://t.me"
    update_url: str = "https://google.com"
    # Флаг, который определяет, работает ли приложение в режиме обслуживания
    maintenance_mode: bool = False

    # Минимальная версия Flutter приложения, которой разрешен вход
    # Если в .env будет NEW__APP__APP__MIN_APP_VERSION=1.1.0,
    # то пользователи с версией 1.0.0 увидят окно обновления.
    min_app_version: str = "1.0.0"
