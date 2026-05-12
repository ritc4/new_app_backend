from datetime import date, datetime

import pytest

from app.core.dependencies.onboarding import get_onboarding_service
from app.main import app
from app.schemas.onboarding import (
    BankType,  # Импортируем Enum для тестов
    BankWebhookPayloadResponse,
    CancelCurrentApplicationResponse,
    OnboardingLinkResponse,
    OnboardingUploadResponse,
    SubmitSurveyResponse,
)


# 1. Мок-сервис (Исправлен под ваши схемы OnboardingLinkResponse и OnboardingUploadResponse)
class MockOnboardingService:
    async def create_application(self, _user_id, _data) -> OnboardingLinkResponse:
        return OnboardingLinkResponse(status="ok", message="создано", link="https://tinkoff.ru")

    async def process_bank_webhook(self, _payload) -> BankWebhookPayloadResponse:
        return BankWebhookPayloadResponse(status="ok", message="обновлено")

    async def get_onboarding_upload_url(self, _user_id, _file_type, _content_type) -> OnboardingUploadResponse:
        return OnboardingUploadResponse(upload_data={"key": "value"}, file_url="https://s3.com")

    async def submit_survey(self, _user_id, _data) -> SubmitSurveyResponse:
        return SubmitSurveyResponse(status="success", message="отправлено")

    async def cancel_current_application(self, _user_id) -> CancelCurrentApplicationResponse:
        return CancelCurrentApplicationResponse(status="success", message="отменена")


@pytest.fixture(autouse=True)
def override_onboarding_service():
    app.dependency_overrides[get_onboarding_service] = lambda: MockOnboardingService()
    yield
    if get_onboarding_service in app.dependency_overrides:
        del app.dependency_overrides[get_onboarding_service]


BASE_URL = "/api/v1/onboarding"


@pytest.mark.asyncio
async def test_start_onboarding(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    payload = {
        "target_role": "supplier",
        "bank": BankType.T_BANK.value,  # Используем "t_bank", как в вашем Enum
    }
    response = await client.post(f"{BASE_URL}/start", json=payload, headers=headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_bank_webhook(client):
    payload = {
        "user_id": 1,
        "phone": "+79991234567",
        "inn": "1234567890",  # 10 цифр
        "full_name": "Иванов Иван Иванович",
    }
    response = await client.post(f"{BASE_URL}/webhook/bank", json=payload)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_upload_link(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    params = {"file_type": "photo_selfie", "content_type": "image/jpeg"}
    response = await client.get(f"{BASE_URL}/upload-link", params=params, headers=headers)
    assert response.status_code == 200
    # В схеме OnboardingUploadResponse два поля: upload_data и file_url
    data = response.json()
    assert "file_url" in data
    assert "upload_data" in data


@pytest.mark.asyncio
async def test_submit_survey(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    current_year = datetime.now().year

    # Payload, который удовлетворяет ВСЕМ вашим валидаторам SupplierSurvey
    payload = {
        "car_model": "Kia Rio",
        "car_year": current_year - 2,  # Машина свежая (пройдет ge=1990 и < 15 лет)
        "car_number": "А777АА77",  # Только разрешенные буквы
        "car_color": "Белый",
        "vin_number": "1234567890ABCDEFG",  # 17 символов, без I, O, Q
        "license_number": "9901123456",  # 10 цифр для RU
        "license_expiry_date": str(date(current_year + 5, 1, 1)),  # Будущая дата
        "license_country": "RU",
        "experience_years": 5,  # Больше 3 лет
        "photo_selfie": "id_1",
        "photo_car_front": "id_2",
        "photo_car_back": "id_3",
        "photo_sts_front": "id_4",
        "photo_sts_back": "id_5",
        "photo_license": "id_6",
    }
    response = await client.post(f"{BASE_URL}/submit-survey", json=payload, headers=headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cancel_onboarding(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    response = await client.delete(f"{BASE_URL}/cancel", headers=headers)
    assert response.status_code == 200
