import asyncio
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request
from jose import jwt

from app.core.jwt import ALGORITHM, SECRET_KEY, create_tokens, get_session_info


class TestJWTCore:
    @pytest.fixture(autouse=True)
    async def clear_redis(self, redis_client):
        await redis_client.flushdb()
        return

    # --- ТЕСТЫ get_session_info ---

    def test_get_session_info_real_ip_from_x_forwarded(self):
        """Проверка IP из X-Forwarded-For (убрали async и маркер asyncio)"""
        request = MagicMock(spec=Request)
        request.headers = {
            "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            "x-forwarded-for": "192.168.1.50",
        }
        device, ip = get_session_info(request)

        assert ip == "192.168.1.50"
        # Проверяем наличие ключевых слов ОС, так как парсер может выдать 'Mobile Safari'
        assert "iOS" in device or "iPhone" in device or "Mobile" in device

    def test_get_session_info_fallback_to_client_host(self):
        request = MagicMock(spec=Request)
        request.headers = {"user-agent": "Postman"}
        request.client = MagicMock()
        request.client.host = "172.20.10.2"

        _, ip = get_session_info(request)
        assert ip == "172.20.10.2"

    # --- ТЕСТЫ create_tokens (Безопасность) ---
    @pytest.mark.asyncio
    async def test_create_tokens_deleted_user_raises(self, redis_client):
        """Дыра: Токен не должен выпускаться для удаленных аккаунтов."""
        # Явно задаем ВСЕ поля, которые попадают в JWT Payload
        user = MagicMock(
            id=1,
            phone="79991112233",
            role="user",
            is_superuser=False,
            is_banned=False,
            is_active=True,
            deleted_at=datetime.now(),
        )
        with pytest.raises(HTTPException) as exc:
            await create_tokens(user, "Device", "127.0.0.1", redis_client)
        assert exc.value.status_code == 403

    # --- ТЕСТЫ Session Capping (Лимит устройств) ---
    @pytest.mark.asyncio
    async def test_session_capping_removes_oldest(self, redis_client):
        user = MagicMock(
            id=10, phone="799", role="u", is_active=True, is_banned=False, deleted_at=None, is_superuser=False
        )

        sids = []
        for i in range(3):
            _, ref = await create_tokens(user, f"D-{i}", f"I-{i}", redis_client, 2)
            sids.append(jwt.decode(ref, SECRET_KEY, algorithms=[ALGORITHM])["jti"])
            await asyncio.sleep(0.05)  # Важно для разных score

        # Проверка 1: В индексе должно остаться ровно 2 сессии
        count = await redis_client.zcard(f"user_sessions:{user.id}")
        assert count == 2

        # Проверка 2: Физический ключ первой сессии удален
        val = await redis_client.get(f"refresh:{user.id}:{sids[0]}")
        assert val is None, f"Сессия {sids[0]} не была удалена из Redis!"

        # --- ТЕСТЫ JWT Payload ---

    @pytest.mark.asyncio
    async def test_create_tokens_banned_user_raises(self, redis_client):
        """Проверка блокировки забаненного пользователя."""
        user = MagicMock(
            id=2,
            phone="79991112244",
            role="user",
            is_superuser=False,
            is_banned=True,
            is_active=True,
            deleted_at=None,
        )
        with pytest.raises(HTTPException) as exc:
            await create_tokens(user, "Device", "127.0.0.1", redis_client)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_tokens_payload_integrity(self, redis_client):
        user = MagicMock(
            id=55,
            phone="70000000000",
            role="admin",
            is_superuser=True,
            is_banned=False,
            is_active=True,
            deleted_at=None,
        )
        acc, ref = await create_tokens(user, "PC", "1.1.1.1", redis_client)

        acc_payload = jwt.decode(acc, SECRET_KEY, algorithms=[ALGORITHM])
        assert acc_payload["id"] == 55
        assert acc_payload["sub"] == "70000000000"
        assert acc_payload["type"] == "access"

    # --- ТЕСТЫ Redis Persistence ---
    @pytest.mark.asyncio
    async def test_create_tokens_redis_data_structure(self, redis_client):
        """Проверка, что метаданные сессии в Redis сохраняются корректно в JSON."""
        user = MagicMock(
            id=1, phone="79991112233", role="user", is_superuser=False, is_banned=False, is_active=True, deleted_at=None
        )

        _, ref = await create_tokens(user, "Android Phone", "8.8.8.8", redis_client)
        payload = jwt.decode(ref, SECRET_KEY, algorithms=[ALGORITHM])
        sid = payload["jti"]

        # Достаем из Redis
        raw_data = await redis_client.get(f"refresh:{user.id}:{sid}")
        assert raw_data is not None

        data = json.loads(raw_data)
        assert data["device"] == "Android Phone"
        assert data["ip"] == "8.8.8.8"
        assert data["user_id"] == 1
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_tokens_pipeline_transaction(self, redis_client):
        """Проверка, что TTL для индекса сессий устанавливается."""
        user = MagicMock(
            id=1, phone="7", role="u", is_superuser=False, is_banned=False, is_active=True, deleted_at=None
        )
        await create_tokens(user, "D", "I", redis_client)

        # Проверяем, что у индекса сессий есть TTL (не -1)
        ttl = await redis_client.ttl(f"user_sessions:{user.id}")
        assert ttl > 0
