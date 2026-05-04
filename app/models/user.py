import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.infra.db import Base


class User(Base):
    """
    Модель пользователя, синхронизированная с системой авторизации.
    """

    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)
    # Публичный ID для API и Flutter (безопасный)
    uuid = Column(
        UUID(as_uuid=True), default=uuid.uuid4, server_default=func.gen_random_uuid(), unique=True, index=True
    )
    first_name = Column(String(100), index=True, nullable=True)
    last_name = Column(String(100), nullable=True)
    middle_name = Column(String(100), nullable=True)
    username = Column(String(50), unique=True, index=True, nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    photo_url = Column(String(500), nullable=True)

    # Роли (имена полей в точности как в твоём verify_otp)
    is_active = Column(Boolean, default=True, server_default="true", comment="Доступ пользователя к приложению")
    is_available = Column(Boolean, default=True, comment="Доступность для заказов (кнопка вкл/выкл)")
    is_superuser = Column(Boolean, default=False, server_default="false", comment="Главный администратор")
    role = Column(
        String(20),
        default="customer",
        server_default="customer", 
        nullable=False,
        index=True,
        comment="Роль пользователя",
    )

    # Безопасность
    is_banned = Column(Boolean, default=False, server_default="false", comment="Заблокирован ли пользователь")
    # Временные метки
    last_active = Column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), index=True, comment="Последнее действие"
    )
    created_at = Column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), comment="Дата регистрации"
    )

    app_version = Column(String(50), nullable=True, comment="Версия приложения пользователя")

    deleted_at = Column(
        DateTime(timezone=True), nullable=True, index=True, comment="Время мягкого удаления пользователя"
    )

    @staticmethod
    def get_role_level(role: str, is_superuser: bool = False) -> int:
        if is_superuser:
            return 100
        levels = {"admin": 50, "supplier": 20, "trip_guide": 20, "customer": 10}
        return levels.get(role, 10)

    @property
    def level(self) -> int:
        return self.get_role_level(self.role, self.is_superuser)
