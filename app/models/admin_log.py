from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Импорт для типизации связей
if TYPE_CHECKING:
    from .user import User


class AdminLog(Base):
    """Журнал аудита: кто, что и над кем сделал."""

    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)

    # Кто совершил действие
    admin_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    # Над кем совершено действие
    target_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))

    # Действия: 'ban', 'unban', 'role_change', 'phone_change'
    action: Mapped[str] = mapped_column(String(50), index=True)

    # Храним старое и новое значение (например, старую и новую роль)
    # Типизируем как dict[str, Any] для удобства работы в Python
    details: Mapped[dict[str, object] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Определение связей
    # Важно: указываем список конкретных колонок [admin_id] и [target_id]
    admin: Mapped[User] = relationship("User", foreign_keys=[admin_id])
    target: Mapped[User] = relationship("User", foreign_keys=[target_id])
