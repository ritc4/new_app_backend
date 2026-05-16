import logging
import secrets
import uuid

import phonenumbers
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import credentials_exception
from app.core.jwt import ALGORITHM, SECRET_KEY, create_tokens, get_session_info
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    AppConfigResponse,
    AuthResult,
    GraceSessionData,
    LogoutAllResponse,
    LogoutResponse,
    OTPResponse,
    OTPVerifyRequest,
    SessionData,
    SessionInfo,
    TokenPairResponse,
)

logger = logging.getLogger("app.services.auth")


class AuthService:
    def __init__(self, db: AsyncSession, redis_client: "Redis[str]") -> None:
        self.db = db
        self.redis = redis_client
        self.users = UserRepository(db)

    async def get_app_config(self) -> AppConfigResponse:
        """Для роутера /config"""
        return AppConfigResponse(
            min_required_version=settings.app.min_app_version,
            latest_version=settings.app.version,
            contact_support=settings.app.contact_support,
            update_url=settings.app.update_url,
            maintenance_mode=settings.app.maintenance_mode,
        )

    async def request_otp(self, phone: str, ip: str) -> OTPResponse:
        if settings.app.maintenance_mode:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Тех. обслуживание")

        # 1. Сначала проверяем жесткие лимиты (Wait limit и Daily)
        await self._check_otp_limits(phone, ip)

        # 2. Генерируем и сохраняем OTP
        otp = "".join(str(secrets.randbelow(10)) for _ in range(4))
        await self.redis.set(f"otp:{phone}", otp, ex=300)

        # 3. Устанавливаем лимиты ожидания и инкрементируем счетчик за день
        # Используем pipeline или просто последовательно, но лимиты ставим ПОСЛЕ успеха генерации
        await self.redis.set(f"limit:otp_req_phone:{phone}", "1", ex=60)
        await self.redis.set(f"limit:otp_req_ip:{ip}", "1", ex=60)

        daily_key = f"limit:otp_daily:{phone}"
        await self.redis.incr(daily_key)
        await self.redis.expire(daily_key, 86400, nx=True)  # Ставим expire только если ключа не было

        from app.workers.auth.tasks import send_flash_call_task

        send_flash_call_task.delay(phone, otp)

        return OTPResponse(status="success", message="Звонок выполняется.")

    async def verify_otp_and_login(self, payload: OTPVerifyRequest, request: Request) -> TokenPairResponse:
        """НОВЫЙ МЕТОД: Специально для чистого роутера /verify-otp"""
        # 1. Сначала проверяем код (вызывает метод из Части 2)
        await self.verify_otp_code(payload.phone, payload.code)

        # 2. Затем логиним/регистрируем
        result = await self.login_or_register(payload.phone, request)

        # 3. Возвращаем структуру для TokenPairResponse
        return TokenPairResponse(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            is_new_user=result.is_new_user,
        )

    async def refresh_tokens(self, refresh_token: str, request: Request) -> TokenPairResponse:
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, [ALGORITHM])
            user_id, session_id = payload.get("id"), payload.get("jti")
            if not isinstance(user_id, int) or not isinstance(session_id, str):
                raise credentials_exception

            if payload.get("type") != "refresh":
                raise credentials_exception

            # 1. Grace Period (Льготный период для повторных запросов)
            grace = await self._get_grace_session(user_id, session_id)
            if grace:
                return TokenPairResponse(
                    access_token=grace.access,
                    refresh_token=grace.refresh,
                    is_new_user=grace.is_new,
                )

            # 2. Валидация сессии и пользователя (Reuse Detection внутри)
            user = await self.validate_user_access(user_id, session_id)

            # 3. Ротация (Удаляем старую, создаем новую)
            return await self._rotate_session(user, session_id, request)

        except JWTError:
            raise credentials_exception from None

    # --- НОВОЕ: Методы для слоя безопасности (get_current_user) ---

    async def validate_user_access(self, user_id: int, session_id: str) -> User:
        """Бизнес-логика проверки доступа (Яндекс-стайл)."""

        # 1. Валидация сессии в Redis
        # Важно: используем явную проверку существования ключа
        session_exists = await self.redis.exists(f"refresh:{user_id}:{session_id}")
        if not session_exists:
            raise credentials_exception

        # 2. Получение пользователя
        user = await self.users.get_by_id(user_id)

        # Сначала проверяем физическое существование (Type Guard для MyPy)
        if not user:
            await self.logout(user_id, session_id)
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Аккаунт удален")

        # Теперь MyPy на 100% знает, что user — это объект класса User
        # 3. Проверка статусов (Бан, Удаление, Активность)
        is_invalid = user.is_banned or user.deleted_at is not None or not user.is_active

        if is_invalid:
            await self.logout(user_id, session_id)

            # Определяем детальную причину
            if not user.is_active:
                detail = "Аккаунт деактивирован"
            elif user.is_banned:
                detail = "Аккаунт заблокирован"
            else:
                detail = "Аккаунт удален"

            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)

        return user

    async def update_user_activity_bg(self, user_id: int, app_version: str) -> None:
        """Фоновая задача обновления активности."""
        try:
            await self.users.update_activity(user_id, app_version)
            await self.db.commit()
            logger.info(f"Активность пользователя {user_id} успешно обновлена.")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при обновлении активности пользователя {user_id}: {e}")

    async def login_or_register(self, phone: str, request: Request) -> AuthResult:
        if settings.app.maintenance_mode:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Тех. обслуживание")
        try:
            app_version = request.headers.get("X-App-Version", "1.0.0")
            device, ip = get_session_info(request)

            # 1. СТРОГАЯ НОРМАЛИЗАЦИЯ
            try:
                parsed_phone = phonenumbers.parse(phone, None)
                if not phonenumbers.is_valid_number(parsed_phone):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Некорректный номер телефона")
                normalized_phone = phonenumbers.format_number(parsed_phone, phonenumbers.PhoneNumberFormat.E164)
            except Exception:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный формат номера телефона") from None

            # 2. Проверяем существование пользователя в базе данных (включая soft-deleted)
            existing_user = await self.users.get_by_phone_include_deleted(normalized_phone)
            is_new = not bool(existing_user)

            # 3. ГЕО-ЛОГИКА: Определяем страну ТОЛЬКО если это новый или ранее удаленный пользователь
            if is_new or (existing_user and existing_user.deleted_at):
                # Получаем ISO-код страны (например: "RU", "KZ", "BY")
                iso_code = phonenumbers.region_code_for_number(parsed_phone)

                # ИСПРАВЛЕНИЕ ОШИБКИ 1: Защита от None для MyPy
                if not iso_code:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Не удалось определить регион для данного номера телефона",
                    )

                # Ищем ID страны в вашем репозитории по её ISO-коду
                country_id = await self.users.find_country_id_by_iso_code(iso_code)
                if not country_id:
                    logger.warning(
                        f"REGISTRATION_REJECTED: Unsupported country ISO '{iso_code}' for phone {normalized_phone}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Регистрация отклонена: регион ({iso_code}) не поддерживается платформой",
                    )
            else:
                # ИСПРАВЛЕНИЕ ОШИБКИ 2: Явный тайп-гард для MyPy через проверку на существование объекта
                if existing_user:
                    country_id = existing_user.country_id
                else:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

            # 4. Генерация username
            if is_new:
                temp_username = f"user_{str(uuid.uuid4())[:8]}"
            else:
                # ИСПРАВЛЕНИЕ ОШИБКИ 3: Явный тайп-гард для извлечения старого username
                if existing_user:
                    temp_username = existing_user.username or f"user_{str(uuid.uuid4())[:8]}"
                else:
                    temp_username = f"user_{str(uuid.uuid4())[:8]}"

            # 5. Создание или Восстановление (Upsert) в базе данных
            user = await self.users.create_with_phone(
                phone=normalized_phone, app_version=app_version, username=temp_username, country_id=country_id
            )

            if user.is_banned:
                logger.warning(f"BANNED_LOGIN_ATTEMPT: {normalized_phone} from {ip}")
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")

            await self.db.commit()

            # 6. Генерация сессии и пары токенов
            access, refresh = await create_tokens(user, device, ip, self.redis)
            return AuthResult(access_token=access, refresh_token=refresh, is_new_user=is_new)

        except HTTPException:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error(f"AUTH_CRITICAL_ERROR: {phone} - {str(e)}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка авторизации") from e

    # --- ВСПОМОГАТЕЛЬНЫЕ ПРИВАТНЫЕ МЕТОДЫ (Clean Code) ---

    async def _get_grace_session(self, user_id: int, session_id: str) -> GraceSessionData | None:
        data_raw = await self.redis.get(f"grace_period:{user_id}:{session_id}")
        if not data_raw:
            return None

        # ПРАВИЛЬНО: Парсим JSON сразу в схему. MyPy теперь знает типы полей.
        return GraceSessionData.model_validate_json(data_raw)

    async def _rotate_session(self, user: User, old_sid: str, request: Request) -> TokenPairResponse:
        device, ip = get_session_info(request)
        access, refresh = await create_tokens(user, device, ip, self.redis)
        is_new = not bool(user.first_name)

        # Сохраняем для Grace Period
        grace_data = GraceSessionData(access=access, refresh=refresh, is_new=is_new)
        await self.redis.set(
            f"grace_period:{user.id}:{old_sid}",
            grace_data.model_dump_json(),  # Сериализуем красиво
            ex=60,
        )

        await self.logout(user.id, old_sid)
        return TokenPairResponse(access_token=access, refresh_token=refresh, is_new_user=is_new)

    async def _check_otp_limits(self, phone: str, ip: str) -> None:
        """Проверка лимитов на создание OTP (Highload-оптимизация)."""

        # 1. Явно типизируем результат MGET для MyPy
        # redis.mget возвращает list[str | None]
        limits: list[str | None] = await self.redis.mget(f"limit:otp_req_phone:{phone}", f"limit:otp_req_ip:{ip}")

        # Распаковка (Type Safe)
        phone_limit, ip_limit = limits[0], limits[1]

        # 2. Проверка "Wait limit" (60 секунд между попытками)
        if phone_limit is not None or ip_limit is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много попыток. Пожалуйста, подождите минуту.",
            )

        # 3. Дневной лимит (макс 10 звонков в сутки)
        daily_count_raw = await self.redis.get(f"limit:otp_daily:{phone}")

        if daily_count_raw is not None:
            # Превращаем в int только после проверки на None
            if int(daily_count_raw) >= 10:
                logger.warning(f"DAILY_LIMIT_EXCEEDED: {phone}")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Дневной лимит попыток исчерпан",
                )

    async def verify_otp_code(self, phone: str, code: str) -> None:
        """Проверка кода с защитой от перебора (Brute-force)."""
        retry_key = f"limit:otp_retry:{phone}"

        # 1. Проверяем блокировку (Type Safe)
        retries_raw = await self.redis.get(retry_key)
        if retries_raw is not None:
            # Сначала в int, потом сравниваем. Явная проверка на None для MyPy.
            if int(retries_raw) >= 5:
                logger.warning(f"BRUTE_FORCE_ATTEMPT: {phone}")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Слишком много попыток. Доступ заблокирован на 15 минут.",
                )

        # 2. Сверяем код
        stored_otp = await self.redis.get(f"otp:{phone}")

        # secrets.compare_digest работает только со строками одинаковой длины или объектами bytes
        # Поэтому сначала проверяем наличие и тип
        if not stored_otp or not secrets.compare_digest(stored_otp, code):
            # Увеличиваем счетчик (incr возвращает int в асинхронном redis-py)
            new_retries: int = await self.redis.incr(retry_key)

            if new_retries == 1:
                await self.redis.expire(retry_key, 900)

            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный код подтверждения")

        # 3. Успех — атомарная зачистка
        await self.redis.delete(retry_key, f"otp:{phone}")
        logger.info(f"OTP_VERIFIED: {phone}")

    async def list_sessions(self, user: User, current_session_id: str | None) -> list[SessionInfo]:
        if current_session_id is None:
            raise HTTPException(status_code=401, detail="Сессия не найдена")

        # 1. Получаем SID. Redis[str] возвращает list[str]
        sids: list[str] = await self.redis.zrange(f"user_sessions:{user.id}", 0, -1)
        if not sids:
            return []

        # 2. Собираем ключи для MGET
        keys = [f"refresh:{user.id}:{sid}" for sid in sids]

        # ПРАВИЛЬНО: Результат MGET — список строк или None
        data_list: list[str | None] = await self.redis.mget(*keys)

        sessions: list[SessionInfo] = []

        # 3. Обработка через встроенный валидатор строк Pydantic
        for sid, data_raw in zip(sids, data_list, strict=True):
            # Если данных в Redis нет (протухли), пропускаем
            if data_raw is None:
                continue

            # ВАЖНО: Мы не делаем json.loads вручную!
            # Pydantic сам парсит строку и валидирует её. Никакого Any и cast.
            data = SessionData.model_validate_json(data_raw)

            session_obj = SessionInfo(
                session_id=sid,
                device=data.device,
                ip=data.ip,
                is_current=(sid == current_session_id),
                created_at=data.created_at,
            )
            sessions.append(session_obj)

        # 4. Сортировка по объектам
        return sorted(sessions, key=lambda x: (x.is_current, x.created_at or ""), reverse=True)

    async def logout(self, user_id: int, session_id: str | None) -> LogoutResponse:
        if not session_id:
            raise HTTPException(status_code=401, detail="Сессия не найдена")
        # Удаляем и данные, и индекс, и grace period
        keys_to_delete = [f"refresh:{user_id}:{session_id}", f"grace_period:{user_id}:{session_id}"]

        await self.redis.delete(*keys_to_delete)
        await self.redis.zrem(f"user_sessions:{user_id}", session_id)

        logger.info(f"USER_LOGOUT: User {user_id}, Session {session_id}")

        return LogoutResponse(status="success", message="Вы успешно вышли из системы")

    async def logout_all(self, user_id: int) -> LogoutAllResponse:
        """Полный логаут со всех устройств (Enterprise стандарт)."""
        index_key = f"user_sessions:{user_id}"

        # Явно типизируем sids как список строк
        sids: list[str] = await self.redis.zrange(index_key, 0, -1)

        if sids:
            # Формируем плоский список ключей
            keys_to_del: list[str] = []
            for sid in sids:
                keys_to_del.append(f"refresh:{user_id}:{sid}")
                keys_to_del.append(f"grace_period:{user_id}:{sid}")

            # Добавляем сам индекс в список на удаление
            keys_to_del.append(index_key)

            # Удаляем всё одним запросом
            await self.redis.delete(*keys_to_del)
            logger.info(f"Все сессии пользователя {user_id} аннулированы ({len(sids)} шт.)")

        # 2. Дополнительная зачистка (страховка)
        async for key in self.redis.scan_iter(match=f"refresh:{user_id}:*"):
            await self.redis.delete(key)

        return LogoutAllResponse(status="success", message="Вы успешно вышли со всех устройств")
