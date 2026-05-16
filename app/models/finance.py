# from __future__ import annotations
# from datetime import datetime
# from enum import StrEnum
# from typing import TYPE_CHECKING
# from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, func
# from sqlalchemy.orm import Mapped, mapped_column, relationship
# from app.infra.db import Base

# if TYPE_CHECKING:
#     from .orders import Order
#     from .user import User

# class TransactionType(StrEnum):
#     PAYMENT = "payment"       # Списание с карты клиента (Входящий платеж)
#     PAYOUT = "payout"         # Выплата исполнителю на карту/расчетный счет
#     REFUND = "refund"         # Возврат клиенту при отмене
#     COMMISSION = "commission" # Списание комиссии платформы

# class TransactionStatus(StrEnum):
#     HOLD = "hold"             # Деньги заморожены на стороне банка (стадия авторизации)
#     SUCCESS = "success"       # Платеж успешно проведен (клиринг завершен)
#     FAILED = "failed"         # Ошибка платежа (нет денег, отказ банка)

# class Transaction(Base):
#     """Финансовые транзакции маркетплейса."""
#     __tablename__ = "transactions"

#     id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
#     order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
#     user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, 
#     comment="Кто платит или получает")
    
#     amount: Mapped[float] = mapped_column(Float, comment="Сумма операции")
#     currency: Mapped[str] = mapped_column(String(3), default="RUB")
    
#     type_transaction: Mapped[TransactionType] = mapped_column(String(20), index=True)
#     status: Mapped[TransactionStatus] = mapped_column(String(20), default=TransactionStatus.HOLD, index=True)
    
#     # Идентификатор транзакции в платежной системе ( CloudPayments, ЮKassa и т.д.)
#     external_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
#     updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), 
#     onupdate=func.now())

#     order: Mapped[Order] = relationship("Order")
#     user: Mapped[User] = relationship("User")