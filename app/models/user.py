from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.infra.db import Base


class User(Base):
    """
    Модель пользователя, синхронизированная с системой авторизации.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    middle_name = Column(String, nullable=True)
    username = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    phone = Column(String, unique=True, index=True, nullable=False)
    photo_url = Column(String, nullable=True)

    # Роли (имена полей в точности как в твоём verify_otp)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    is_customer = Column(Boolean, default=True, comment="Клиент (экскурсии/трансфер)")
    is_supplier = Column(Boolean, default=False, comment="Поставщик (водитель)")
    is_trip_guide = Column(Boolean, default=False, comment="Пеший гид")

    # Безопасность
    is_banned = Column(Boolean, default=False, comment="Заблокирован ли пользователь")
    # Временные метки
    last_active = Column(DateTime(timezone=True), default=func.now(), comment="Последнее действие")
    created_at = Column(DateTime(timezone=True), default=func.now(), comment="Дата регистрации")

    app_version = Column(
        String, nullable=True, comment="Версия приложения пользователя"
    )
