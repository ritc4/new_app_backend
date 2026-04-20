from app.api.v1 import v1_router  # Перенеси auth сюда
from app.config.settings import settings
from app.core.logging import setup_logging
from app.core.setup import create_app

setup_logging()

app = create_app()

# АВТОМАТИЗАЦИЯ: Префикс берется из настроек (/api/v1)
app.include_router(v1_router, prefix=settings.app.api_v1_str)

# Когда появится v2, ты просто добавишь:
# app.include_router(v2_router, prefix=settings.app.api_v2_str)
