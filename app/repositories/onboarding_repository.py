from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.onboarding import OnboardingApplication


class OnboardingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, application_id: int) -> OnboardingApplication | None:
        """Получить заявку по ID."""
        stmt = select(OnboardingApplication).where(OnboardingApplication.id == application_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create(self, **kwargs) -> OnboardingApplication:
        """Создать новую запись заявки."""
        new_app = OnboardingApplication(**kwargs)
        self.db.add(new_app)
        return new_app

    async def update_by_user_id(self, user_id: int, **values) -> None:
        """Атомарное обновление заявки по ID пользователя."""
        from sqlalchemy import update

        stmt = update(OnboardingApplication).where(OnboardingApplication.user_id == user_id).values(**values)
        await self.db.execute(stmt)

    async def get_pending_by_user(self, user_id: int) -> OnboardingApplication | None:
        """
        Найти активную заявку пользователя.
        Используется в /me для отображения статуса онбординга.
        """
        stmt = select(OnboardingApplication).where(
            OnboardingApplication.user_id == user_id,
            OnboardingApplication.status != "approved",
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_moderation_list(self, limit: int = 20, offset: int = 0) -> Sequence[OnboardingApplication]:
        """
        Список заявок для админ-панели.
        joinedload гарантирует, что app.user будет доступен без доп. запросов.
        """
        stmt = (
            select(OnboardingApplication)
            .options(joinedload(OnboardingApplication.user))
            .where(OnboardingApplication.status == "on_moderation")
            .order_by(OnboardingApplication.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.db.execute(stmt)
        # .scalars().all() возвращает Sequence, что идеально для типизации
        return res.scalars().all()

    async def delete_expired_applications(self) -> int:
        """
        Удаляет старые анкеты:
        - Одобренные (approved): храним 180 дней для истории.
        - Остальные: 30 дней.
        """

        limit_approved = datetime.now(UTC) - timedelta(days=180)
        limit_others = datetime.now(UTC) - timedelta(days=30)

        stmt = delete(OnboardingApplication).where(
            or_(
                # Старые одобренные
                and_(OnboardingApplication.status == "approved", OnboardingApplication.created_at < limit_approved),
                # Старый мусор (отклоненные, брошенные)
                and_(OnboardingApplication.status != "approved", OnboardingApplication.created_at < limit_others),
            )
        )
        result = await self.db.execute(stmt)
        return result.rowcount  # Возвращаем кол-во удаленных записей
