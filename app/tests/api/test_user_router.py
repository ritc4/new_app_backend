from datetime import datetime

import pytest

from app.core.dependencies.auth import get_auth_service
from app.core.dependencies.user import get_user_service
from app.main import app


# Вспомогательная функция для сборки UserShort, чтобы не дублировать поля
def get_mock_user_short(role="customer"):
    now = datetime.now().isoformat()
    return {
        "id": 1,
        "uuid": "76c10cff-e2dc-4bf8-b74e-7e992cc54021",
        "phone": "+79991112233",  # Схема замаскирует это автоматически
        "first_name": "Иван",
        "last_name": "Иванов",
        "role": role,
        "is_active": True,
        "created_at": now,
        "last_active": now,
        "email": "ivan@example.com",
        "username": "ivan_ivanov",
    }


# 1. Мок для UserService (учитываем вложенность "user": {...})
class MockUserService:
    async def complete_registration(self, _uid, _data):
        return {"status": "ok", "message": "Регистрация завершена"}

    async def get_full_profile(self, _user):
        return {
            "user": get_mock_user_short(),
            "customer_data": {"onboarding_status": None, "admin_comment": None},
            "supplier_data": None,
            "trip_guide_data": None,
            "admin_data": None,
        }

    async def update_profile(self, _uid, _data):
        return {"status": "success", "message": "Обновлено", "user": get_mock_user_short()}

    async def update_username(self, _uid, _username):
        user = get_mock_user_short()
        user["username"] = _username
        return {"status": "success", "message": "Ник изменен", "user": user}

    async def update_email(self, _uid, _email):
        user = get_mock_user_short()
        user["email"] = _email
        return {"status": "success", "message": "Email изменен", "user": user}

    async def update_avatar(self, _user, _content_type):
        return {
            "status": "success",
            "message": "Ссылка создана",
            "upload_data": {"url": "https://s3.com", "fields": {"key": "value"}},
            "photo_url": "https://s3.com",
        }

    async def toggle_work_status(self, _user):
        return {"status": "success", "message": "Статус изменен", "is_available": True}

    async def delete_account(self, _user):
        return {
            "status": "success",
            "message": "Удален",
            "restore_until_days": 30,
            "restore_until_date": datetime.now().isoformat(),
            "user": get_mock_user_short(),
        }


# 2. Мок для AuthService (учитываем поля device и ip)
class MockAuthService:
    async def list_sessions(self, _user, _session_id):
        return [
            {
                "session_id": "sess_123",
                "device": "iPhone 15",
                "ip": "127.0.0.1",
                "is_current": True,
                "created_at": datetime.now().isoformat(),
            }
        ]

    async def logout(self, _uid, _sid):
        return {"status": "success", "message": "Вышли"}

    async def logout_all(self, _uid):
        return {"status": "success", "message": "Все сессии сброшены"}


@pytest.fixture(autouse=True)
def override_user_services():
    app.dependency_overrides[get_user_service] = lambda: MockUserService()
    app.dependency_overrides[get_auth_service] = lambda: MockAuthService()
    yield
    if get_user_service in app.dependency_overrides:
        del app.dependency_overrides[get_user_service]
    if get_auth_service in app.dependency_overrides:
        del app.dependency_overrides[get_auth_service]


BASE_URL = "/api/v1/users"


@pytest.mark.asyncio
async def test_read_me(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    response = await client.get(f"{BASE_URL}/me", headers=headers)
    assert response.status_code == 200
    # Проверяем вложенный объект user
    assert response.json()["user"]["first_name"] == "Иван"


@pytest.mark.asyncio
async def test_update_profile(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    payload = {"first_name": "Петр", "last_name": "Петров"}
    response = await client.patch(f"{BASE_URL}/me/update-profile", json=payload, headers=headers)
    assert response.status_code in [200, 403]
    if response.status_code == 200:
        assert "user" in response.json()


@pytest.mark.asyncio
async def test_get_avatar_link(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    response = await client.post(f"{BASE_URL}/me/avatar/upload-link?content_type=image/jpeg", headers=headers)
    assert response.status_code == 200
    assert "upload_data" in response.json()
    assert "photo_url" in response.json()


@pytest.mark.asyncio
async def test_list_sessions(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    response = await client.get(f"{BASE_URL}/me/sessions", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data[0]["device"] == "iPhone 15"
    assert data[0]["ip"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_logout(client, user_token):
    headers = {"Authorization": f"Bearer {user_token}"}
    response = await client.post(f"{BASE_URL}/me/logout", headers=headers)
    assert response.status_code == 200
