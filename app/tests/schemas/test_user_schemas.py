from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.user import FullProfileResponse, UpdateProfileRequest, UpdateUsernameRequest, UserShort


class TestUserSchemas:
    # --- 1. ТЕСТЫ МАСКИРОВКИ (UserShort) ---
    @pytest.mark.parametrize(
        ("email", "expected"),
        [
            ("ivanov@yandex.ru", "iv****@yandex.ru"),
            ("a@b.ru", "a****@b.ru"),  # Короткое имя
            (None, None),
        ],
    )
    def test_email_masking(self, email, expected):
        # Используем dummy данные для обязательных полей UserBase
        data = {
            "id": 1,
            "uuid": uuid4(),
            "phone": "+79001112233",
            "role": "customer",
            "created_at": datetime.now(UTC),
            "last_active": datetime.now(UTC),
            "email": email,
        }
        user = UserShort(**data)
        assert user.email == expected

    def test_phone_masking(self):
        data = {
            "id": 1,
            "uuid": uuid4(),
            "phone": "+79621234567",
            "role": "customer",
            "created_at": datetime.now(UTC),
            "last_active": datetime.now(UTC),
        }
        user = UserShort(**data)
        # +79621 (5 симв) + **** + 67 (2 симв)
        assert user.phone == "+7962****67"

    # --- 2. ТЕСТЫ ВАЛИДАЦИИ ИМЕН (UpdateProfileRequest) ---
    @pytest.mark.parametrize("name", ["Иван", "Анна-Мария", "Д'Артаньян"])
    def test_profile_update_names_success(self, name):
        schema = UpdateProfileRequest(first_name=name)
        assert schema.first_name == name

    @pytest.mark.parametrize(
        "name",
        [
            "И",  # Слишком коротко (min_length=2)
            "А" * 101,  # Слишком длинно (max_length=100)
        ],
    )
    def test_profile_update_names_error(self, name):
        with pytest.raises(ValidationError):
            UpdateProfileRequest(first_name=name)

    # --- 3. ТЕСТЫ НИКНЕЙМА (UpdateUsernameRequest) ---
    @pytest.mark.parametrize("username", ["user_123", "CoolAdmin", "pro_driver"])
    def test_username_success(self, username):
        schema = UpdateUsernameRequest(username=username)
        assert schema.username == username

    @pytest.mark.parametrize("username", ["user name", "юзер", "!!!", "ab"])
    def test_username_error(self, username):
        """Дыра: Проверка, что кириллица, пробелы и спецсимволы в нике запрещены."""
        with pytest.raises(ValidationError):
            UpdateUsernameRequest(username=username)

    # --- 4. ТЕСТ КОМПОЗИЦИИ (FullProfileResponse) ---
    def test_full_profile_matryoshka(self):
        """Проверка, что матрешка собирается корректно."""
        user_data = {
            "id": 1,
            "uuid": uuid4(),
            "phone": "+79001112233",
            "role": "customer",
            "created_at": datetime.now(UTC),
            "last_active": datetime.now(UTC),
        }
        # Имитируем ответ от /me
        response = FullProfileResponse(
            user=UserShort(**user_data), customer_data={"onboarding_status": "filling_survey"}
        )
        assert response.user.role == "customer"
        assert response.customer_data.onboarding_status == "filling_survey"
        assert response.supplier_data is None  # Должно быть null по умолчанию
