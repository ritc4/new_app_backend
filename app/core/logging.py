import logging
import sys

from app.config.settings import settings


def setup_logging() -> None:
    """Настройка логирования для всего проекта"""

    # Формат логов (берем из твоего LoggingConfig)
    log_format = settings.logging.format
    log_level = settings.logging.log_level

    # Настройка корневого логгера
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),  # Логи в консоль (Docker их подхватит)
        ],
    )

    # Настройка специфичных логгеров
    # Логи SQLAlchemy (выключаем лишний шум, если не DEBUG)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.db.sqla.echo else logging.WARNING,
    )

    # Логи Alembic
    logging.getLogger("alembic").setLevel(logging.INFO)

    # Логи FastAPI / Uvicorn
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    logging.info(f"Logging initialized with level: {settings.logging.level}")
