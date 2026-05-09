import pytest
import requests
import responses

from app.config.settings import settings
from app.workers.auth.tasks import send_flash_call_task


@responses.activate
def test_send_flash_call_success():
    phone = "+79001112233"
    code = "1234"

    # Берем URL прямо из конфига, чтобы он точно совпал
    api_url = settings.sigma.api_url

    responses.add(responses.POST, api_url, json={"id": "msg_123"}, status=200)

    result = send_flash_call_task(phone, code)
    assert result["status"] == "success"


@responses.activate
def test_send_flash_call_retry_on_500(mocker):
    # Исправляем путь к таске для мока
    mock_retry = mocker.patch("app.workers.auth.tasks.send_flash_call_task.retry")
    # Передаем исключение, чтобы не было ошибки типа
    mock_retry.side_effect = Exception("retry_called")

    responses.add(responses.POST, settings.sigma.api_url, status=500)

    with pytest.raises(Exception, match="retry_called"):
        send_flash_call_task("+79001112233", "1234")

    assert mock_retry.called


@responses.activate
def test_send_flash_call_retries_on_network_error(mocker):
    # 1. Мокаем метод retry у задачи
    # Используем side_effect, чтобы "прервать" выполнение таски при вызове retry
    mock_retry = mocker.patch("app.workers.auth.tasks.send_flash_call_task.retry")
    mock_retry.side_effect = Exception("Retry triggered")

    # 2. Имитируем сетевой сбой (requests выбросит ConnectionError)
    responses.add(responses.POST, settings.sigma.api_url, body=requests.exceptions.ConnectionError("Network fail"))

    # 3. Вызываем задачу. Она должна поймать ConnectionError и вызвать retry()
    # который выбросит наше исключение "Retry triggered"
    with pytest.raises(Exception, match="Retry triggered"):
        send_flash_call_task("+79000000000", "1234")

    # 4. Проверяем, что Celery реально пытался сделать ретрай
    assert mock_retry.called
    # Можно даже проверить, с каким таймаутом (у тебя в коде 15 сек для сетевых ошибок)
    assert mock_retry.call_args.kwargs["countdown"] == 15
