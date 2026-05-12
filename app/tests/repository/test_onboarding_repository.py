from datetime import UTC, datetime, timedelta

import pytest

from app.models.onboarding import OnboardingApplication
from app.models.user import User
from app.repositories.onboarding_repository import OnboardingRepository
from app.schemas.onboarding import OnboardingStatus


@pytest.mark.asyncio
class TestOnboardingRepository:
    async def _create_test_user(self, db_session, phone: str):
        """Вспомогательный метод для создания пользователя."""
        user = User(phone=phone, username=f"user_{phone[-4:]}", is_active=True)
        db_session.add(user)
        await db_session.flush()  # Получаем id без коммита всей транзакции
        return user

    # 1. ТЕСТ: UPSERT (Перезапуск заявки)
    async def test_create_upsert_resets_data(self, db_session):
        repo = OnboardingRepository(db_session)
        user = await self._create_test_user(db_session, "+79001112233")

        # Сначала создаем заявку с данными анкеты
        await repo.create(user_id=user.id, target_role="supplier", survey_payload={"step1": "done"}, inn="1234567890")
        await db_session.commit()

        # Юзер нажимает "Начать заново"
        new_app = await repo.create(user_id=user.id, target_role="trip_guide")
        await db_session.commit()
        await db_session.refresh(new_app)

        # ПРОВЕРКА: старые данные (inn, payload) затерлись (как прописано в твоем Upsert)
        assert new_app.target_role == "trip_guide"
        assert new_app.survey_payload is None
        assert new_app.inn is None
        assert new_app.status == OnboardingStatus.PENDING_LEGAL

    # 2. ТЕСТ: ПОИСК АКТИВНОЙ ЗАЯВКИ
    async def test_get_pending_by_user_filtering(self, db_session):
        repo = OnboardingRepository(db_session)
        user = await self._create_test_user(db_session, "+79004445566")

        # Создаем активную заявку (на заполнении)
        app = OnboardingApplication(user_id=user.id, status=OnboardingStatus.FILLING_SURVEY, target_role="s")
        db_session.add(app)
        await db_session.commit()

        found = await repo.get_pending_by_user(user.id)
        assert found is not None
        assert found.status == OnboardingStatus.FILLING_SURVEY

    # 3. ТЕСТ: ОТМЕНА ЗАЯВКИ
    async def test_cancel_application_restrictions(self, db_session):
        repo = OnboardingRepository(db_session)

        # Кейс 1: МОЖНО отменить (статус FILLING_SURVEY)
        user1 = await self._create_test_user(db_session, "+79007778899")
        await repo.create(user_id=user1.id, status=OnboardingStatus.FILLING_SURVEY, target_role="s")
        await db_session.commit()

        success = await repo.cancel_application(user1.id)
        assert success is True

        # Кейс 2: НЕЛЬЗЯ отменить самому (статус ON_MODERATION)
        user2 = await self._create_test_user(db_session, "+79000000000")
        # Твой repo.create всегда ставит PENDING_LEGAL при конфликте, поэтому обновим статус вручную
        await repo.create(user_id=user2.id, status=OnboardingStatus.PENDING_LEGAL, target_role="s")
        await repo.update_by_user_id(user2.id, status=OnboardingStatus.ON_MODERATION)
        await db_session.commit()

        success_on_mod = await repo.cancel_application(user2.id)
        assert success_on_mod is False

    # 4. ТЕСТ: ОЧИСТКА УСТАРЕВШИХ
    async def test_delete_expired_logic(self, db_session):
        repo = OnboardingRepository(db_session)
        now = datetime.now(UTC)

        # Создаем 3 разных пользователя для 3 разных заявок (из-за UNIQUE user_id)
        u1 = await self._create_test_user(db_session, "+70000000001")
        u2 = await self._create_test_user(db_session, "+70000000002")
        u3 = await self._create_test_user(db_session, "+70000000003")

        # 1. Старая брошенная (40 дней) -> УДАЛИТЬ
        db_session.add(
            OnboardingApplication(
                user_id=u1.id,
                status=OnboardingStatus.PENDING_LEGAL,
                created_at=now - timedelta(days=40),
                target_role="s",
            )
        )
        # 2. Старая одобренная (100 дней) -> ОСТАВИТЬ (лимит 180)
        db_session.add(
            OnboardingApplication(
                user_id=u2.id, status=OnboardingStatus.APPROVED, created_at=now - timedelta(days=100), target_role="s"
            )
        )
        # 3. Свежая (1 день) -> ОСТАВИТЬ
        db_session.add(
            OnboardingApplication(
                user_id=u3.id,
                status=OnboardingStatus.PENDING_LEGAL,
                created_at=now - timedelta(days=1),
                target_role="s",
            )
        )
        await db_session.commit()

        deleted_count = await repo.delete_expired_applications()
        assert deleted_count == 1

    # 5. ТЕСТ: СПИСОК ДЛЯ МОДЕРАЦИИ (Pagination + Relationships)
    async def test_get_moderation_list_success(self, db_session):
        repo = OnboardingRepository(db_session)
        user = await self._create_test_user(db_session, "+79998887766")

        # Создаем заявку именно в статусе ON_MODERATION
        await repo.create(user_id=user.id, target_role="supplier")
        await repo.update_by_user_id(user.id, status=OnboardingStatus.ON_MODERATION)
        await db_session.commit()

        result = await repo.get_moderation_list(limit=10)

        assert len(result) == 1
        # Проверяем joinedload: обращение к .user не должно вызывать новый запрос/ошибку
        assert result[0].user.phone == "+79998887766"

    # 6. ТЕСТ: АТОМАРНОЕ ОБНОВЛЕНИЕ
    async def test_update_by_user_id_partial(self, db_session):
        repo = OnboardingRepository(db_session)
        user = await self._create_test_user(db_session, "+79990001122")
        await repo.create(user_id=user.id, target_role="supplier", inn="12345")
        await db_session.commit()

        # Обновляем ТОЛЬКО комментарий админа
        await repo.update_by_user_id(user.id, admin_comment="Check this")
        await db_session.commit()

        # Проверяем, что ИНН не стерся
        app = await repo.get_by_id((await repo.get_pending_by_user(user.id)).id)
        assert app.admin_comment == "Check this"
        assert app.inn == "12345"

    # 7. ТЕСТ: ИГНОРИРОВАНИЕ ЗАВЕРШЕННЫХ ЗАЯВОК
    async def test_get_pending_ignores_finished(self, db_session):
        repo = OnboardingRepository(db_session)
        user = await self._create_test_user(db_session, "+70001110000")

        # Создаем отклоненную (REJECTED) заявку
        # В твоем коде REJECTED нет в списке активных, значит метод должен вернуть None
        app = OnboardingApplication(user_id=user.id, status=OnboardingStatus.REJECTED, target_role="s")
        db_session.add(app)
        await db_session.commit()

        found = await repo.get_pending_by_user(user.id)
        assert found is None
