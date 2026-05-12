import builtins
import secrets
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.models.user import User
from app.models.user_profiles import SupplierProfile
from app.repositories.user_repository import UserRepository


@pytest.mark.asyncio
class TestUserRepository:
    # 1. ТЕСТ: UPSERT LOGIC (Восстановление пользователя)
    async def test_create_with_phone_restores_user(self, db_session):
        repo = UserRepository(db_session)
        phone = "+70001112233"

        # Создаем удаленного пользователя
        initial_user = User(phone=phone, username="old_nick", is_superuser=True, deleted_at=datetime.now(UTC))
        db_session.add(initial_user)
        await db_session.commit()

        # Пытаемся зайти снова (Upsert)
        restored = await repo.create_with_phone(phone, "2.0.0", "temp_nick")

        # ВАЖНО: Принудительно обновляем объект из БД, чтобы увидеть сброс deleted_at
        await db_session.refresh(restored)

        assert restored.phone == phone
        assert restored.deleted_at is None  # Теперь пройдет
        assert restored.username == "old_nick"
        assert restored.is_superuser is True

    # 2. ТЕСТ: ПОДГРУЗКА СВЯЗЕЙ (Заполняем все Not Null поля)
    async def test_get_by_id_loads_profiles(self, db_session):
        repo = UserRepository(db_session)

        # 1. Создаем пользователя
        user = User(phone="+7123", username="test_loader")
        db_session.add(user)
        await db_session.flush()

        # 2. Создаем профиль со всеми Not Null полями
        profile = SupplierProfile(
            user_id=user.id,
            car_model="Tesla",
            car_year=2024,
            car_number="A001AA",
            car_color="White",
            license_number="123456",
            license_expiry_date=date(2030, 1, 1),
            photo_selfie="url",
            photo_car_front="url",
            photo_car_back="url",
            photo_sts_front="url",
            photo_sts_back="url",
            photo_license="url",
        )
        db_session.add(profile)
        await db_session.commit()

        # 3. Асинхронно получаем пользователя через репозиторий
        # Метод repo.get_by_id уже содержит selectinload
        user_from_db = await repo.get_by_id(user.id)

        assert user_from_db is not None

        # 4. Чтобы избежать MissingGreenlet после commit/expire,
        # можно явно обновить объект со связями, если сессия "потеряла" их
        # Но при правильно настроенном selectinload в репозитории, строка ниже должна работать:
        assert user_from_db.supplier_profile is not None
        assert user_from_db.supplier_profile.car_model == "Tesla"

    @pytest.mark.parametrize(
        ("search_method", "field_name", "value"),
        [
            ("get_by_uuid", "uuid", uuid4()),
            ("get_by_username", "username", "ghost_user"),
            ("get_by_email", "email", "ghost@example.com"),
        ],
    )
    async def test_search_methods_respect_soft_delete(self, db_session, search_method, field_name, value):
        repo = UserRepository(db_session)
        # Создаем удаленного пользователя с конкретным полем
        user_data = {field_name: value, "phone": f"+7{secrets.token_hex(5)}", "deleted_at": datetime.now(UTC)}
        user = User(**user_data)
        db_session.add(user)
        await db_session.commit()

        # Вызываем метод динамически
        method = getattr(repo, search_method)
        found = await method(value)

        assert found is None, f"Метод {search_method} не должен находить удаленных пользователей"

    # 5. ТЕСТ: УНИВЕРСАЛЬНЫЙ UPDATE
    async def test_update_user_partial_fields(self, db_session):
        repo = UserRepository(db_session)
        user = User(phone="+7111", username="original", first_name="Ivan")
        db_session.add(user)
        await db_session.commit()

        # Обновляем только имя
        updated = await repo.update_user(user.id, first_name="Dmitry")
        await db_session.commit()
        await db_session.refresh(updated)

        assert updated.first_name == "Dmitry"
        assert updated.username == "original"  # Это поле не должно измениться
        assert updated.last_active is not None

    # 6. ТЕСТ: ОБНОВЛЕНИЕ АКТИВНОСТИ (Background)
    async def test_update_activity_logic(self, db_session):
        repo = UserRepository(db_session)
        user = User(phone="+7222", username="active_user", app_version="1.0.0")
        db_session.add(user)
        await db_session.commit()

        # Имитируем обновление из фоновой задачи
        await repo.update_activity(user.id, app_version="2.0.0")
        await db_session.commit()
        await db_session.refresh(user)

        assert user.app_version == "2.0.0"
        # Проверяем, что last_active обновился (был None или старым)
        assert user.last_active is not None

    # 7. ТЕСТ: ФИЗИЧЕСКОЕ УДАЛЕНИЕ (Hard Delete)
    async def test_delete_user_permanently(self, db_session):
        repo = UserRepository(db_session)
        user = User(phone="+7333", username="to_be_purged")
        db_session.add(user)
        await db_session.commit()

        # Удаляем физически
        await repo.delete_user_permanently(user.id)
        await db_session.commit()

        # Проверяем, что в базе вообще ничего нет (даже через include_deleted)
        res = await repo.get_by_phone_include_deleted("+7333")
        assert res is None

    # 8. ТЕСТ: СМЕНА НОМЕРА ТЕЛЕФОНА
    async def test_change_phone_success(self, db_session):
        repo = UserRepository(db_session)
        user = User(phone="+7000", username="phone_changer")
        db_session.add(user)
        await db_session.commit()

        await repo.change_phone(user.id, "+7999")
        await db_session.commit()
        await db_session.refresh(user)

        assert user.phone == "+7999"

    async def test_change_phone_not_found_raises(self, db_session):
        repo = UserRepository(db_session)
        with pytest.raises(builtins.ValueError) as exc:
            await repo.change_phone(999999, "+7999")
        assert "не найден" in str(exc.value)
