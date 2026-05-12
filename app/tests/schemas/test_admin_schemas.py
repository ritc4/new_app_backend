from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.admin import AdminChangePhoneRequest, UserAdminView


class TestAdminSchemas:
    # --- ТЕСТЫ ВАЛИДАЦИИ ТЕЛЕФОНА ---

    @pytest.mark.parametrize(
        "valid_phone",
        [
            "+79991234567",  # Стандарт РФ
            "79991234567",  # Без плюса
            "+12025550123",  # США
            "375291234567",  # Беларусь
            "1234567",  # Минимальная длина (7 цифр)
            "+998901234567",  # Узбекистан
        ],
    )
    def test_validate_phone_success(self, valid_phone):
        """Проверка корректных номеров."""
        schema = AdminChangePhoneRequest(new_phone=valid_phone)
        assert schema.new_phone == valid_phone

    @pytest.mark.parametrize(
        "invalid_phone",
        [
            "+09991234567",  # Начинается с 0 (запрещено паттерном [1-9])
            "123456",  # Слишком короткий (меньше 7 цифр)
            "1234567890123456",  # Слишком длинный (больше 15 знаков)
            "+7999abc4567",  # Содержит буквы
            "++7999123456",  # Два плюса
            " 79991234567",  # Пробел в начале
        ],
    )
    def test_validate_phone_error(self, invalid_phone):
        """Дыра: Проверка, что мусорные номера НЕ проходят."""
        with pytest.raises(ValidationError) as exc:
            AdminChangePhoneRequest(new_phone=invalid_phone)

        # Проверяем, что ошибка именно в поле new_phone
        assert exc.value.errors()[0]["loc"][0] == "new_phone"
        assert "Некорректный формат номера" in exc.value.errors()[0]["msg"]

    # --- ТЕСТЫ ОТОБРАЖЕНИЯ (UserAdminView) ---

    def test_user_admin_view_no_masking(self):
        """Проверка: админская схема НЕ должна содержать звездочек."""
        raw_email = "super_secret@example.com"
        raw_phone = "+79991112233"
        now = datetime.now(UTC)

        # Создаем схему. Т.к. она теперь "чистая" (базовая),
        # она просто примет данные как есть.
        view = UserAdminView(
            id=1,
            uuid="550e8400-e29b-41d4-a716-446655440000",
            phone=raw_phone,
            email=raw_email,
            username="admin_hero",
            role="admin",
            created_at=now,
            last_active=now,
        )

        # Главная проверка: данные НЕ изменились
        assert view.email == raw_email
        assert view.phone == raw_phone
        # Дополнительная проверка на отсутствие "маскировки"
        assert "*" not in str(view.email)
        assert "*" not in str(view.phone)
