import json
import logging
import secrets

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import credentials_exception
from app.core.jwt import ALGORITHM, SECRET_KEY, create_tokens, get_session_info
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger("app.services.auth")


class AuthService:
    def __init__(self, db: AsyncSession, redis_client: Redis):
        self.db = db
        self.redis = redis_client
        self.users = UserRepository(db)

    # --- НОВОЕ: Методы для слоя безопасности (get_current_user) ---

    async def validate_user_access(self, user_id: int, session_id: str) -> User:
        """Бизнес-логика проверки доступа (используется в get_current_user)."""
        # 1. Валидация сессии в Redis
        if not await self.redis.exists(f"refresh:{user_id}:{session_id}"):
            raise credentials_exception

        # 2. Получение и проверка статуса пользователя
        user = await self.users.get_by_id(user_id)

        if not user or user.is_banned or user.deleted_at is not None or not user.is_active:
            if user_id:
                await self.logout(user_id, session_id)

            if user and not user.is_active:
                detail = "Аккаунт деактивирован"
            elif user and user.is_banned:
                detail = "Аккаунт заблокирован"
            else:
                detail = "Аккаунт удален"

            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)

        return user

    async def update_user_activity_bg(self, user_id: int, app_version: str):
        """Фоновая задача обновления активности."""
        try:
            await self.users.update_activity(user_id, app_version)
            await self.db.commit()
            logger.info(f"Активность пользователя {user_id} успешно обновлена.")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при обновлении активности пользователя {user_id}: {e}")

    # --- ОСНОВНЫЕ МЕТОДЫ СЕРВИСА ---

    async def request_otp(self, phone: str, ip: str) -> None:
        # 1. Сначала проверяем, не на тех.обслуживании ли мы
        if settings.app.maintenance_mode:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Сервис временно недоступен. Ведутся технические работы.",
            )

        await self._check_otp_limits(phone, ip)
        otp = "".join(str(secrets.randbelow(10)) for _ in range(4))

        await self.redis.set(f"otp:{phone}", otp, ex=300)
        await self.redis.set(f"limit:otp_req_phone:{phone}", "1", ex=60)
        await self.redis.set(f"limit:otp_req_ip:{ip}", "1", ex=60)

        # Инкрементируем дневной счетчик
        daily_key = f"limit:otp_daily:{phone}"
        await self.redis.incr(daily_key)
        await self.redis.expire(daily_key, 86400)
        from app.workers.auth.tasks import send_flash_call_task

        send_flash_call_task.delay(phone, otp)
        logger.info(f"Задача Flash Call для {phone} отправлена.")

    async def login_or_register(self, phone: str, request: Request) -> tuple[str, str, bool]:
        """
        Вход или регистрация.
        is_new=True только для тех, кого ВООБЩЕ нет в базе.
        """
        if settings.app.maintenance_mode:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Тех. обслуживание")

        try:
            app_version = request.headers.get("X-App-Version", "1.0.0")

            # 1. Ищем пользователя, включая удаленных (Soft Delete)
            existing_user = await self.users.get_by_phone_include_deleted(phone)

            # ОПРЕДЕЛЯЕМ НОВИЗНУ:
            # Если юзера нет в БД вообще — он НОВЫЙ.
            # Если юзер есть (даже удаленный) — он СТАРЫЙ (возвращенец).
            is_new = not bool(existing_user)

            # 2. Выполняем Upsert (Создание или Восстановление)
            # Этот метод в репозитории сбросит deleted_at в None, если юзер был удален
            user = await self.users.create_with_phone(phone, app_version)

            # 3. Проверка на бан (всегда важна)
            if user.is_banned:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")

            await self.db.commit()

            # Логирование для аналитики
            if is_new:
                logger.info(f"Новый пользователь: {phone}")
            elif existing_user and existing_user.deleted_at:
                logger.info(f"Пользователь ВОССТАНОВИЛСЯ после удаления: {phone}")
            else:
                logger.info(f"Обычный вход: {phone}")

            # 4. Генерация токенов
            device, ip = get_session_info(request)
            access, refresh = await create_tokens(user, device, ip, self.redis)

            # Фронтенд получит is_new=true только для абсолютно новых
            return access, refresh, is_new

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка входа {phone}: {e}")
            raise HTTPException(500, "Ошибка авторизации") from e

    async def refresh_tokens(self, refresh_token: str, request: Request) -> tuple[str, str, bool]:
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, [ALGORITHM])
            user_id, session_id = payload.get("id"), payload.get("jti")

            if payload.get("type") != "refresh":
                raise credentials_exception

            # 1. Grace Period (Льготный период для повторных запросов)
            grace_data = await self._get_grace_session(user_id, session_id)
            if grace_data:
                return grace_data

            # 2. Валидация сессии и пользователя (Reuse Detection внутри)
            user = await self.validate_user_access(user_id, session_id)

            # 3. Ротация (Удаляем старую, создаем новую)
            return await self._rotate_session(user, session_id, request)

        except JWTError:
            raise credentials_exception from None

    # --- ВСПОМОГАТЕЛЬНЫЕ ПРИВАТНЫЕ МЕТОДЫ (Clean Code) ---

    async def _get_grace_session(self, user_id: int, session_id: str) -> tuple | None:
        data_raw = await self.redis.get(f"grace_period:{user_id}:{session_id}")
        if data_raw:
            d = json.loads(data_raw)
            return d["access"], d["refresh"], d["is_new"]
        return None

    async def _rotate_session(self, user: User, old_sid: str, request: Request) -> tuple:
        device, ip = get_session_info(request)
        access, refresh = await create_tokens(user, device, ip, self.redis)
        is_new = not bool(user.first_name)

        # Сохраняем для Grace Period
        grace_data = {"access": access, "refresh": refresh, "is_new": is_new}
        await self.redis.set(f"grace_period:{user.id}:{old_sid}", json.dumps(grace_data), ex=60)

        await self.logout(user.id, old_sid)
        return access, refresh, is_new

    async def _check_otp_limits(self, phone: str, ip: str) -> None:
        """Проверка лимитов на создание OTP (Highload-оптимизация)."""
        # Используем MGET для экономии ресурсов (1 запрос вместо 2)
        phone_limit, ip_limit = await self.redis.mget(f"limit:otp_req_phone:{phone}", f"limit:otp_req_ip:{ip}")

        if phone_limit or ip_limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток")

        daily_count = await self.redis.get(f"limit:otp_daily:{phone}")
        if daily_count and int(daily_count) >= 10:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Дневной лимит исчерпан")

    async def verify_otp_code(self, phone: str, code: str) -> None:
        """Проверка кода с защитой от перебора (Brute-force)."""
        retry_key = f"limit:otp_retry:{phone}"

        # 1. Проверяем, не заблокирован ли юзер за перебор
        retries = await self.redis.get(retry_key)
        if retries and int(retries) >= 5:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Много попыток. Бан 15 минут.")

        # 2. Сверяем код
        stored_otp = await self.redis.get(f"otp:{phone}")

        if not stored_otp or not secrets.compare_digest(stored_otp, code):
            # Увеличиваем счетчик ошибок
            new_retries = await self.redis.incr(retry_key)
            if int(new_retries) == 1:
                await self.redis.expire(retry_key, 900)  # Бан 15 минут

            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный код")

        # 3. Успех — чистим лимиты
        await self.redis.delete(retry_key)
        await self.redis.delete(f"otp:{phone}")

    async def list_sessions(self, user: User, current_session_id: str) -> list[dict]:
        # 1. Получаем все активные SID пользователя из нашего ZSET
        sids = await self.redis.zrange(f"user_sessions:{user.id}", 0, -1)
        if not sids:
            return []

        # 2. Собираем ключи для MGET
        keys = [f"refresh:{user.id}:{sid}" for sid in sids]
        data_list = await self.redis.mget(*keys)

        sessions = []
        for sid, data_raw in zip(sids, data_list, strict=True):
            if not data_raw:
                continue

            data = json.loads(data_raw)
            sessions.append(
                {
                    "session_id": sid,
                    "device": data.get("device", "Unknown Device"),
                    "ip": data.get("ip", "Unknown IP"),
                    "is_current": sid == current_session_id,
                    "created_at": data.get("created_at"),
                }
            )

        return sorted(sessions, key=lambda x: (x["is_current"], x["created_at"]), reverse=True)

    async def logout(self, user_id: int, session_id: str) -> None:
        # Удаляем и данные, и индекс, и grace period
        await self.redis.delete(f"refresh:{user_id}:{session_id}")
        await self.redis.delete(f"grace_period:{user_id}:{session_id}")
        await self.redis.zrem(f"user_sessions:{user_id}", session_id)

    async def logout_all(self, user_id: int) -> None:
        """Полный логаут со всех устройств (Enterprise стандарт)."""
        index_key = f"user_sessions:{user_id}"

        # 1. Получаем все SID из индекса (Sorted Set)
        sids = await self.redis.zrange(index_key, 0, -1)

        if sids:
            # Формируем список ключей для удаления данных самих сессий
            keys_to_del = [f"refresh:{user_id}:{sid}" for sid in sids]

            # Также добавляем в список на удаление все записи Grace Period для этих сессий
            grace_keys = [f"grace_period:{user_id}:{sid}" for sid in sids]

            # Удаляем всё пачкой (БД Redis это любит)
            await self.redis.delete(*keys_to_del, *grace_keys, index_key)
            logger.info(f"Все сессии пользователя {user_id} аннулированы ({len(sids)} шт.)")

        # 2. Дополнительная зачистка (на случай старых сессий без индекса)
        # В Highload проектах SCAN используют аккуратно, но здесь это хорошая страховка
        async for key in self.redis.scan_iter(match=f"refresh:{user_id}:*"):
            await self.redis.delete(key)
