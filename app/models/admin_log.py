from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.infra.db import Base


class AdminLog(Base):
    """Журнал аудита: кто, что и над кем сделал."""

    __tablename__ = "admin_logs"

    id = Column(BigInteger, primary_key=True, index=True)
    admin_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Действия: 'ban', 'unban', 'role_change', 'phone_change'
    action = Column(String(50), nullable=False, index=True)

    # Храним старое и новое значение (например, старую и новую роль)
    details = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    admin = relationship("User", foreign_keys="AdminLog.admin_id")
    target = relationship("User", foreign_keys="AdminLog.target_id")
