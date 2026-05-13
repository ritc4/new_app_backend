from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.onboarding import BankWebhookPayload, SupplierSurvey, TripguideSurvey


class TestOnboardingSchemas:
    # --- 1. ТЕСТЫ WEBHOOK (ИНН) ---
    def test_bank_webhook_inn_valid(self):
        payload = BankWebhookPayload(user_id=1, phone="7999", inn="1234567890", full_name="Ivan")
        assert payload.inn == "1234567890"

    def test_bank_webhook_inn_invalid_chars(self):
        """Дыра: ИНН не должен содержать буквы."""
        with pytest.raises(ValidationError) as exc:
            BankWebhookPayload(user_id=1, phone="7999", inn="12345678ab", full_name="Ivan")
        assert "только из цифр" in str(exc.value)

    # --- 2. ТЕСТЫ АНКЕТЫ ВОДИТЕЛЯ (SupplierSurvey) ---

    @pytest.fixture
    def valid_supplier_data(self):
        """Базовый набор валидных данных для анкеты."""
        return {
            "car_brand": "Kia",
            "car_model": "Rio",
            "car_year": datetime.now().year - 2,
            "car_number": "А777АА77",
            "car_color": "Белый",
            "license_number": "9901123456",
            "license_expiry_date": date(2030, 1, 1),
            "experience_years": 5,
            "photo_selfie": "url",
            "photo_car_side": "url",
            "photo_car_interior": "url",
            "photo_car_front": "url",
            "photo_car_back": "url",
            "photo_sts_front": "url",
            "photo_sts_back": "url",
            "photo_license": "url",
        }

    def test_car_number_transliteration(self, valid_supplier_data):
        """Проверка замены английских букв на русские аналоги (А, В, Е...)."""
        valid_supplier_data["car_number"] = "A777AA77"  # Здесь латинская 'A'
        survey = SupplierSurvey(**valid_supplier_data)
        # Должно стать кириллицей 'А'
        assert survey.car_number == "А777АА77"
        assert ord(survey.car_number[0]) == 1040  # Код кириллической 'А'

    def test_car_age_limit_error(self, valid_supplier_data):
        """Дыра: Машина старше 15 лет (Enterprise требование)."""
        valid_supplier_data["car_year"] = datetime.now().year - 16
        with pytest.raises(ValidationError) as exc:
            SupplierSurvey(**valid_supplier_data)
        assert "старше 15 лет" in str(exc.value)

    @pytest.mark.parametrize(
        ("country", "number", "should_pass"),  # Передаем кортеж строк
        [
            ("RU", "9901 123456", True),
            ("RU", "12345", False),
            ("BY", "1AB1234567", True),
            ("KZ", "AA1234567", True),
        ],
    )
    def test_license_format_by_country(self, valid_supplier_data, country, number, should_pass):
        """Проверка регулярок прав для разных стран."""
        valid_supplier_data["license_country"] = country
        valid_supplier_data["license_number"] = number

        if should_pass:
            survey = SupplierSurvey(**valid_supplier_data)
            assert " " not in survey.license_number  # Проверка очистки пробелов
        else:
            with pytest.raises(ValidationError):
                SupplierSurvey(**valid_supplier_data)

    def test_license_expired_error(self, valid_supplier_data):
        """Дыра: Просроченные права."""
        valid_supplier_data["license_expiry_date"] = date(2020, 1, 1)
        with pytest.raises(ValidationError) as exc:
            SupplierSurvey(**valid_supplier_data)
        assert "истек" in str(exc.value)

    def test_experience_years_error(self, valid_supplier_data):
        """Дыра: Стаж менее 3 лет."""
        valid_supplier_data["experience_years"] = 2
        with pytest.raises(ValidationError) as exc:
            SupplierSurvey(**valid_supplier_data)

        # Проверяем наличие главных слов, игнорируя тире и точный порядок
        error_msg = str(exc.value).lower()
        assert "стаж" in error_msg
        assert "3 года" in error_msg

    def test_vin_validation(self, valid_supplier_data):
        """Проверка VIN (запрет букв I, O, Q)."""
        valid_supplier_data["vin_number"] = "1YVHP8CB12345678Q"  # Буква Q
        with pytest.raises(ValidationError) as exc:
            SupplierSurvey(**valid_supplier_data)
        assert "запрещены буквы I, O, Q" in str(exc.value)

    # --- 3. ТЕСТЫ АНКЕТЫ ГИДА (TripguideSurvey) ---

    def test_tripguide_bio_too_short(self):
        """Дыра: Слишком короткий рассказ о себе."""
        with pytest.raises(ValidationError):
            TripguideSurvey(bio="Short", specialization="History")
