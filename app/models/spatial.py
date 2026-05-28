from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class CarClass(StrEnum):
    ECONOMY = "economy"
    COMFORT = "comfort"
    MINIVAN = "minivan"
    BUSINESS = "business"
    JEEP = "jeep"


class Country(Base):
    """Справочник стран международного комплаенса."""

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    iso_code: Mapped[str] = mapped_column(String(2), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))  # "RUB", "USD", "KZT"
    is_allowed_for_ru_onboarding: Mapped[bool] = mapped_column(
        default=False, comment="Разрешена ли эта страна прав для коммерческой работы в РФ"
    )
    phone_code: Mapped[str] = mapped_column(String(5), index=True, unique=False)
    license_regex: Mapped[str] = mapped_column(String(255), default=r"^\d{10}$")
    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    users: Mapped[list[User]] = relationship("User", back_populates="country")


class CityRegion(Base):
    """Операционные регионы деятельности (курортные зоны / города)."""

    __tablename__ = "city_regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)  # "Кавминводы", "Большой Сочи"
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    country: Mapped[Country] = relationship("Country", passive_deletes=True)


class LocationHub(Base):
    """Фиксированные узлы (хабы): Аэропорты, Вокзалы, Популярные Отели."""

    __tablename__ = "location_hubs"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("city_regions.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(150), index=True)  # "Аэропорт Минеральные Воды"
    address: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(30))  # "airport", "railway", "hotel"

    # Стандартные числа для позиционирования маркеров на фронтенде
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    region: Mapped[CityRegion] = relationship("CityRegion", passive_deletes=True)


class TransferRoute(Base):
    """Тарифные направления (Хаб А -> Хаб Б)."""

    __tablename__ = "transfer_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_location_id: Mapped[int] = mapped_column(ForeignKey("location_hubs.id", ondelete="CASCADE"), index=True)
    to_location_id: Mapped[int] = mapped_column(ForeignKey("location_hubs.id", ondelete="CASCADE"), index=True)

    distance_km: Mapped[float] = mapped_column(Float)
    estimated_time_min: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    from_location: Mapped[LocationHub] = relationship("LocationHub", foreign_keys=[from_location_id])
    to_location: Mapped[LocationHub] = relationship("LocationHub", foreign_keys=[to_location_id])
    prices: Mapped[list[RoutePrice]] = relationship("RoutePrice", back_populates="route", cascade="all, delete-orphan")


class RoutePrice(Base):
    """Фиксированная стоимость маршрута за конкретный класс авто."""

    __tablename__ = "route_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("transfer_routes.id", ondelete="CASCADE"), index=True)
    car_class: Mapped[str] = mapped_column(String(20), default=CarClass.ECONOMY.value, index=True)
    price: Mapped[float] = mapped_column(Float)

    route: Mapped[TransferRoute] = relationship("TransferRoute", back_populates="prices")
