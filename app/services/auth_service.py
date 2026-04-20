import json
import logging
import secrets
from typing import Any

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    ALGORITHM,
    SECRET_KEY,
    create_tokens,
    credentials_exception,
    get_session_info,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import CompleteRegistrationRequest
from app.schemas.user import UserRole
from app.workers.auth.tasks import send_flash_call_task

# Иерархическое имя логгера для Enterprise-мониторинга
logger = logging.getLogger("app.services.auth")


class AuthService:
    def __init__(self, db: AsyncSession, redis_client: Redis):
        self.db = db
        self.redis = redis_client
        self.users = UserRepository(db)

    # --- РАБОТА С ПРОФИЛЕМ ---

    async def get_user_by_id(self, user_id: int) -> User:
        """Получение пользователя с логированием промахов."""
        user = await self.users.get_by_id(user_id)
        if not user:
            logger.warning(f"Пользователь ID {user_id} не найден.")
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
        return user

    async def complete_registration(
        self, user_id: int, data: CompleteRegistrationRequest
    ) -> User:
        """Завершение регистрации с защитой транзакции."""
        try:
            logger.info(f"Завершение регистрации для User ID {user_id}")
            user = await self.users.update_profile(
                user_id=user_id, first_name=data.first_name, last_name=data.last_name
            )
            logger.info(f"Профиль User ID {user_id} успешно обновлен.")
            return user
        except SQLAlchemyError as e:
            logger.error(f"Ошибка БД при обновлении профиля {user_id}: {e}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка сохранения данных"
            ) from e

    async def update_username(self, user_id: int, username: str) -> None:
        """Обновление ника с проверкой уникальности."""
        try:
            existing_user = await self.users.get_by_username(username)
            if existing_user and existing_user.id != user_id:
                logger.warning(f"Конфликт имен: ник '{username}' уже занят.")
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ник занят")

            await self.users.update_username(user_id, username)
            logger.info(f"User ID {user_id} сменил ник на '{username}'")
        except SQLAlchemyError as e:
            logger.error(f"Ошибка БД при смене ника для {user_id}: {e}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка обновления ника"
            ) from e

    # --- OTP ЛОГИКА ---

    async def _check_otp_limits(self, phone: str, ip: str) -> None:
        """Проверка лимитов для защиты от спама звонками."""
        if await self.redis.exists(f"limit:otp_req_phone:{phone}"):
            logger.warning(f"Лимит OTP превышен по номеру: {phone}")
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Слишком часто (номер)"
            )

        if await self.redis.exists(f"limit:otp_req_ip:{ip}"):
            logger.warning(f"Лимит OTP превышен по IP: {ip}")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком часто (IP)")

    async def request_otp(self, phone: str, ip: str) -> None:
        """Запрос OTP и постановка задачи в Celery."""

        logger.info(f"Запрос OTP: {phone} (IP: {ip})")
        await self._check_otp_limits(phone, ip)

        otp = "".join(str(secrets.randbelow(10)) for _ in range(4))

        await self.redis.set(f"otp:{phone}", otp, ex=300)
        await self.redis.set(f"limit:otp_req_phone:{phone}", "1", ex=60)
        await self.redis.set(f"limit:otp_req_ip:{ip}", "1", ex=20)

        send_flash_call_task.delay(phone, otp)
        logger.info(f"Задача Flash Call для {phone} отправлена в воркер.")

    async def verify_otp_code(self, phone: str, code: str) -> None:
        """Верификация с защитой от брутфорса."""
        retry_key = f"limit:otp_retry:{phone}"
        retries = await self.redis.get(retry_key)

        if retries and int(retries) >= 5:
            logger.error(f"Брутфорс OTP: превышено число попыток для {phone}")
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Много попыток. Бан 15 минут."
            )

        stored_otp = await self.redis.get(f"otp:{phone}")
        if not stored_otp or stored_otp != code:
            new_retries = await self.redis.incr(retry_key)
            if int(new_retries) == 1:
                await self.redis.expire(retry_key, 900)
            logger.warning(f"Неверный код для {phone}. Попытка №{new_retries}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный код")

        await self.redis.delete(retry_key)
        await self.redis.delete(f"otp:{phone}")
        logger.info(f"OTP подтвержден успешно: {phone}")

    # --- ВХОД И СЕССИИ ---

    async def login_or_register(
        self, phone: str, request: Request
    ) -> tuple[str, str, bool]:
        """Автоматическая регистрация или вход."""
        try:
            app_version = request.headers.get("X-App-Version", "1.0.0")
            user = await self.users.get_by_phone(phone)

            if user and user.is_banned:
                logger.critical(f"Попытка входа забаненного пользователя: {phone}")
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")

            is_new = False
            if not user:
                logger.info(f"Регистрация нового пользователя: {phone}")
                is_new = True
                user = await self.users.create_with_phone(phone, app_version)
            else:
                logger.info(f"Вход User ID {user.id} ({phone})")
                await self.users.update_activity(user.id, app_version)
                if not user.first_name:
                    is_new = True

            device, ip = get_session_info(request)
            access, refresh = await create_tokens(user, device, ip, self.redis)
            return access, refresh, is_new
        except SQLAlchemyError as e:
            logger.error(f"Ошибка БД при входе/регистрации {phone}: {e}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка авторизации"
            ) from e

    async def refresh_tokens(
        self, refresh_token: str, request: Request
    ) -> tuple[str, str]:
        """Обновление токенов с проверкой сессии в Redis."""
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, [ALGORITHM])
            user_id, session_id = payload.get("id"), payload.get("jti")
            redis_key = f"refresh:{user_id}:{session_id}"

            stored = await self.redis.get(redis_key)
            if not stored or json.loads(stored).get("refresh_token") != refresh_token:
                logger.warning(f"Невалидный Refresh токен для User {user_id}")
                raise credentials_exception

            user = await self.get_user_by_id(user_id)
            if user.is_banned:
                await self.redis.delete(redis_key)
                logger.critical(f"Сессия прервана: User {user_id} забанен.")
                raise HTTPException(403, "Заблокировано")

            await self.redis.delete(redis_key)
            device, ip = get_session_info(request)
            access, new_refresh = await create_tokens(user, device, ip, self.redis)

            logger.info(f"Сессия обновлена: User {user_id}")
            return access, new_refresh
        except JWTError as e:
            logger.error(f"JWT Error при Refresh: {e}")
            raise credentials_exception from e

    async def set_user_role(
        self, current_user: dict, target_id: int, role: UserRole
    ) -> User:
        if not current_user.get("is_admin"):
            logger.warning(
                f"Пользователь {current_user.get('id')} пытался сменить роль без прав"
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав администратора")

        user = await self.get_user_by_id(target_id)

        # Обнуляем спец. роли (логика переключения)
        user.is_supplier = False
        user.is_trip_guide = False
        user.is_customer = False

        if role == UserRole.SUPPLIER:
            user.is_supplier = True
        elif role == UserRole.TRIP_GUIDE:
            user.is_trip_guide = True
        elif role == UserRole.CUSTOMER:
            user.is_customer = True
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверная роль")

        try:
            await self.db.commit()
            # Сбрасываем сессии, чтобы новые роли записались в JWT при следующем входе
            await self.logout_all({"id": target_id})
            logger.info(
                f"Админ {current_user['id']} установил роль {role} "
                f"пользователю {target_id}"
            )
            return user
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Ошибка БД при смене роли для {target_id}: {e}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось сохранить роль"
            ) from e

    async def toggle_user_ban(self, current_user: dict, target_id: int) -> bool:
        if not current_user.get("is_admin"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав")

        user = await self.get_user_by_id(target_id)
        if user.is_admin:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Администратора нельзя забанить"
            )

        user.is_banned = not user.is_banned

        try:
            await self.db.commit()
            # При смене статуса бана (особенно при блокировке) всегда сбрасываем сессии
            await self.logout_all({"id": target_id})

            status_str = "забанен" if user.is_banned else "разбанен"
            logger.info(
                f"Админ {current_user['id']} изменил статус: "
                f"пользователь {target_id} {status_str}"
            )
            return user.is_banned
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Ошибка БД при изменении бана для {target_id}: {e}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Ошибка обновления статуса блокировки",
            ) from e

    async def list_sessions(self, current_user: dict) -> list[dict[str, Any]]:
        """Безопасный список сессий через SCAN."""
        user_id, current_jti = current_user["id"], current_user["jti"]
        sessions = []
        async for key in self.redis.scan_iter(match=f"refresh:{user_id}:*"):
            data_raw = await self.redis.get(key)
            if data_raw:
                data = json.loads(data_raw)
                session_id = key.split(":")[-1]
                sessions.append(
                    {
                        "session_id": session_id,
                        "device": data["device"],
                        "ip": data["ip"],
                        "is_current": session_id == current_jti,
                    }
                )
        return sessions

    async def logout(self, current_user: dict) -> None:
        """Выход с текущего устройства."""
        u_id, s_id = current_user["id"], current_user["jti"]
        await self.redis.delete(f"refresh:{u_id}:{s_id}")
        logger.info(f"User {u_id} вышел (сессия {s_id})")

    async def logout_all(self, current_user: dict) -> None:
        """Сброс всех сессий пользователя."""
        user_id = current_user["id"]
        keys = [key async for key in self.redis.scan_iter(match=f"refresh:{user_id}:*")]
        if keys:
            await self.redis.delete(*keys)
        logger.info(f"Все сессии User {user_id} аннулированы ({len(keys)} шт.)")

    # --- АДМИН ПАНЕЛЬ ---

    async def admin_change_phone(
        self, current_user: dict, target_user_id: int, new_phone: str
    ) -> None:
        """Смена номера (только админ) с инвалидацией сессий."""
        if not current_user.get("is_admin"):
            logger.warning(
                f"User {current_user['id']} пытался выполнить админ-действие!"
            )
            raise HTTPException(403, "Нет прав")

        if await self.users.get_by_phone(new_phone):
            raise HTTPException(400, "Номер занят")

        await self.users.change_phone(target_user_id, new_phone)

        # Инвалидация сессий цели
        keys = [
            key
            async for key in self.redis.scan_iter(match=f"refresh:{target_user_id}:*")
        ]
        if keys:
            await self.redis.delete(*keys)
        logger.info(
            f"Админ {current_user['id']} изменил номер User {target_user_id}. "
            "Сессии сброшены."
        )

    async def delete_account(self, current_user: dict) -> None:
        """Полное удаление пользователя."""
        user_id = current_user["id"]
        try:
            await self.users.delete_user(user_id)
            keys = [
                key async for key in self.redis.scan_iter(match=f"refresh:{user_id}:*")
            ]
            if keys:
                await self.redis.delete(*keys)
            logger.warning(f"АККАУНТ УДАЛЕН: User {user_id}")
        except SQLAlchemyError as e:
            logger.error(f"Ошибка БД при удалении аккаунта {user_id}: {e}")
            raise HTTPException(500, "Ошибка удаления") from e
