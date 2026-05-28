from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

if TYPE_CHECKING:
    from .orders import Order
    from .user import User


class TransactionType(enum.StrEnum):
    PAYMENT = "payment"  # Блокировка денег на карте клиента (Входящий HOLD)
    PAYOUT = "payout"  # Выплата исполнителю на карту/счет
    REFUND = "refund"  # Разблокировка холда или возврат клиенту
    COMMISSION = "commission"  # Фиксация чистой прибыли маркетплейса


class TransactionStatus(enum.StrEnum):
    HOLD = "hold"  # Банк успешно заморозил средства
    SUCCESS = "success"  # Деньги списаны с холда или успешно выплачены
    FAILED = "failed"  # Банк отклонил операцию


class Transaction(Base):
    """Финансовые транзакции маркетплейса."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True)

    amount: Mapped[float] = mapped_column(Float, comment="Сумма операции")
    currency: Mapped[str] = mapped_column(String(3), default="RUB")

    type_transaction: Mapped[TransactionType] = mapped_column(Enum(TransactionType, native_enum=False), index=True)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, native_enum=False), default=TransactionStatus.HOLD, index=True
    )

    # Ссылка на транзакцию внутри ЮKassa, Т-Банка или CloudPayments
    external_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    order: Mapped[Order] = relationship("Order")
    user: Mapped[User] = relationship("User")
