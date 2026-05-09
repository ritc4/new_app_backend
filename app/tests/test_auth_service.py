import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_otp_limits_logic(db_session: AsyncSession, redis_client: Redis) -> None:
    # Передаем аргумент под правильным именем 'redis_client'
    service = AuthService(db=db_session, redis_client=redis_client)

    phone = "+79990001122"
    ip = "127.0.0.1"

    # Очистка перед тестом
    await redis_client.delete(
        f"limit:otp_req_phone:{phone}", f"limit:otp_req_ip:{ip}", f"limit:otp_daily:{phone}", f"otp:{phone}"
    )

    # Имитируем достижение лимита
    await redis_client.set(f"limit:otp_daily:{phone}", 10)

    # Проверяем исключение
    with pytest.raises(HTTPException) as exc_info:
        await service.request_otp(phone, ip)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Дневной лимит исчерпан"
