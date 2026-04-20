from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app.title,
        description=settings.app.description,
        version=settings.app.version,
    )

    # Настройка CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.http.cors_origins,
        allow_credentials=settings.http.cors_allow_credentials,
        allow_methods=settings.http.cors_methods,
        allow_headers=settings.http.cors_headers,
    )

    return app
