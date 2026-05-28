from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

if TYPE_CHECKING:
    from .spatial import CityRegion
    from .user_profiles import TripGuideProfile


class Excursion(Base):
    """
    Карточки авторских экскурсий, создаваемые гидами.
    Объект продажи в маркетплейсе для пеших и выездных гидов.
    """

    __tablename__ = "excursions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    # К какому гиду принадлежит
    guide_profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("trip_guide_profiles.id", ondelete="CASCADE"),
        index=True,
        comment="Ссылка на профиль гида-создателя",
    )

    # К какому операционному региону относится (из вашей таблицы city_regions)
    region_id: Mapped[int] = mapped_column(
        ForeignKey("city_regions.id", ondelete="RESTRICT"),
        index=True,
        comment="Регион проведения экскурсии (например, Кавминводы)",
    )

    # --- Контентная часть (Карточка на Островке) ---
    title: Mapped[str] = mapped_column(String(150), index=True, comment="Название экскурсии")
    description: Mapped[str] = mapped_column(Text, comment="Детальная программа, нитка маршрута и локации")
    main_photo_url: Mapped[str] = mapped_column(String(500), comment="Главное изображение (превью карточки)")

    # --- Ограничения и Тайминги ---
    duration_hours: Mapped[float] = mapped_column(Float, comment="Продолжительность экскурсии в часах")
    max_people_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="Максимальное количество человек в группе"
    )

    # --- Финансовые параметры ---
    price: Mapped[float] = mapped_column(Float, index=True, comment="Фиксированная стоимость за всю экскурсию/группу")
    currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")

    # --- Статусы комплаенса и модерации ---
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", index=True, comment="Включена ли экскурсия самим гидом"
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        index=True,
        comment="Проверена ли карточка модератором платформы",
    )

    # --- Аудит ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    # --- ORM Связи ---
    guide: Mapped[TripGuideProfile] = relationship("TripGuideProfile", back_populates="excursions")
    region: Mapped[CityRegion] = relationship("CityRegion")

    # Связь с каруселью дополнительных фотографий
    medias: Mapped[list[ExcursionMedia]] = relationship(
        "ExcursionMedia", back_populates="excursion", cascade="all, delete-orphan"
    )
    slots: Mapped[list[ExcursionSlot]] = relationship(
        "ExcursionSlot", back_populates="excursion", cascade="all, delete-orphan"
    )


class ExcursionSlot(Base):
    """Календарная сетка слотов выезда на экскурсии."""

    __tablename__ = "excursion_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    excursion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("excursions.id", ondelete="CASCADE"), index=True)

    # Дата и время начала экскурсии
    execution_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Сколько ВСЕГО мест осталось на этот конкретный выезд
    available_slots: Mapped[int] = mapped_column(Integer, nullable=False)

    # Управляется гидом (можно временно скрыть слот из продажи)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ORM Связь
    excursion: Mapped[Excursion] = relationship("Excursion")


class ExcursionMedia(Base):
    """
    Дополнительные фотографии для карусели в карточке экскурсии.
    Пользователи Островка выбирают глазами, поэтому нужна галерея.
    """

    __tablename__ = "excursion_medias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    excursion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("excursions.id", ondelete="CASCADE"), index=True)

    photo_url: Mapped[str] = mapped_column(String(500), comment="Ссылка на S3-хранилище файлов")
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="Порядок сортировки при показе в карусели приложения"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), server_default=func.now())

    excursion: Mapped[Excursion] = relationship("Excursion", back_populates="medias")
