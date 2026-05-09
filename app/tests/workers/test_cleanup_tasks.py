from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_run_cleanup_orchestration(mocker):
    # 1. Готовим мок для UserService
    mock_user_service = AsyncMock()
    mock_user_service.perform_full_cleanup.return_value = {"deleted": 5}
    mocker.patch("app.workers.users.tasks.UserService", return_value=mock_user_service)

    # 2. Мокаем сессию БД (самое важное для 'async with')
    mock_session = AsyncMock()
    # Настраиваем, чтобы вызов async_session_maker() возвращал контекстный менеджер
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__.return_value = mock_session

    mocker.patch("app.workers.users.tasks.async_session_maker", mock_session_maker)

    # 3. Остальные зависимости
    mocker.patch("app.workers.users.tasks.get_s3_service", return_value=AsyncMock())
    mocker.patch("app.workers.users.tasks.AuthService")
    mocker.patch("app.workers.users.tasks.redis_pool")

    # 4. Выполняем
    from app.workers.users.tasks import run_cleanup

    report = await run_cleanup()

    # 5. Проверки
    assert report == {"deleted": 5}
    mock_user_service.perform_full_cleanup.assert_called_once()
