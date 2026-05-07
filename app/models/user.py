from __future__ import annotations  # Позволяет использовать типы, которые объявлены ниже

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Решает ошибку F821 (Undefined name): импортируем только для линтеров
if TYPE_CHECKING:
    from .user_profiles import SupplierProfile, TripGuideProfile


class User(Base):
    """
    Модель пользователя, синхронизированная с системой авторизации.
    Использует современный синтаксис Mapped и mapped_column.
    """

    __tablename__ = "users"

    # Основные поля
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        unique=True,
        index=True,
    )

    # Optional[str] автоматически делает колонку nullable=True
    first_name: Mapped[str | None] = mapped_column(String(100), index=True)
    last_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)

    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="Подтвержден ли email"
    )
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    photo_url: Mapped[str | None] = mapped_column(String(500))

    # Статусы и роли
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", comment="Доступ к приложению")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, comment="Доступность для заказов")
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="Главный администратор"
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default="customer",
        server_default="customer",
        index=True,
        comment="Роль пользователя",
    )

    # Безопасность и логи
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", comment="Заблокирован ли")
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), server_default=func.now())

    app_version: Mapped[str | None] = mapped_column(String(50))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # Связи (Relationships)
    # Используем кавычки "SupplierProfile", чтобы не было ошибок импорта
    supplier_profile: Mapped[SupplierProfile | None] = relationship(
        "SupplierProfile", back_populates="user", uselist=False
    )
    trip_guide_profile: Mapped[TripGuideProfile | None] = relationship(
        "TripGuideProfile", back_populates="user", uselist=False
    )

    @staticmethod
    def get_role_level(role: str, is_superuser: bool = False) -> int:
        if is_superuser:
            return 100
        levels = {"admin": 50, "supplier": 20, "trip_guide": 20, "customer": 10}
        return levels.get(role, 10)

    @property
    def level(self) -> int:
        return self.get_role_level(self.role, self.is_superuser)
