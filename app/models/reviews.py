from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

if TYPE_CHECKING:
    from .orders import Order
    from .user import User


class OrderReview(Base):
    """Единая таблица отзывов маркетплейса с автоматическим разделением ролей."""

    __tablename__ = "order_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    # Защита от фрода: на один заказ можно оставить ровно один отзыв
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Кто оценивает (Клиент / Пассажир / Турист)
    client_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))

    # Кого оценивают (ID пользователя из таблицы users, который был performer_id в заказе)
    performer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Оценка (от 1 до 5 звезд)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Текстовый отзыв")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ORM Связи
    order: Mapped[Order] = relationship("Order")
    client: Mapped[User] = relationship("User", foreign_keys=[client_id])
    performer: Mapped[User] = relationship("User", foreign_keys=[performer_id])
