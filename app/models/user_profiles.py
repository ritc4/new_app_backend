from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Date, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Импорт для типизации связи
if TYPE_CHECKING:
    from .user import User  # Укажите правильный путь к файлу с моделью User


class SupplierProfile(Base):
    """Постоянный профиль водителя (Enterprise Standard)."""

    __tablename__ = "supplier_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    # --- Данные авто ---
    car_model: Mapped[str] = mapped_column(String(100))
    car_year: Mapped[int] = mapped_column(BigInteger)
    car_number: Mapped[str] = mapped_column(String(20))
    car_color: Mapped[str] = mapped_column(String(30))
    vin_number: Mapped[str | None] = mapped_column(String(17), nullable=True)

    # --- Документы ---
    license_number: Mapped[str] = mapped_column(String(20))
    license_expiry_date: Mapped[date] = mapped_column(Date)  # Для контроля просрочки
    experience_years: Mapped[int] = mapped_column(BigInteger, default=0)
    license_country: Mapped[str] = mapped_column(String(50), default="RU")

    # --- Технические фото (селфи здесь нет, оно в таблице User) ---
    photo_selfie: Mapped[str] = mapped_column(String(500))
    photo_car_front: Mapped[str] = mapped_column(String(500))
    photo_car_back: Mapped[str] = mapped_column(String(500))
    photo_sts_front: Mapped[str] = mapped_column(String(500))
    photo_sts_back: Mapped[str] = mapped_column(String(500))
    photo_license: Mapped[str] = mapped_column(String(500))

    # --- Бизнес-метрики ---
    rating: Mapped[float] = mapped_column(Float, default=5.0)

    # Таймстампы для аудита
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # --- Связи ---
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
