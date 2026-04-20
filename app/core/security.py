import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from packaging import version
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as ua_parse

from app.config.settings import settings
from app.infra.db_depends import get_db
from app.infra.redis import get_redis_client
from app.models.user import User

# Логгер для слоя безопасности
logger = logging.getLogger("app.core.security")

SECRET_KEY = settings.auth.secret_key.get_secret_value()
ALGORITHM = settings.auth.algorithm
ACCESS_EXPIRE = settings.auth.access_token_expire_minutes
REFRESH_EXPIRE = settings.auth.refresh_token_expire_days

security_scheme = HTTPBearer()

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Не удалось подтвердить учетные данные",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_session_info(request: Request) -> tuple[str, str]:
    """Извлечение данных об устройстве для логирования и безопасности."""
    ua = ua_parse(request.headers.get("user-agent", "Unknown Device"))
    device = f"{ua.os.family} {ua.os.version_string} / {ua.browser.family}"
    x_forwarded = request.headers.get("x-forwarded-for")
    ip = x_forwarded.split(",")[0] if x_forwarded else request.client.host
    return device, ip


async def create_tokens(user: User, device_info: str, ip_address: str, r: Redis):
    """Генерация JWT и запись сессии в кэш."""
    now = datetime.now(UTC)
    s_id = str(uuid.uuid4())

    payload = {
        "sub": str(user.phone),
        "id": user.id,
        "jti": s_id,
        "is_admin": user.is_admin,
        "is_customer": user.is_customer,
        "is_supplier": user.is_supplier,
        "is_trip_guide": user.is_trip_guide,
    }

    access = jwt.encode(
        {**payload, "exp": now + timedelta(minutes=ACCESS_EXPIRE)},
        SECRET_KEY,
        ALGORITHM,
    )
    refresh = jwt.encode(
        {
            **payload,
            "type": "refresh",
            "exp": now + timedelta(days=REFRESH_EXPIRE),
        },
        SECRET_KEY,
        ALGORITHM,
    )

    metadata = {
        "refresh_token": refresh,
        "device": device_info,
        "ip": ip_address,
        "created_at": now.isoformat(),
    }

    # Запись в Redis
    await r.set(
        f"refresh:{user.id}:{s_id}",
        json.dumps(metadata),
        ex=timedelta(days=REFRESH_EXPIRE),
    )
    logger.info(f"Созданы новые токены для User ID: {user.id}")
    return access, refresh


async def get_current_user(
    auth: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    r: Annotated[Redis, Depends(get_redis_client)],
):
    token = auth.credentials
    try:
        # --- 1. ПРОВЕРКА ВЕРСИИ ПРИЛОЖЕНИЯ (FORCE UPDATE) ---
        client_version = request.headers.get("X-App-Version", "1.0.0")
        min_version = settings.app.min_app_version  # Берём из нашего AppConfig

        if version.parse(client_version) < version.parse(min_version):
            logger.warning(
                f"Force Update: Юзер с версией {client_version} заблокирован. "
                f"Минимальная версия: {min_version}"
            )
            raise HTTPException(
                status_code=status.HTTP_426_UPGRADE_REQUIRED,
                detail={
                    "message": "Необходимо обновить приложение",
                    "min_version": min_version,
                    "update_url": "https://google.com",  # Ссылка на Store
                },
            )

        # --- 2. ДЕКОДИРОВАНИЕ JWT ---
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        u_id, s_id = payload.get("id"), payload.get("jti")

        # --- 3. ВАЛИДАЦИЯ СЕССИИ В REDIS ---
        if not u_id or not s_id or not await r.exists(f"refresh:{u_id}:{s_id}"):
            logger.warning(f"Отказ в доступе: Сессия не найдена. User ID: {u_id}")
            raise credentials_exception

        # --- 4. ПРОВЕРКА ПОЛЬЗОВАТЕЛЯ И БАНА ---
        user = await db.get(User, u_id)
        if not user or user.is_banned:
            if user:
                await r.delete(f"refresh:{u_id}:{s_id}")
                logger.critical(f"Блокировка: Забаненный ID {u_id} пытался войти")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")

        # --- 5. ОБНОВЛЕНИЕ АКТИВНОСТИ (ФОНОМ) ---
        try:
            upd = {
                "last_active": datetime.now(UTC),
                "app_version": client_version,  # Сохраняем актуальную версию юзера
            }
            await db.execute(update(User).where(User.id == u_id).values(**upd))
            await db.commit()
        except SQLAlchemyError as db_err:
            await db.rollback()
            logger.error(f"Ошибка обновления активности юзера {u_id}: {db_err}")

        return payload

    except JWTError as e:
        logger.warning(f"Ошибка JWT: {e}")
        raise credentials_exception from e
    except HTTPException:  # Пробрасываем наши 426 и 403 ошибки без изменений
        raise
    except Exception as e:
        logger.error(f"Сбой в get_current_user: {e}", exc_info=True)
        raise credentials_exception from e


# новый не тестируемый код
# async def get_current_user(
#     token: Annotated[str, Depends(oauth2_scheme)],
#     request: Request,
#     db: Annotated[AsyncSession, Depends(get_db)],
#     r: Annotated[Redis, Depends(get_redis_client)],
# ) -> User:  # <--- ТЕПЕРЬ ВОЗВРАЩАЕМ МОДЕЛЬ
#     try:
#         # 1. FORCE UPDATE (Версия приложения)
#         client_version = request.headers.get("X-App-Version", "1.0.0")
#         if version.parse(client_version) < version.parse(settings.app.min_app_version):
#             raise HTTPException(
#                 status_code=status.HTTP_426_UPGRADE_REQUIRED,
#                 detail={
#                     "message": "Update required",
#                     "min_version": settings.app.min_app_version,
#                 },
#             )

#         # 2. ДЕКОДИРОВАНИЕ
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         u_id: int = payload.get("id")
#         s_id: str = payload.get("jti")

#         # 3. ВАЛИДАЦИЯ СЕССИИ (Redis)
#         session_key = f"refresh:{u_id}:{s_id}"
#         if not u_id or not s_id or not await r.exists(session_key):
#             raise credentials_exception

#         # 4. ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЯ
#         user = await db.get(User, u_id)
#         if not user or user.is_banned or not user.is_active:
#             await r.delete(session_key)  # Выкидываем из сессии сразу
#             raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступ запрещен")

#         # 5. ОПТИМИЗИРОВАННОЕ ОБНОВЛЕНИЕ АКТИВНОСТИ (Throttle)
#         # Обновляем БД только раз в 10 минут, чтобы не «убивать» Postgres
#         activity_cache_key = f"last_act:{u_id}"
#         if not await r.get(activity_cache_key):
#             try:
#                 user.last_active = datetime.now(UTC).replace(tzinfo=None)
#                 user.app_version = client_version
#                 await db.commit()
#                 # Ставим метку в Redis на 10 минут
#                 await r.set(activity_cache_key, "ok", ex=600)
#             except SQLAlchemyError as e:
#                 await db.rollback()
#                 logger.error(f"Activity update failed: {e}")

#         return user  # <--- Теперь в роутах работает автодополнение user.id, user.phone

#     except JWTError:
#         raise credentials_exception from e
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Auth error: {e}", exc_info=True)
#         raise credentials_exception from e
