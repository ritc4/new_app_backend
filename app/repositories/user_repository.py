import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

# Логгер для уровня базы данных
logger = logging.getLogger("app.infra.db")


class UserRepository:
    """Все операции с таблицей users."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_phone(self, phone: str) -> User | None:
        stmt = select(User).where(User.phone == phone)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create_with_phone(self, phone: str, app_version: str) -> User:
        try:
            now = datetime.now(UTC)
            stmt = (
                insert(User)
                .values(
                    phone=phone,
                    is_active=True,
                    app_version=app_version,
                    last_active=now,
                )
                .returning(User)
            )
            res = await self.db.execute(stmt)
            await self.db.commit()
            return res.scalar_one()
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Ошибка при создании пользователя {phone}: {e}")
            raise

    async def update_user(self, user_id: int, **values: Any) -> User:
        """Универсальное обновление любых полей пользователя."""
        try:
            stmt = (
                update(User).where(User.id == user_id).values(**values).returning(User)
            )
            res = await self.db.execute(stmt)
            await self.db.commit()
            return res.scalar_one()
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Ошибка при обновлении полей пользователя {user_id}: {e}")
            raise

    async def update_activity(
        self,
        user_id: int,
        app_version: str | None = None,
    ) -> None:
        values = {"last_active": datetime.now(UTC)}
        if app_version is not None:
            values["app_version"] = app_version

        # Переиспользуем универсальный метод
        await self.update_user(user_id, **values)

    async def update_profile(
        self,
        user_id: int,
        first_name: str,
        last_name: str | None,
    ) -> User:
        return await self.update_user(
            user_id, first_name=first_name, last_name=last_name
        )

    async def update_username(self, user_id: int, username: str) -> None:
        await self.update_user(user_id, username=username)

    async def change_phone(self, user_id: int, new_phone: str) -> None:
        await self.update_user(user_id, phone=new_phone)

    async def delete_user(self, user_id: int) -> None:
        try:
            stmt = delete(User).where(User.id == user_id)
            await self.db.execute(stmt)
            await self.db.commit()
        except SQLAlchemyError as e:
            await self.db.rollback()
            logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")
            raise
