import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from packaging import version
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import credentials_exception
from app.core.jwt import ALGORITHM, SECRET_KEY
from app.infra.db_depends import get_db
from app.infra.redis import get_redis_client
from app.models.user import User
from app.services.auth_service import AuthService

# Логгер для слоя безопасности
logger = logging.getLogger("app.core.security")


security_scheme = HTTPBearer()


async def get_current_user(
    auth: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    r: Annotated[Redis, Depends(get_redis_client)],
) -> User:
    """
    Главная зависимость для получения текущего пользователя.
    Реализована по принципам Clean Architecture.
    """
    token = auth.credentials
    auth_service = AuthService(db, r)

    try:
        # 1. ПРОВЕРКА ВЕРСИИ ПРИЛОЖЕНИЯ
        client_version = request.headers.get("X-App-Version", "1.0.0")
        try:
            if version.parse(client_version) < version.parse(settings.app.min_app_version):
                raise HTTPException(
                    status_code=status.HTTP_426_UPGRADE_REQUIRED,
                    detail={"message": "Необходимо обновить приложение", "min_version": settings.app.min_app_version},
                )
        except version.InvalidVersion:
            logger.warning(f"Неверный формат версии: {client_version}")

        # 2. ДЕКОДИРОВАНИЕ И ПРОВЕРКА ТИПА ТОКЕНА
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        u_id, s_id = payload.get("id"), payload.get("jti")

        if payload.get("type") != "access":
            logger.warning(f"Попытка доступа с типом токена {payload.get('type')}. User: {u_id}")
            raise credentials_exception

        # 3. ВАЛИДАЦИЯ ДОСТУПА (Бизнес-логика делегирована сервису)
        # Метод проверяет Redis, бан, активность и удаление
        user = await auth_service.validate_user_access(u_id, s_id)

        # 4. ФОНОВОЕ ОБНОВЛЕНИЕ АКТИВНОСТИ (Раз в 5 минут)
        now = datetime.now(UTC)
        last_active = user.last_active or (now - timedelta(minutes=10))

        if (now - last_active).total_seconds() > 300:
            background_tasks.add_task(auth_service.update_user_activity_bg, u_id, client_version)

        # Прокидываем SID для управления сессией
        user.current_session_id = s_id
        return user

    except JWTError:
        raise credentials_exception from None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Критическая ошибка в get_current_user: {e}", exc_info=True)
        raise credentials_exception from None


async def get_current_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Проверка прав администратора через уровень доступа (>= 50)."""
    # Суперюзер (100) тоже пройдет эту проверку автоматически
    if user.level < 50:
        logger.warning(f"Доступ запрещен: пользователь {user.id} с уровнем {user.level} не админ.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Доступ запрещен: требуются права администратора"
        )
    return user
