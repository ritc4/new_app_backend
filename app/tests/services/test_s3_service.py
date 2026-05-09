from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.s3_service import S3Service


@pytest.mark.asyncio
async def test_s3_delete_all_user_files(mocker):
    service = S3Service()

    # 1. Объект, который будет "клиентом" (s3 в коде сервиса)
    mock_s3_client = MagicMock()

    # Настраиваем пагинатор
    mock_paginator = MagicMock()
    # paginate возвращает объект, поддерживающий async for (через __aiter__)
    mock_paginator.paginate.return_value.__aiter__.return_value = [{"Contents": [{"Key": "user_1/avatar.jpg"}]}]
    mock_s3_client.get_paginator.return_value = mock_paginator

    # Настраиваем удаление как асинхронную функцию
    mock_s3_client.delete_objects = AsyncMock(return_value={})

    # 2. Объект, который является асинхронным контекстным менеджером
    # Это то, что возвращает `await self.session.client(...)`
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    # 3. Самое важное: патчим вызов метода client сессии
    # Мы заменяем его на AsyncMock, чтобы `await self.session.client(...)` вернул наш `mock_ctx`
    mocker.patch.object(service.session, "client", return_value=mock_ctx)

    # 4. Выполняем
    result = await service.delete_all_user_files(user_id=1)

    # 5. Проверки
    assert result is True
    mock_s3_client.delete_objects.assert_called_once()

    # Проверяем правильность удаления (удаляем до 1000 объектов)
    call_args = mock_s3_client.delete_objects.call_args
    assert call_args.kwargs["Delete"]["Objects"][0]["Key"] == "user_1/avatar.jpg"


@pytest.mark.asyncio
async def test_delete_file_by_url_parsing(mocker):
    service = S3Service()
    mock_execute = mocker.patch.object(service, "_execute_delete", return_value=True)

    url = f"{service.endpoint_url}/{service.bucket}/onboarding/user_1/photo.jpg"
    await service.delete_file_by_url(url, client=AsyncMock())

    # Проверяем, что ключ извлечен верно
    mock_execute.assert_called_once()
    assert mock_execute.call_args[0][1] == "onboarding/user_1/photo.jpg"
