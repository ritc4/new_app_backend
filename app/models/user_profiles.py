from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, Date, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base
from app.models.spatial import CarClass

# Импорт для типизации связи
if TYPE_CHECKING:
    # from .excursions import Excursion
    from .excursions import Excursion
    from .spatial import CityRegion
    from .user import User


class SupplierProfile(Base):
    """Постоянный профиль водителя трансферов."""

    __tablename__ = "supplier_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    languages: Mapped[list[str] | None] = mapped_column(JSON, default=list, comment="Языки общения водителя")

    base_region_id: Mapped[int] = mapped_column(ForeignKey("city_regions.id", ondelete="RESTRICT"), index=True)
    car_class: Mapped[str] = mapped_column(String(20), default=CarClass.ECONOMY.value, index=True)

    car_brand: Mapped[str] = mapped_column(String(50), index=True)
    car_model: Mapped[str] = mapped_column(String(100))
    car_year: Mapped[int] = mapped_column(BigInteger)
    car_number: Mapped[str] = mapped_column(String(20))
    car_color: Mapped[str] = mapped_column(String(30))
    vin_number: Mapped[str | None] = mapped_column(String(17), nullable=True)

    license_number: Mapped[str] = mapped_column(String(20))
    license_expiry_date: Mapped[date] = mapped_column(Date)
    experience_years: Mapped[int] = mapped_column(BigInteger, default=0)

    # Фото-контроль Островка
    photo_selfie: Mapped[str] = mapped_column(String(500))
    photo_car_side: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_car_interior: Mapped[str] = mapped_column(String(500), nullable=False)
    photo_car_front: Mapped[str] = mapped_column(String(500))
    photo_car_back: Mapped[str] = mapped_column(String(500))
    photo_sts_front: Mapped[str] = mapped_column(String(500))
    photo_sts_back: Mapped[str] = mapped_column(String(500))
    photo_license: Mapped[str] = mapped_column(String(500))

    rating: Mapped[float] = mapped_column(Float, default=5.0)  # Кешированный рейтинг
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship("User", back_populates="supplier_profile")
    base_region: Mapped[CityRegion] = relationship("CityRegion")


class TripGuideProfile(Base):
    """Постоянный профиль пешего гида."""

    __tablename__ = "trip_guide_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    base_region_id: Mapped[int] = mapped_column(ForeignKey("city_regions.id", ondelete="RESTRICT"), index=True)

    bio: Mapped[str | None] = mapped_column(String(1000))
    languages: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    specialization: Mapped[str | None] = mapped_column(String(255))
    photo_certificate: Mapped[str | None] = mapped_column(String(500))
    rating: Mapped[float] = mapped_column(Float, default=5.0)

    user: Mapped[User] = relationship("User", back_populates="trip_guide_profile")
    base_region: Mapped[CityRegion] = relationship("CityRegion")

    excursions: Mapped[list[Excursion]] = relationship(
        "Excursion", back_populates="guide", cascade="all, delete-orphan"
    )
