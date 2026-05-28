from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.onboarding import OnboardingApplication
from app.models.spatial import Country
from app.schemas.onboarding import OnboardingStatus


class OnboardingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, application_id: int) -> OnboardingApplication | None:
        """Получить заявку по ID."""
        stmt = select(OnboardingApplication).where(OnboardingApplication.id == application_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create(self, **kwargs: object) -> OnboardingApplication:
        """
        Создает новую заявку или перезаписывает существующую (Upsert).
        Явно затирает старые данные анкеты при перезапуске.
        """
        stmt = (
            pg_insert(OnboardingApplication)
            .values(**kwargs)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "target_role": pg_insert(OnboardingApplication).excluded.target_role,
                    "bank_type": pg_insert(OnboardingApplication).excluded.bank_type,
                    "status": OnboardingStatus.PENDING_LEGAL,
                    "survey_payload": None,
                    "inn": None,
                    "admin_comment": None,
                    "external_id": None,
                    "created_at": func.now(),
                },
            )
            .returning(OnboardingApplication)
        )

        res = await self.db.execute(stmt)
        obj: OnboardingApplication = res.scalar_one()
        return obj

    async def update_by_user_id(self, user_id: int, **values: object) -> None:
        """Атомарное обновление заявки по ID пользователя."""

        stmt = update(OnboardingApplication).where(OnboardingApplication.user_id == user_id).values(**values)
        await self.db.execute(stmt)

    async def get_pending_by_user(self, user_id: int) -> OnboardingApplication | None:
        """
        Находит заявку, которая находится В ПРОЦЕССЕ.
        Отмененные (canceled), одобренные (approved) и отклоненные (rejected) - НЕ мешают.
        """
        active_statuses = [
            OnboardingStatus.PENDING_LEGAL,
            OnboardingStatus.FILLING_SURVEY,
            OnboardingStatus.ON_MODERATION,
        ]
        stmt = select(OnboardingApplication).where(
            OnboardingApplication.user_id == user_id,
            OnboardingApplication.status.in_(active_statuses),
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_moderation_list(self, limit: int = 20, offset: int = 0) -> Sequence[OnboardingApplication]:
        stmt = (
            select(OnboardingApplication)
            .options(joinedload(OnboardingApplication.user))
            .where(OnboardingApplication.status == OnboardingStatus.ON_MODERATION)
            .order_by(OnboardingApplication.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def cancel_application(self, user_id: int) -> bool:
        """Отмена пользователем только тех заявок, что не на модерации."""
        stmt = (
            update(OnboardingApplication)
            .where(
                OnboardingApplication.user_id == user_id,
                OnboardingApplication.status.in_([OnboardingStatus.PENDING_LEGAL, OnboardingStatus.FILLING_SURVEY]),
            )
            .values(status=OnboardingStatus.CANCELED, admin_comment="Отменено пользователем")
        )
        result = await self.db.execute(stmt)
        count = getattr(result, "rowcount", 0)
        return bool(count and count > 0)

    async def get_active_countries(self) -> Sequence[Country]:
        """
        Низкоуровневый SQL-запрос к PostgreSQL.
        Ищет все активные страны и сортирует их по алфавиту.
        """
        stmt = select(Country).where(Country.is_active).order_by(Country.name.asc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_country_iso_by_id(self, country_id: int) -> str | None:
        """
        Точечный атомарный запрос в СУБД.
        Возвращает ISO-код страны по её первичному ключу.
        """
        stmt = select(Country.iso_code).where(Country.id == country_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
    
    async def get_country_by_iso(self, iso_code: str) -> Country | None:
        """Точечный атомарный запрос в СУБД. Находит страну по её ISO-коду."""
        stmt = select(Country).where(Country.iso_code == iso_code)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_expired_applications_with_payloads(self, limit: int = 500) -> Sequence[OnboardingApplication]:
        """Находит строго ограниченную порцию просроченных заявок."""
        limit_approved = datetime.now(UTC) - timedelta(days=180)
        limit_others = datetime.now(UTC) - timedelta(days=30)
        
        stmt = (
            select(OnboardingApplication)
            .where(
                or_(
                    and_(
                        OnboardingApplication.status == OnboardingStatus.APPROVED,
                        OnboardingApplication.created_at < limit_approved,
                    ),
                    and_(
                        OnboardingApplication.status != OnboardingStatus.APPROVED,
                        # ЗАЩИТА: не трогаем тех, кто ждет проверки админа
                        OnboardingApplication.status != OnboardingStatus.ON_MODERATION, 
                        OnboardingApplication.created_at < limit_others,
                    ),
                )
            )
            .limit(limit) # ЗАЩИТА ОТ OOM: берем максимум 500 штук за одну ночь
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def batch_delete_applications(self, application_ids: list[int]) -> None:
        """Выполняет пакетное удаление просроченных заявок из БД."""
        if not application_ids:
            return
        stmt = delete(OnboardingApplication).where(OnboardingApplication.id.in_(application_ids))
        await self.db.execute(stmt)

    async def get_any_by_user_id(self, user_id: int) -> OnboardingApplication | None:
        """Находит абсолютно любую заявку по ID пользователя (колонке user_id)."""
        stmt = select(OnboardingApplication).where(OnboardingApplication.user_id == user_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
