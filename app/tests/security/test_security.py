from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.jwt import ALGORITHM, SECRET_KEY
from app.core.security import get_current_admin, get_current_user  # Правильный импорт


@pytest.mark.asyncio
class TestAuthDependencies:
    # 1. ТЕСТ: УСТАРЕВШАЯ ВЕРСИЯ ПРИЛОЖЕНИЯ
    async def test_get_current_user_old_version(self):
        request = MagicMock()
        request.headers = {"X-App-Version": "0.1.0"}

        # Имитируем объект авторизации, чтобы get_current_user мог достать token
        auth_mock = MagicMock()
        auth_mock.credentials = "fake_token"

        # Патчим settings в модуле core.security
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.app.min_app_version = "1.0.0"

            with pytest.raises(HTTPException) as exc:
                await get_current_user(
                    auth=auth_mock,  # Передаем исправленный мок
                    request=request,
                    background_tasks=MagicMock(),
                    db=AsyncMock(),
                    r=AsyncMock(),
                )

            assert exc.value.status_code == 426
            # Проверяем, что в ответе есть подсказка о версии
            assert exc.value.detail["min_version"] == "1.0.0"

    # 2. ТЕСТ: ОБНОВЛЕНИЕ АКТИВНОСТИ (Background Task)
    async def test_get_current_user_triggers_activity_update(self):
        token = jwt.encode({"id": 1, "jti": "sid", "type": "access"}, SECRET_KEY, ALGORITHM)
        auth_creds = MagicMock(credentials=token)

        request = MagicMock()
        request.headers = {"X-App-Version": "1.1.0"}
        bg_tasks = MagicMock()

        mock_user = MagicMock(id=1, last_active=datetime(2000, 1, 1, tzinfo=UTC))

        # Патчим AuthService по правильному пути
        with patch("app.core.security.AuthService", autospec=True) as mock_auth_service:
            instance = mock_auth_service.return_value
            instance.validate_user_access = AsyncMock(return_value=mock_user)

            await get_current_user(
                auth=auth_creds, request=request, background_tasks=bg_tasks, db=AsyncMock(), r=AsyncMock()
            )

            bg_tasks.add_task.assert_called_once()

    # 3. ТЕСТ: ПРОВЕРКА УРОВНЯ АДМИНА (Критическая дыра)
    async def test_get_current_admin_logic(self):
        # 49 — еще не админ
        low_user = MagicMock(id=1, level=49)
        with pytest.raises(HTTPException) as exc:
            await get_current_admin(low_user)
        assert exc.value.status_code == 403

        # 50 — уже админ
        admin_user = MagicMock(id=2, level=50)
        result = await get_current_admin(admin_user)
        assert result == admin_user
