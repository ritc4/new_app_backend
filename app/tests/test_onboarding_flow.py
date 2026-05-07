import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_onboarding_to_supplier_conversion(client: AsyncClient, test_user, user_token, admin_token):
    # 1. Банк подтверждает личность (Вебхук)
    bank_resp = await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={
            "user_id": test_user.id,
            "phone": test_user.phone,
            "inn": "123456789012",
            "full_name": "Иванов Иван Иванович",
        },
    )
    assert bank_resp.status_code == 200

    # 2. Юзер отправляет анкету машины
    survey_resp = await client.post(
        "/api/v1/onboarding/submit-survey",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "car_model": "Tesla Model 3",
            "car_number": "X777XX77",
            "license_number": "12345678",
            "experience_years": 3,
            "photo_car_front": "http://s3.com",
            "photo_sts_front": "http://s3.com",
            "photo_license": "http://s3.com",
        },
    )
    assert survey_resp.status_code == 200

    # 3. Админ одобряет (нужно сначала найти ID заявки)
    # В реальном тесте можно вытащить ID из базы или через GET /pending
    # Для простоты допустим ID = 1 (если база чистая)
    approve_resp = await client.patch(
        "/api/v1/permissions/onboarding/1/approve", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert approve_resp.status_code == 200

    # 4. Проверка смены роли в /me
    me_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {user_token}"})
    data = me_resp.json()
    assert data["user"]["role"] == "supplier"
    assert data["supplier_data"]["car_model"] == "Tesla Model 3"
