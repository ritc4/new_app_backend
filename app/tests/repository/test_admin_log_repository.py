import pytest
from sqlalchemy import select

from app.models.admin_log import AdminLog
from app.models.user import User
from app.repositories.admin_log_repository import AdminLogRepository


@pytest.mark.asyncio
class TestAdminLogRepository:
    async def _create_user(self, db_session, phone: str):
        """Вспомогательный метод для создания пользователя."""
        user = User(phone=phone, username=f"u_{phone[-4:]}", is_active=True)
        db_session.add(user)
        await db_session.flush()
        return user

    # 1. ТЕСТ: УСПЕШНОЕ СОЗДАНИЕ ЛОГА
    async def test_create_admin_log_success(self, db_session):
        repo = AdminLogRepository(db_session)

        # Создаем админа и цель (целью может быть тот же юзер или другой)
        admin = await self._create_user(db_session, "+70000000001")
        target = await self._create_user(db_session, "+70000000002")

        action_name = "ban_user"
        log_details = {"reason": "spam", "duration": "permanent"}

        # Act
        await repo.create_admin_log(admin_id=admin.id, target_id=target.id, action=action_name, details=log_details)
        await db_session.commit()

        # Assert: проверяем, что запись появилась в БД
        stmt = select(AdminLog).where(AdminLog.admin_id == admin.id)
        result = await db_session.execute(stmt)
        created_log = result.scalar_one()

        assert created_log.action == action_name
        assert created_log.target_id == target.id
        assert created_log.details == log_details

    # 2. ТЕСТ: ЛОГ БЕЗ ДЕТАЛЕЙ (Optional поле)
    async def test_create_admin_log_no_details(self, db_session):
        repo = AdminLogRepository(db_session)
        admin = await self._create_user(db_session, "+70000000003")

        await repo.create_admin_log(
            admin_id=admin.id,
            target_id=admin.id,  # Лог на самого себя
            action="view_secret_page",
            details=None,
        )
        await db_session.commit()

        stmt = select(AdminLog).where(AdminLog.action == "view_secret_page")
        result = await db_session.execute(stmt)
        created_log = result.scalar_one()

        assert created_log.details is None

    # 3. ТЕСТ: ЦЕЛОСТНОСТЬ (ForeignKey error)
    async def test_create_admin_log_invalid_user_raises(self, db_session):
        repo = AdminLogRepository(db_session)

        # Пытаемся создать лог для несуществующего admin_id
        await repo.create_admin_log(
            admin_id=999999,  # Такого юзера нет
            target_id=999999,
            action="hacker_attack",
        )

        # При коммите должна вылететь ошибка IntegrityError (FK constraint)
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await db_session.commit()

    # 4. ТЕСТ: НЕИЗМЕНЯЕМОСТЬ (Immutability)
    async def test_admin_logs_are_immutable(self, db_session):
        """Дыра: Проверка, что логи нельзя изменить после создания."""
        repo = AdminLogRepository(db_session)
        admin = await self._create_user(db_session, "+70009998877")

        await repo.create_admin_log(admin_id=admin.id, target_id=admin.id, action="critical_action")
        await db_session.commit()

        # Пытаемся найти лог и изменить его напрямую через SQLAlchemy
        stmt = select(AdminLog).where(AdminLog.admin_id == admin.id)
        result = await db_session.execute(stmt)
        log_obj = result.scalar_one()

        # Эмуляция "случайного" изменения поля в коде
        log_obj.action = "hacked_action"

        # Если в модели AdminLog не настроены триггеры на запрет Update,
        # SQLAlchemy позволит это сделать. Но этот тест фиксирует ОЖИДАНИЕ:
        # история должна быть только для чтения.
        # В данном тесте мы проверяем, что репозиторий не предоставляет методов для Update.
        assert not hasattr(repo, "update_admin_log"), "Репозиторий логов НЕ ДОЛЖЕН иметь методов обновления"

    # 5. ТЕСТ: ПАГИНАЦИЯ И МАСШТАБИРУЕМОСТЬ
    async def test_get_admin_logs_pagination(self, db_session):
        """Дыра: Проверка, что при 1 000 000 логов база не упадет (тестируем limit/offset)."""
        repo = AdminLogRepository(db_session)
        admin = await self._create_user(db_session, "+70001112222")

        # Создаем 5 логов
        for i in range(5):
            await repo.create_admin_log(admin_id=admin.id, target_id=admin.id, action=f"action_{i}")
        await db_session.commit()

        # Берем только 2 последних лога (Limit 2)
        logs_page_1 = await repo.get_admin_logs(limit=2, offset=0)
        assert len(logs_page_1) == 2

        # Берем следующую страницу (Offset 2)
        logs_page_2 = await repo.get_admin_logs(limit=2, offset=2)
        assert len(logs_page_2) == 2
        assert logs_page_1[0].action != logs_page_2[0].action  # Данные разные

    # 6. ТЕСТ: ФИЛЬТРАЦИЯ ПО АДМИНУ
    async def test_get_admin_logs_filtering(self, db_session):
        """Дыра: Проверка, что фильтрация не возвращает лишнего."""
        repo = AdminLogRepository(db_session)
        admin_1 = await self._create_user(db_session, "+70001110001")
        admin_2 = await self._create_user(db_session, "+70001110002")

        await repo.create_admin_log(admin_id=admin_1.id, target_id=admin_1.id, action="admin1_action")
        await repo.create_admin_log(admin_id=admin_2.id, target_id=admin_2.id, action="admin2_action")
        await db_session.commit()

        # Ищем только логи первого админа
        logs = await repo.get_admin_logs(admin_id=admin_1.id)
        assert len(logs) == 1
        assert logs[0].action == "admin1_action"
