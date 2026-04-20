import logging

import httpx

from app.config.settings import settings

# Настраиваем логгер для инфраструктуры
logger = logging.getLogger("app.infra.httpx")

# Используем правильный конфиг (HttpxClientConfig)
conf = settings.httpx_client

logger.info(
    f"Инициализация Singleton HTTPX Client: timeout={conf.timeout}s, "
    f"max_conn={conf.max_connections}, keep-alive={conf.max_keepalive}"
)

# Создаем один клиент на все приложение (Singleton)
httpx_client = httpx.Client(
    # ИСПОЛЬЗУЕМ conf ЗДЕСЬ:
    timeout=conf.timeout,
    limits=httpx.Limits(
        max_connections=conf.max_connections,
        max_keepalive_connections=conf.max_keepalive,
    ),
    http2=True,  # SigmaSMS это поддерживает, будет работать быстрее
    follow_redirects=True,  # Хорошая практика для внешних API
)
