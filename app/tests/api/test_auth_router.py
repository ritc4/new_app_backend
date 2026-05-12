import pytest

from app.core.dependencies.auth import get_auth_service
from app.main import app  # Импортируем для переопределения сервиса
from app.schemas.auth import AppConfigResponse, OTPResponse, TokenPairResponse


# 1. Мок сервис остается (только добавьте типы для чистоты)
class MockAuthService:
    async def get_app_config(self) -> AppConfigResponse:
        return AppConfigResponse(
            latest_version="1.0.0",
            min_required_version="1.0.0",
            contact_support="support@example.com",
            update_url="https://example.com",
        )

    async def request_otp(self, _phone: str, _ip: str) -> OTPResponse:
        return OTPResponse(status="ok", message="code sent")

    async def verify_otp_and_login(self, _payload, _request) -> TokenPairResponse:
        return TokenPairResponse(
            access_token="fake_access", refresh_token="fake_refresh", token_type="bearer", is_new_user=False
        )

    async def refresh_tokens(self, _refresh_token, _request) -> TokenPairResponse:
        return TokenPairResponse(
            access_token="new_access", refresh_token="new_refresh", token_type="bearer", is_new_user=False
        )


# 2. Локально подменяем AuthService
@pytest.fixture(autouse=True)
def override_auth_service():
    # Мы добавляем это в дополнение к глобальным переопределениям
    app.dependency_overrides[get_auth_service] = lambda: MockAuthService()
    yield
    # Удаляем только наше переопределение, чтобы не сломать глобальные
    del app.dependency_overrides[get_auth_service]


# 3. Сами тесты используют фикстуру 'client' из conftest.py
@pytest.mark.asyncio
async def test_get_app_config(client):
    response = await client.get("/api/v1/auth/config")
    assert response.status_code == 200

    data = response.json()
    # Если поля "version" нет, давайте проверим то, которое точно обязательно
    assert "latest_version" in data
    assert data["latest_version"] == "1.0.0"


@pytest.mark.asyncio
async def test_request_otp(client):
    response = await client.post("/api/v1/auth/request-otp", json={"phone": "79991234567"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_verify_otp(client):
    payload = {"phone": "79991234567", "code": "1234"}
    response = await client.post("/api/v1/auth/verify-otp", json=payload)
    assert response.status_code == 200
    assert response.json()["access_token"] == "fake_access"
