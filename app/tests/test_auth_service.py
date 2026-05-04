import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.user import User
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_otp_limits_logic(db_session, redis_client):
    service = AuthService(db=db_session, redis_client=redis_client)
    phone = "+79990001122"
    ip = "127.0.0.1"

    # Очистим ключи перед тестом, если они есть
    await redis_client.delete(f"limit:otp_req_phone:{phone}", f"limit:otp_req_ip:{ip}", f"otp:{phone}")

    # 1. Первый запрос должен пройти успешно
    await service.request_otp(phone, ip)

    assert await redis_client.exists(f"otp:{phone}")
    assert await redis_client.exists(f"limit:otp_req_phone:{phone}")

    # 2. Второй запрос сразу после первого должен вызвать 429 ошибку
    with pytest.raises(HTTPException) as excinfo:
        await service.request_otp(phone, ip)

    assert excinfo.value.status_code == 429
    assert "Слишком часто" in excinfo.value.detail


@pytest.mark.asyncio
async def test_verify_otp_and_register_logic(db_session, redis_client):
    service = AuthService(db=db_session, redis_client=redis_client)
    phone = "+79001112233"
    code = "1234"

    # 1. Подготовка: кладем код в Redis
    await redis_client.set(f"otp:{phone}", code, ex=60)

    # 2. Имитируем запрос от FastAPI (Request)
    # Создаем пустой объект запроса для работы get_session_info
    mock_request = type(
        "MockRequest",
        (),
        {
            "headers": {"user-agent": "Mozilla/5.0", "X-App-Version": "1.0.0"},
            "client": type("MockClient", (), {"host": "127.0.0.1"}),
        },
    )

    # 3. Проверяем код
    await service.verify_otp_code(phone, code)

    # 4. Входим или регистрируемся
    access, refresh, is_new = await service.login_or_register(phone, mock_request)

    # Проверки (Assertions)
    assert access is not None
    assert is_new is True  # Юзер новый, так как мы его только что создали

    result = await db_session.execute(select(User).where(User.phone == phone))
    user_in_db = result.scalar_one_or_none()

    assert user_in_db is not None
    assert user_in_db.phone == phone
