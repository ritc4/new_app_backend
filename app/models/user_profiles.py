from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Импорт для типизации связи
if TYPE_CHECKING:
    from .user import User  # Укажите правильный путь к файлу с моделью User


class SupplierProfile(Base):
    """Постоянный профиль водителя."""

    __tablename__ = "supplier_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    car_model: Mapped[str] = mapped_column(String(100))
    car_number: Mapped[str] = mapped_column(String(20))
    license_number: Mapped[str] = mapped_column(String(20))
    experience_years: Mapped[int] = mapped_column(BigInteger, default=0)

    # Ссылки на фото (Optional через | None)
    photo_car_front: Mapped[str | None] = mapped_column(String(500))
    photo_sts_front: Mapped[str | None] = mapped_column(String(500))

    rating: Mapped[float] = mapped_column(Float, default=5.0)

    # Связь с User (указываем back_populates для двусторонней связи)
    user: Mapped[User] = relationship("User", back_populates="supplier_profile")


class TripGuideProfile(Base):
    """Постоянный профиль гида."""

    __tablename__ = "trip_guide_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    bio: Mapped[str | None] = mapped_column(String(1000))
    # Список языков (указываем тип List для линтера)
    languages: Mapped[list | None] = mapped_column(JSON, default=list)
    specialization: Mapped[str | None] = mapped_column(String(255))
    photo_certificate: Mapped[str | None] = mapped_column(String(500))

    rating: Mapped[float] = mapped_column(Float, default=5.0)

    user: Mapped[User] = relationship("User", back_populates="trip_guide_profile")
