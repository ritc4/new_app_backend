import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.services.auth_service import AuthService


@pytest.mark.asyncio
class TestAuthServiceFull:
    @pytest.fixture(autouse=True)
    async def clear_redis(self, redis_client):
        """Автоматическая очистка Redis перед каждым тестом."""
        await redis_client.flushdb()
        return

    # --- Тест лимитов OTP ---
    async def test_request_otp_daily_limit(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        phone, ip = "79991112233", "1.1.1.1"

        # Arrange: ставим лимит 10 (как в _check_otp_limits)
        await redis_client.set(f"limit:otp_daily:{phone}", 10)

        # Act & Assert
        with pytest.raises(HTTPException) as exc:
            await service.request_otp(phone, ip)
        assert exc.value.status_code == 429
        assert "Дневной лимит" in exc.value.detail

    # --- Тест Brute-force ---
    async def test_verify_otp_brute_force(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        phone = "79990000000"
        retry_key = f"limit:otp_retry:{phone}"

        # Arrange: имитируем 5 неудачных попыток
        await redis_client.set(retry_key, 5)

        # Act & Assert
        with pytest.raises(HTTPException) as exc:
            await service.verify_otp_code(phone, "1234")
        assert exc.value.status_code == 429

    # --- Тест Grace Period (Самое важное для UX) ---
    async def test_refresh_tokens_grace_period(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        user_id, sid = 1, "test_session"

        # Arrange: записываем "старые" токены в Grace Period
        from app.schemas.auth import GraceSessionData

        grace_data = GraceSessionData(access="new_access", refresh="new_refresh", is_new=False)
        await redis_client.set(f"grace_period:{user_id}:{sid}", grace_data.model_dump_json(), ex=60)

        # Mock JWT decode
        with patch("jose.jwt.decode", return_value={"id": user_id, "jti": sid, "type": "refresh"}):
            # Act
            result = await service.refresh_tokens("old_token_string", MagicMock())

            # Assert: должны получить данные из Grace, а не новые
            assert result.access_token == "new_access"
            assert result.refresh_token == "new_refresh"

    # --- Тест безопасности: Бан на лету ---
    async def test_validate_user_access_banned_real_time(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        user_id, sid = 99, "active_sid"

        # Arrange: Сессия в Redis есть
        await redis_client.set(f"refresh:{user_id}:{sid}", "some_data")

        # Мокаем пользователя как забаненного
        mock_user = MagicMock(id=user_id, is_banned=True, is_active=True, deleted_at=None)
        service.users.get_by_id = AsyncMock(return_value=mock_user)
        service.logout = AsyncMock()  # Чтобы не чистить реальный Redis

        # Act & Assert
        with pytest.raises(HTTPException) as exc:
            await service.validate_user_access(user_id, sid)

        assert exc.value.status_code == 403
        assert "заблокирован" in exc.value.detail
        # Проверяем, что система вызвала логаут для этой сессии
        service.logout.assert_called_once()

    # 1. ТЕСТ НА RACE CONDITION (Ошибка уникальности БД)
    async def test_login_or_register_integrity_error(self, db_session, redis_client):
        from app.services.auth_service import AuthService

        # Мокаем метод rollback прямо в объекте сессии
        db_session.rollback = AsyncMock()

        service = AuthService(db=db_session, redis_client=redis_client)
        service.users.get_by_phone_include_deleted = AsyncMock(return_value=None)
        service.users.create_with_phone = AsyncMock(side_effect=IntegrityError("stmt", "params", "orig"))

        request = MagicMock()
        request.headers = {"X-App-Version": "1.0.0"}

        with patch("app.services.auth_service.get_session_info", return_value=("Device", "1.1.1.1")):
            with pytest.raises(HTTPException) as exc:
                await service.login_or_register("79990001122", request)

            assert exc.value.status_code == 500
            # Теперь это сработает, так как мы подменили метод на мок
            db_session.rollback.assert_called()

    # 2. ТЕСТ НА ПРОТУХШИЕ СЕССИИ В СПИСКЕ (MGET вернул None)
    async def test_list_sessions_with_expired_keys(self, db_session, redis_client):
        from app.services.auth_service import AuthService

        service = AuthService(db=db_session, redis_client=redis_client)
        user = MagicMock(id=1)

        await redis_client.zadd(f"user_sessions:{user.id}", {"sid_active": 1, "sid_expired": 2})
        valid_data = json.dumps({"device": "PC", "ip": "1.1.1.1", "created_at": "2023-01-01T00:00:00"})
        await redis_client.set(f"refresh:{user.id}:sid_active", valid_data)

        result = await service.list_sessions(user, "sid_active")
        assert len(result) == 1

    # 3. ТЕСТ НА ЛИМИТ ПО IP (Злоумышленник меняет телефоны)
    async def test_otp_limit_by_ip_only(self, db_session, redis_client):
        """Проверка: блокировка OTP, если превышен лимит именно по IP."""
        from app.services.auth_service import AuthService

        service = AuthService(db=db_session, redis_client=redis_client)

        phone, ip = "79991112233", "192.168.1.1"
        # Лимит по IP забит, а по телефону — пусто
        await redis_client.set(f"limit:otp_req_ip:{ip}", "1")

        with pytest.raises(HTTPException) as exc:
            await service.request_otp(phone, ip)

        assert exc.value.status_code == 429
        assert "подождите минуту" in exc.value.detail

    # 4. ТЕСТ НА ОБНОВЛЕНИЕ IP/DEVICE ПРИ REFRESH
    async def test_rotate_session_updates_info(self, db_session, redis_client):
        from app.services.auth_service import AuthService

        service = AuthService(db=db_session, redis_client=redis_client)
        user = MagicMock(id=123, first_name="Ivan")

        # Чтобы logout не удалял наш grace_period в тесте, мокаем его
        service.logout = AsyncMock()

        request = MagicMock()
        with patch("app.services.auth_service.get_session_info", return_value=("NewPhone", "9.9.9.9")):
            with patch("app.services.auth_service.create_tokens", AsyncMock(return_value=("acc", "ref"))):
                await service._rotate_session(user, "old_sid", request)

                grace_raw = await redis_client.get(f"grace_period:{user.id}:old_sid")
                assert grace_raw is not None
                assert "acc" in grace_raw

    # 5. ТЕСТ НА ОШИБКУ ТИПА ТОКЕНА (Access вместо Refresh)
    async def test_refresh_tokens_wrong_type(self, db_session, redis_client):
        """Проверка: нельзя обновить сессию, используя Access Token."""
        from app.services.auth_service import AuthService

        service = AuthService(db=db_session, redis_client=redis_client)

        # Токен валидный, но тип "access"
        payload = {"id": 1, "jti": "sid", "type": "access"}

        with patch("jose.jwt.decode", return_value=payload):
            with pytest.raises(HTTPException) as exc:
                await service.refresh_tokens("valid_access_token", MagicMock())
            assert exc.value.status_code == 401

    # 6. ТЕСТ НА ИЗОЛЯЦИЮ ФОНОВОЙ ЗАДАЧИ
    async def test_update_activity_bg_silences_exception(self, db_session, redis_client):
        from app.services.auth_service import AuthService

        db_session.rollback = AsyncMock()  # Мокаем для проверки
        service = AuthService(db=db_session, redis_client=redis_client)

        service.users.update_activity = AsyncMock(side_effect=RuntimeError("DB Crashed"))

        # Не должно падать
        await service.update_user_activity_bg(1, "1.0.0")
        db_session.rollback.assert_called_once()

    async def test_verify_otp_expired(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        # Кода в Redis нет
        with pytest.raises(HTTPException) as exc:
            await service.verify_otp_code("79991112233", "1234")
        assert exc.value.status_code == 400
        assert "Неверный код" in exc.value.detail

    # 8. ТЕСТ: LOGOUT ALL (Массовая зачистка)
    async def test_logout_all_full_cleanup(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        user_id = 777
        # Создаем несколько сессий
        for i in range(3):
            sid = f"sid_{i}"
            await redis_client.zadd(f"user_sessions:{user_id}", {sid: i})
            await redis_client.set(f"refresh:{user_id}:{sid}", "data")
            await redis_client.set(f"grace_period:{user_id}:{sid}", "data")

        await service.logout_all(user_id)

        # Проверяем, что не осталось ничего
        keys = await redis_client.keys(f"*{user_id}*")
        assert len(keys) == 0

    # 9. ТЕСТ: КОРРЕКТНОСТЬ CONFIG
    async def test_get_app_config_structure(self, db_session, redis_client):
        service = AuthService(db=db_session, redis_client=redis_client)
        config = await service.get_app_config()
        assert hasattr(config, "min_required_version")
        assert hasattr(config, "latest_version")
