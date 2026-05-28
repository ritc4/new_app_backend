import logging
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func

from app.models.orders import Order, OrderStatus
from app.models.spatial import Country
from app.models.user import User

logger = logging.getLogger("app.infra.db")


class UserRepository:
    """Все операции с таблицей users с поддержкой UUID и Soft Delete."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        """Внутренний поиск по BigInt ID (для связей в БД)."""
        stmt = (
            select(User)
            .options(selectinload(User.supplier_profile), selectinload(User.trip_guide_profile))
            .where(User.id == user_id)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_uuid(self, user_uuid: UUID) -> User | None:
        """Публичный поиск по UUID (для API и Flutter)."""
        stmt = (
            select(User)
            .options(selectinload(User.supplier_profile), selectinload(User.trip_guide_profile))
            .where(and_(User.uuid == user_uuid, User.deleted_at.is_(None)))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        """Поиск по телефону только среди активных (не удаленных)."""
        stmt = (
            select(User)
            .options(selectinload(User.supplier_profile), selectinload(User.trip_guide_profile))
            .where(and_(User.phone == phone, User.deleted_at.is_(None)))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(and_(User.username == username, User.deleted_at.is_(None)))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Поиск по email среди активных (не удаленных) пользователей."""
        stmt = select(User).where(and_(User.email == email, User.deleted_at.is_(None)))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create_with_phone(self, phone: str, app_version: str, username: str, country_id: int) -> User:
        """
        Создает пользователя или восстанавливает удаленного.
        Сохраняет права активных админов при входе.
        """
        now = func.now()

        # 1. Подготавливаем данные для нового пользователя
        stmt = (
            pg_insert(User)
            .values(
                phone=phone,
                username=username,
                country_id=country_id,
                is_email_verified=False,
                is_active=True,
                app_version=app_version,
                last_active=now,
                role="customer",
            )
            .on_conflict_do_update(
                index_elements=["phone"],
                set_={
                    "username": User.username,
                    "country_id": User.country_id,
                    "first_name": User.first_name,
                    "last_name": User.last_name,
                    "middle_name": User.middle_name,
                    "email": User.email,
                    "photo_url": User.photo_url,
                    "is_email_verified": User.is_email_verified,
                    "is_active": True,
                    "app_version": app_version,
                    "last_active": now,
                    "role": User.role,
                    "is_superuser": User.is_superuser,
                    "deleted_at": None,
                },
            )
            .returning(User)
        )
        res = await self.db.execute(stmt)
        # 2. Подсказываем mypy тип через аннотацию переменной
        result: User = res.scalar_one()
        return result

    async def update_user(self, user_id: int, **values: object) -> User | None:
        """Универсальное обновление по внутреннему ID."""
        # Если пришел пустой словарь значений, просто возвращаем текущего пользователя
        if not values:
            return await self.get_by_id(user_id)

        if "last_active" not in values:
            values["last_active"] = func.now()

        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(**values)
            .options(selectinload(User.supplier_profile), selectinload(User.trip_guide_profile))
            .returning(User)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def update_activity(self, user_id: int, app_version: str | None = None) -> None:
        values: dict[str, object] = {"last_active": func.now()}
        if app_version:
            values["app_version"] = app_version

        stmt = update(User).where(User.id == user_id).values(**values)
        await self.db.execute(stmt)

    async def change_phone(self, user_id: int, new_phone: str) -> User:
        user = await self.update_user(user_id, phone=new_phone)
        if not user:
            raise ValueError(f"Пользователь с ID {user_id} не найден для смены номера")
        return user

    async def find_country_id_by_iso_code(self, iso_code: str) -> int | None:
        """
        Находит внутренний BigInt ID страны по её двухбуквенному международному коду (например, 'RU', 'KZ').
        Используется в AuthService совместно с библиотекой phonenumbers.
        """
        stmt = select(Country.id).where(Country.iso_code == iso_code.upper(), Country.is_active.is_(True))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_countries_page(self, limit: int, offset: int) -> Sequence[Country]:
        """Низкоуровневая выборка списка всех стран с сортировкой от новых к старым."""
        stmt = select(Country).order_by(Country.id.desc()).limit(limit).offset(offset)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_by_phone_include_deleted(self, phone: str) -> User | None:
        """Поиск по телефону без фильтрации deleted_at."""
        stmt = select(User).where(User.phone == phone)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def delete_users_permanently_batch(self, user_ids: list[int]) -> int:
        """
        Физическое пакетное удаление (Hard Delete) — используется воркером очистки.
        Удаляет пачку пользователей ОДНИМ высокопроизводительным SQL-запросом.
        """
        if not user_ids:
            return 0

        stmt = delete(User).where(User.id.in_(user_ids))
        result = await self.db.execute(stmt)

        count = getattr(result, "rowcount", 0)
        return int(count)

    async def has_active_orders(self, performer_id: int) -> bool:
        """
        Проверяет, есть ли у исполнителя назначенные или выполняющиеся заказы.
        Возвращает строго True или False. Чистый SQL без бизнес-логики.
        """
        active_statuses = [OrderStatus.ASSIGNED, OrderStatus.IN_PROGRESS]

        stmt = select(Order.id).where(Order.performer_id == performer_id, Order.status.in_(active_statuses)).limit(1)

        res = await self.db.execute(stmt)
        # Если запись найдена, bool() вернет True, если None — вернет False
        return bool(res.scalar_one_or_none())

    async def get_expired_and_abandoned_users(
        self, abandoned_date: datetime, soft_deleted_date: datetime
    ) -> Sequence[User]:
        """
        Инкапсулирует SQL-запрос для поиска пользователей, подлежащих жесткому удалению.
        Ищет брошенные пустые аккаунты (180 дней) и просроченную корзину (30 дней).
        """
        stmt = select(User).where(
            and_(
                User.is_superuser.is_(False),
                or_(
                    (User.first_name.is_(None) & (User.last_active < abandoned_date)),
                    (User.deleted_at.is_not(None) & (User.deleted_at < soft_deleted_date)),
                ),
            ),
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()
