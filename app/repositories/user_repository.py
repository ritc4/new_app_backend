import logging
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.user import User

logger = logging.getLogger("app.infra.db")


class UserRepository:
    """Все операции с таблицей users с поддержкой UUID и Soft Delete."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        """Внутренний поиск по BigInt ID (для связей в БД)."""
        return await self.db.get(User, user_id)

    async def get_by_uuid(self, user_uuid: UUID) -> User | None:
        """Публичный поиск по UUID (для API и Flutter)."""
        stmt = select(User).where(and_(User.uuid == user_uuid, User.deleted_at.is_(None)))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        """Поиск по телефону только среди активных (не удаленных)."""
        stmt = select(User).where(and_(User.phone == phone, User.deleted_at.is_(None)))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(and_(User.username == username, User.deleted_at.is_(None)))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create_with_phone(self, phone: str, app_version: str) -> User:
        """
        Создает пользователя или восстанавливает удаленного.
        Сохраняет права активных админов при входе.
        """
        now = func.now()

        # 1. Подготавливаем данные для нового пользователя
        stmt = pg_insert(User).values(
            phone=phone,
            is_active=True,
            app_version=app_version,
            last_active=now,
            role="customer",
        )

        # 2. Логика при конфликте (если номер уже есть в базе)
        stmt = stmt.on_conflict_do_update(
            index_elements=["phone"],
            set_={
                "is_active": True,
                "app_version": app_version,
                "last_active": now,
                # Если юзер был удален (deleted_at не пустой) -> сбрасываем в customer.
                # Если юзер просто входит (активный) -> оставляем текущую роль из БД.
                "role": case((User.deleted_at.is_not(None), "customer"), else_=User.role),
                # Аналогично для суперюзера: сброс только при восстановлении.
                "is_superuser": case((User.deleted_at.is_not(None), False), else_=User.is_superuser),
                # В самом конце очищаем метку удаления
                "deleted_at": None,
            },
        ).returning(User)

        res = await self.db.execute(stmt)
        return res.scalar_one()

    async def update_user(self, user_id: int, **values: Any) -> User | None:
        """Универсальное обновление по внутреннему ID."""
        # Если пришел пустой словарь значений, просто возвращаем текущего пользователя
        if not values:
            return await self.get_by_id(user_id)

        if "last_active" not in values:
            values["last_active"] = func.now()

        stmt = update(User).where(User.id == user_id).values(**values).returning(User)
        res = await self.db.execute(stmt)

        # ИСПРАВЛЕНИЕ: используем scalar_one_or_none() для безопасности
        return res.scalar_one_or_none()

    async def update_activity(self, user_id: int, app_version: str | None = None) -> None:
        values = {"last_active": func.now()}
        if app_version:
            values["app_version"] = app_version

        stmt = update(User).where(User.id == user_id).values(**values)
        await self.db.execute(stmt)

    async def change_phone(self, user_id: int, new_phone: str) -> User:
        return await self.update_user(user_id, phone=new_phone)

    async def get_by_phone_include_deleted(self, phone: str) -> User | None:
        """Поиск по телефону без фильтрации deleted_at."""
        stmt = select(User).where(User.phone == phone)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def delete_user_permanently(self, user_id: int) -> None:
        """Физическое удаление (Hard Delete) — используется только воркером очистки."""
        stmt = delete(User).where(User.id == user_id)
        await self.db.execute(stmt)
