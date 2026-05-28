from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

if TYPE_CHECKING:
    from .excursions import Excursion
    from .spatial import TransferRoute
    from .user import User


class OrderStatus(enum.StrEnum):
    PENDING_PAYMENT = "pending_payment"  # Создан во Flutter, создается платежная ссылка
    SEARCHING_PERFORMER = "searching"  # Оплачен (деньги на HOLD), ищет водителя/гида на бирже
    ASSIGNED = "assigned"  # Исполнитель назначен, ожидает даты выполнения
    IN_PROGRESS = "in_progress"  # Экскурсия проводится или трансфер в пути
    COMPLETED = "completed"  # Завершено успешно (команда банку на списание денег с HOLD)
    CANCELLED = "cancelled"  # Отменено клиентом или системой до выполнения
    REJECTED = "rejected"  # Исполнитель отклонил персональную заявку
    DISPUTE = "dispute"  # Арбитраж (клиент недоволен качеством выполнения)


class Order(Base):
    """Центральная таблица бронирований маркетплейса."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, comment="ID клиента"
    )
    performer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="ID назначенного исполнителя (водитель или гид)",
    )

    # --- Контекст услуги (Заполняется только ОДНО из полей) ---
    transfer_route_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_routes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    excursion_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("excursions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # --- Замороженные параметры на момент покупки ---
    car_class: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True, comment="Выбранный тариф авто")
    flight_number: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="Номер рейса/поезда")

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False), default=OrderStatus.PENDING_PAYMENT, index=True
    )
    execution_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, comment="Дата и время старта услуги"
    )

    # --- Финансовый блок ---
    total_price: Mapped[float] = mapped_column(Float, comment="Цена для туриста")
    service_commission: Mapped[float] = mapped_column(Float, comment="Заработок платформы")
    currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")

    pax_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    client_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- ORM Связи ---
    client: Mapped[User] = relationship("User", foreign_keys=[client_id], back_populates="client_orders")
    performer: Mapped[User | None] = relationship(
        "User", foreign_keys=[performer_id], back_populates="performer_orders"
    )
    transfer_route: Mapped[TransferRoute | None] = relationship("TransferRoute")
    excursion: Mapped[Excursion | None] = relationship("Excursion")

    status_history: Mapped[list[OrderStatusLog]] = relationship(
        "OrderStatusLog", back_populates="order", cascade="all, delete-orphan"
    )


class OrderStatusLog(Base):
    """История изменения состояний для таймлайнов во Flutter."""

    __tablename__ = "order_status_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), index=True)

    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    changed_by_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship("Order", back_populates="status_history")
    changed_by: Mapped[User] = relationship("User")
