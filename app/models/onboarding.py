from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Импорт для линтеров
if TYPE_CHECKING:
    from .user import User


class OnboardingApplication(Base):
    """Очередь регистрации партнеров (водителей/гидов)."""

    __tablename__ = "onboarding_applications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    # Обязательные поля (без | None)
    target_role: Mapped[str] = mapped_column(String(20))  # supplier / trip_guide
    status: Mapped[str] = mapped_column(
        String(20),
        server_default="pending_legal",
        default="pending_legal",
    )  # pending_legal, filling_survey, on_moderation, approved, canceled

    # Данные от банка (Optional)
    bank_type: Mapped[str | None] = mapped_column(String(20))  # sber / t_bank
    external_id: Mapped[str | None] = mapped_column(String(100))  # ID связки из банка
    inn: Mapped[str | None] = mapped_column(String(12))
    admin_comment: Mapped[str | None] = mapped_column(String(255))

    # Анкета (СТС машины или навыки гида)
    # Используем dict | None для удобной работы с JSON-объектом
    survey_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связь с User
    # Используем Mapped["User"], SQLAlchemy сама сопоставит ForeignKey
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
