import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from jose import jwt
from redis.asyncio import Redis
from user_agents import parse as ua_parse

from app.config.settings import settings
from app.models.user import User

# Логгер для слоя безопасности
logger = logging.getLogger("app.core.jwt")

# Константы из настроек
SECRET_KEY = settings.auth.secret_key.get_secret_value()
ALGORITHM = settings.auth.algorithm
ACCESS_EXPIRE = settings.auth.access_token_expire_minutes
REFRESH_EXPIRE = settings.auth.refresh_token_expire_days
MAX_SESSIONS_PER_USER = settings.redis.max_sessions_per_user

security_scheme = HTTPBearer()


def get_session_info(request: Request) -> tuple[str, str]:
    """Извлечение данных об устройстве для логирования и безопасности."""
    ua = ua_parse(request.headers.get("user-agent", "Unknown Device"))
    device = f"{ua.os.family} {ua.os.version_string} / {ua.browser.family}"
    x_forwarded = request.headers.get("x-forwarded-for")
    ip = x_forwarded.split(",")[0] if x_forwarded else request.client.host
    return device, ip


async def create_tokens(user: User, device_info: str, ip_address: str, r: Redis):
    """
    Генерация JWT и запись сессии в кэш.
    Использует ZSET для Session Capping (лимит устройств).
    """
    # 1. Проверка блокировки (КРИТИЧНО)
    if user.is_banned:
        logger.warning(f"Попытка входа заблокированного пользователя: {user.id}")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ваш аккаунт заблокирован")

    # 2. Проверка активности
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт деактивирован")

    # 3. Проверка на удаление
    if user.deleted_at:
        logger.warning(f"Попытка создать токен для удаленного пользователя: {user.id}")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт удален")

    now = datetime.now(UTC)
    s_id = str(uuid.uuid4())
    now_timestamp = int(now.timestamp())

    # Ключи Redis
    sessions_index_key = f"user_sessions:{user.id}"  # Индекс всех SID пользователя
    session_data_key = f"refresh:{user.id}:{s_id}"  # Данные конкретной сессии

    # 1. Лимит сессий (Session Capping) через Sorted Set
    # Добавляем текущую сессию в индекс (score = таймстамп)
    await r.zadd(sessions_index_key, {s_id: now_timestamp})

    # Получаем общее количество сессий
    session_count = await r.zcard(sessions_index_key)

    if session_count > MAX_SESSIONS_PER_USER:
        # Извлекаем SID самых старых сессий, которые выходят за лимит
        old_sids = await r.zrange(sessions_index_key, 0, session_count - MAX_SESSIONS_PER_USER - 1)
        if old_sids:
            # Удаляем данные сессий и записи из индекса
            data_keys_to_del = [f"refresh:{user.id}:{sid}" for sid in old_sids]
            await r.delete(*data_keys_to_del)
            await r.zrem(sessions_index_key, *old_sids)
            logger.info(f"Удалено старых сессий для User {user.id}: {len(old_sids)}")

    # 2. Подготовка Payload
    payload = {
        "sub": str(user.phone),
        "id": user.id,
        "jti": s_id,
        "role": user.role,
        "is_superuser": user.is_superuser,
    }

    # 3. Генерация токенов
    access = jwt.encode(
        {**payload, "type": "access", "exp": now + timedelta(minutes=ACCESS_EXPIRE)},
        SECRET_KEY,
        ALGORITHM,
    )
    refresh = jwt.encode(
        {**payload, "type": "refresh", "exp": now + timedelta(days=REFRESH_EXPIRE)},
        SECRET_KEY,
        ALGORITHM,
    )

    # 4. Сохранение данных сессии
    metadata = {
        "refresh_token": refresh,
        "device": device_info,
        "ip": ip_address,
        "created_at": now.isoformat(),
        "user_id": user.id,
    }

    async with r.pipeline(transaction=True) as pipe:
        await pipe.set(session_data_key, json.dumps(metadata), ex=timedelta(days=REFRESH_EXPIRE))
        # Продлеваем жизнь индекса сессий
        await pipe.expire(sessions_index_key, timedelta(days=REFRESH_EXPIRE))
        await pipe.execute()

    logger.info(f"Сессия создана: User ID {user.id}, SID {s_id}")
    return access, refresh
