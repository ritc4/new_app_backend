import pytest

from app.infra.redis import redis_pool


@pytest.mark.asyncio
async def test_full_auth_flow(client):
    test_phone = "79001112233"

    # 1. Запрос OTP
    response = await client.post("/api/v1/auth/request-otp", json={"phone": test_phone})
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # 2. Перехватываем код из Redis (имитируем получение SMS)
    otp_code = await redis_pool.get(f"otp:{test_phone}")
    assert otp_code is not None

    # 3. Верификация OTP и получение токенов
    verify_res = await client.post(
        "/api/v1/auth/verify-otp", json={"phone": test_phone, "code": otp_code}
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["is_new_user"] is True

    # 4. Проверка защищенного эндпоинта /me
    access_token = data["access_token"]
    me_res = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_res.status_code == 200
    assert me_res.json()["phone"] == test_phone
