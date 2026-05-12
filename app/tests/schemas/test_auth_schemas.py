from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    AppConfigResponse,
    CompleteRegistrationRequest,
    OTPRequest,
    OTPVerifyRequest,
    RegistrationResponse,
    SessionData,
)
from app.schemas.user import UserShort


class TestAuthSchemas:
    # --- 1. ТЕСТЫ OTPRequest (Валидация телефона) ---
    @pytest.mark.parametrize("phone", ["79001234567", "+79001234567", "12345", "799988877665544"])
    def test_otp_request_phone_success(self, phone):
        schema = OTPRequest(phone=phone)
        assert schema.phone == phone

    @pytest.mark.parametrize(
        "phone",
        [
            "09001234567",  # Начинается с 0 (запрещено паттерном [1-9])
            "+0900",  # То же самое с плюсом
            "7900abc4567",  # Буквы
            "",  # Пусто
            " 79001234567",  # Пробел в начале
        ],
    )
    def test_otp_request_phone_error(self, phone):
        with pytest.raises(ValidationError):
            OTPRequest(phone=phone)

    # --- 2. ТЕСТЫ OTPVerifyRequest (Телефон + Код) ---
    def test_otp_verify_success(self):
        data = {"phone": "79001234567", "code": "1234"}
        schema = OTPVerifyRequest(**data)
        assert schema.code == "1234"

    @pytest.mark.parametrize("code", ["123", "12345", "abcd", "12 4"])
    def test_otp_verify_code_error(self, code):
        """Дыра: Код должен быть строго 4 цифрами."""
        with pytest.raises(ValidationError):
            OTPVerifyRequest(phone="79001234567", code=code)

    # --- 3. ТЕСТЫ CompleteRegistrationRequest (Имена) ---
    @pytest.mark.parametrize("name", ["Иван", "Д'Артаньян", "Анна-Мария"])
    def test_registration_name_success(self, name):
        schema = CompleteRegistrationRequest(first_name=name)
        assert schema.first_name == name

    @pytest.mark.parametrize(
        "name",
        [
            " Иван",  # Пробел в начале
            "Иван ",  # Пробел в конце
            " ",  # Только пробел
            "А",  # Слишком короткое (min_length=2)
            "И" * 51,  # Слишком длинное (max_length=50)
        ],
    )
    def test_registration_name_error(self, name):
        """Дыра: Имена не должны содержать ведущих пробелов или быть слишком короткими."""
        with pytest.raises(ValidationError):
            CompleteRegistrationRequest(first_name=name)

    # --- 4. ТЕСТ: Необязательность фамилии ---
    def test_registration_optional_last_name(self):
        # Должно работать без фамилии
        schema = CompleteRegistrationRequest(first_name="Иван")
        assert schema.last_name is None

        # Должно работать с фамилией
        schema_full = CompleteRegistrationRequest(first_name="Иван", last_name="Иванов")
        assert schema_full.last_name == "Иванов"

    def test_registration_response_mapping(self):
        # Имитируем данные пользователя
        user_data = {
            "uuid": uuid4(),
            "phone": "+79001112233",
            "username": "test_user",
            "role": "customer",
            "created_at": datetime.now(UTC),
            "last_active": datetime.now(UTC),
            "is_email_verified": True,
            "is_banned": False,
            "is_superuser": False,
            "is_available": True,
        }
        # Проверяем, что схема валидирует объект целиком
        response = RegistrationResponse(user=UserShort(**user_data))
        assert response.status == "success"

        # ИСПРАВЛЕНО: теперь ожидаем ровно то, что выдает валидатор
        assert response.user.phone == "+7900****33"

    # 6. ТЕСТ: Конфиг приложения (Строгость полей)
    def test_app_config_validation(self):
        config_data = {
            "min_required_version": "1.0.0",
            "latest_version": "1.1.0",
            "contact_support": "@support_bot",
            "update_url": "https://store.com",
            "maintenance_mode": False,
        }
        config = AppConfigResponse(**config_data)
        assert config.maintenance_mode is False

    # 7. ТЕСТ: Значения по умолчанию для сессий
    def test_session_data_defaults(self):
        # Если пришел пустой словарь из Redis
        session = SessionData()
        assert session.device == "Unknown Device"
        assert session.ip == "Unknown IP"
