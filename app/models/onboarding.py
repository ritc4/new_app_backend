from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base

# Импорт для линтеров
if TYPE_CHECKING:
    from .spatial import CityRegion
    from .user import User


class OnboardingApplication(Base):
    """Заявка на регистрацию партнера."""

    __tablename__ = "onboarding_applications"

    __table_args__ = (Index("ix_onboarding_applications_status_created_at", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    target_region_id: Mapped[int] = mapped_column(ForeignKey("city_regions.id", ondelete="RESTRICT"), index=True)

    target_role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), server_default="pending_legal", default="pending_legal")
    bank_type: Mapped[str | None] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(100))
    inn: Mapped[str | None] = mapped_column(String(12))
    admin_comment: Mapped[str | None] = mapped_column(String(255))

    survey_payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    target_region: Mapped[CityRegion] = relationship("CityRegion")
