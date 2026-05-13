from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Date, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Импорт для типизации связи
if TYPE_CHECKING:
    from .user import User


class SupplierProfile(Base):
    """Постоянный профиль водителя (Enterprise Standard)."""

    __tablename__ = "supplier_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # id профиля
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )  # связь с User

    # --- Данные авто ---
    car_brand: Mapped[str] = mapped_column(String(50), index=True)  # марка
    car_model: Mapped[str] = mapped_column(String(100))  # модель
    car_year: Mapped[int] = mapped_column(BigInteger)  # год выпуска
    car_number: Mapped[str] = mapped_column(String(20))  # регистрационный номер
    car_color: Mapped[str] = mapped_column(String(30))  # цвет
    vin_number: Mapped[str | None] = mapped_column(String(17), nullable=True)  # VIN-номер

    # --- Документы ---
    license_number: Mapped[str] = mapped_column(String(20))  # номер водительского удостоверения
    license_expiry_date: Mapped[date] = mapped_column(Date)  # Для контроля просрочки
    experience_years: Mapped[int] = mapped_column(BigInteger, default=0)  # опыт вождения
    license_country: Mapped[str] = mapped_column(String(50), default="RU")  # страна водительского удостоверения

    # --- Технические фото (селфи здесь нет, оно в таблице User) ---
    photo_selfie: Mapped[str] = mapped_column(String(500))  # фото селфи водителя
    photo_car_side: Mapped[str] = mapped_column(String(500), nullable=False)  # Фото боковой стороны автомобиля
    photo_car_interior: Mapped[str] = mapped_column(String(500), nullable=False)  # Фото салона автомобиля (задний ряд)
    photo_car_front: Mapped[str] = mapped_column(String(500))  # фото лицевой стороны автомобиля
    photo_car_back: Mapped[str] = mapped_column(String(500))  # фото задней стороны автомобиля
    photo_sts_front: Mapped[str] = mapped_column(
        String(500)
    )  # STS (Свидетельство о транспортном средстве, лицевая сторона)
    photo_sts_back: Mapped[str] = mapped_column(
        String(500)
    )  # STS (Свидетельство о транспортном средстве, обратная сторона)
    photo_license: Mapped[str] = mapped_column(String(500))  # фото водительского удостоверения

    # --- Бизнес-метрики ---
    rating: Mapped[float] = mapped_column(Float, default=5.0)  # рейтинг водителя

    # Таймстампы для аудита
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())  # дата создания
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )  # дата последнего обновления

    # --- Связи ---
    user: Mapped[User] = relationship("User", back_populates="supplier_profile")  # один ко многим


class TripGuideProfile(Base):
    """Постоянный профиль гида."""

    __tablename__ = "trip_guide_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    bio: Mapped[str | None] = mapped_column(String(1000))
    # Список языков (указываем тип List для линтера)
    languages: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    specialization: Mapped[str | None] = mapped_column(String(255))
    photo_certificate: Mapped[str | None] = mapped_column(String(500))

    rating: Mapped[float] = mapped_column(Float, default=5.0)

    user: Mapped[User] = relationship("User", back_populates="trip_guide_profile")
