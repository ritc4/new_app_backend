from datetime import datetime
from uuid import uuid4

import pytest

from app.core.dependencies.admin import get_admin_service
from app.main import app
from app.schemas.base import UserRole
from app.schemas.onboarding import OnboardingStatus


# Вспомогательная функция для создания данных пользователя, чтобы не дублировать код
def get_mock_user_admin_view(role: UserRole = UserRole.CUSTOMER) -> dict[str, object]:
    now_iso = datetime.now().isoformat()
    return {
        "id": 100,
        "uuid": str(uuid4()),
        "phone": "+79991112233",
        "first_name": "Тест",
        "last_name": "Тестов",
        "role": role,
        "is_active": True,
        "created_at": now_iso,
        "last_active": now_iso
    }


# 1. Мок-сервис с учетом обязательного поля 'user' в AdminActionResponse
class MockAdminService:
    async def set_user_role(self, _admin, _user_uuid, role) -> dict:
        return {"status": "success", "message": "Роль изменена", "user": get_mock_user_admin_view(role=role)}

    async def toggle_user_ban(self, _admin, _user_uuid) -> dict:
        return {"status": "success", "message": "Статус изменен", "is_banned": True, "user": get_mock_user_admin_view()}

    async def admin_change_phone(self, _admin, _user_uuid, new_phone) -> dict:
        user_data = get_mock_user_admin_view()
        user_data["phone"] = new_phone
        return {"status": "success", "message": "Телефон изменен", "user": user_data}

    async def approve_partner_application(self, _admin, _app_id) -> dict:
        return {"status": "success", "message": "Одобрено", "user": get_mock_user_admin_view(role=UserRole.SUPPLIER)}

    async def reject_partner_application(self, _admin, _app_id, _reason) -> dict:
        return {"status": "success", "message": "Отклонено", "user": get_mock_user_admin_view()}

    async def get_pending_applications(self, _admin, _limit, _offset):
        return [
            {
                "id": 1,
                "user_id": 100,
                "target_role": "supplier",
                "status": OnboardingStatus.ON_MODERATION,
                "inn": "1234567890",
                "bank_type": "t_bank",
                "created_at": datetime.now().isoformat(),
                "user": get_mock_user_admin_view(),
            }
        ]


@pytest.fixture(autouse=True)
def override_admin_service():
    app.dependency_overrides[get_admin_service] = lambda: MockAdminService()
    yield
    if get_admin_service in app.dependency_overrides:
        del app.dependency_overrides[get_admin_service]


BASE_URL = "/api/v1/admin"


@pytest.mark.asyncio
async def test_set_user_role(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    u_uuid = uuid4()
    # ВАЖНО: role передается как Query параметр в твоем роутере
    response = await client.patch(f"{BASE_URL}/role/{u_uuid}?role={UserRole.ADMIN}", headers=headers)
    assert response.status_code == 200
    assert "user" in response.json()


@pytest.mark.asyncio
async def test_admin_change_phone(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    u_uuid = uuid4()
    payload = {"new_phone": "+79620001122"}  # Валидный формат по твоей схеме
    response = await client.post(f"{BASE_URL}/change-phone/{u_uuid}", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["user"]["phone"] == "+79620001122"


@pytest.mark.asyncio
async def test_list_pending_onboarding(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = await client.get(f"{BASE_URL}/onboarding/pending", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        assert "user" in data[0]  # Проверяем первый элемент списка
        assert data[0]["id"] == 1
