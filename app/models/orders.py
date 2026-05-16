# from __future__ import annotations
# from datetime import datetime
# from enum import StrEnum
# from typing import TYPE_CHECKING
# from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, func
# from sqlalchemy.orm import Mapped, mapped_column, relationship
# from app.infra.db import Base

# if TYPE_CHECKING:
#     from .excursions import Excursion
#     from .spatial import TransferRoute
#     from .user import User
#     from .user_profiles import SupplierProfile, TripGuideProfile


# class OrderStatus(StrEnum):
#     PENDING = "pending"             # Клиент создал заказ, ждем подтверждения от гида/водителя
#     CONFIRMED = "confirmed"         # Исполнитель подтвердил, ждем оплату от клиента
#     PAID = "paid"                   # Клиент оплатил, деньги заморожены (Hold)
#     IN_PROGRESS = "in_progress"     # Экскурсия или трансфер выполняются прямо сейчас
#     COMPLETED = "completed"         # Успешно завершено (деньги отправляются исполнителю)
#     CANCELLED = "cancelled"         # Отменено клиентом или системой до выполнения
#     REJECTED = "rejected"           # Исполнитель отклонил заявку на этапе pending
#     DISPUTE = "dispute"             # Открыт спор/арбитраж (клиент недоволен качеством)


# class Order(Base):
#     """
#     Центральная таблица бронирований маркетплейса.
#     Объединяет трансферы и экскурсии в единую систему учета.
#     """
#     __tablename__ = "orders"

#     id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    
#     # Кто заказывает услугу
#     client_id: Mapped[int] = mapped_column(
#         BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, comment="ID клиента"
#     )

#     # --- Контекст заказа (Заполняется только ОДНО из этих полей) ---
#     transfer_route_id: Mapped[int | None] = mapped_column(
#         ForeignKey("transfer_routes.id", ondelete="RESTRICT"), nullable=True, index=True, 
#         comment="Ссылка на маршрут, если это трансфер"
#     )
#     excursion_id: Mapped[int | None] = mapped_column(
#         BigInteger, ForeignKey("excursions.id", ondelete="RESTRICT"), nullable=True, index=True, 
#         comment="Ссылка на карточку экскурсии, если это экскурсия"
#     )

#     # --- Назначенный исполнитель (Заполняется только ОДНО из этих полей) ---
#     supplier_profile_id: Mapped[int | None] = mapped_column(
#         BigInteger, ForeignKey("supplier_profiles.id", ondelete="RESTRICT"), nullable=True, index=True,
#         comment="Кто везет (водитель)"
#     )
#     guide_profile_id: Mapped[int | None] = mapped_column(
#         BigInteger, ForeignKey("trip_guide_profiles.id", ondelete="RESTRICT"), nullable=True, index=True,
#         comment="Кто проводит (гид)"
#     )

#     # --- Статус и Время исполнения ---
#     status: Mapped[OrderStatus] = mapped_column(
#         String(30), default=OrderStatus.PENDING, server_default="pending", index=True
#     )
#     execution_at: Mapped[datetime] = mapped_column(
#         DateTime(timezone=True), index=True, comment="Дата и время начала поездки или экскурсии"
#     )

#     # --- Финансовый блок (Прайс-фриз) ---
#     total_price: Mapped[float] = mapped_column(Float, comment="Итоговая стоимость для клиента")
#     service_commission: Mapped[float] = mapped_column(Float, comment="Заработок платформы (включен в total_price)")
#     currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")

#     # --- Дополнительные параметры ---
#     pax_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1", 
#     comment="Количество пассажиров/туристов")
#     client_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Пожелания, детали по встрече")

#     # --- Таймстампы для аналитики ---
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
#     updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), 
#     onupdate=func.now())

#     # --- ORM Связи ---
#     client: Mapped[User] = relationship("User", foreign_keys=[client_id])
#     transfer_route: Mapped[TransferRoute | None] = relationship("TransferRoute")
#     excursion: Mapped[Excursion | None] = relationship("Excursion")
#     supplier: Mapped[SupplierProfile | None] = relationship("SupplierProfile")
#     guide: Mapped[TripGuideProfile | None] = relationship("TripGuideProfile")
    
#     # Связи с будущими таблицами отзывов и логов
#     status_history: Mapped[list[OrderStatusLog]] = relationship(
#         "OrderStatusLog", back_populates="order", cascade="all, delete-orphan"
#     )


# class OrderStatusLog(Base):
#     """
#     История изменения статусов заказа.
#     Необходима для разбора спорных ситуаций (когда именно гид отменил заказ, во сколько клиент оплатил).
#     """
#     __tablename__ = "order_status_logs"

#     id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
#     order_id: Mapped[int] = mapped_column(
#         BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), index=True
#     )
    
#     from_status: Mapped[str | None] = mapped_column(String(30), comment="Старый статус")
#     to_status: Mapped[str] = mapped_column(String(30), comment="Новый статус")
    
#     # Кто перевел статус (может быть сам клиент, исполнитель через приложение или система по таймауту)
#     changed_by_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
#     reason: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Причина отмены/отклонения")
    
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

#     order: Mapped[Order] = relationship("Order", back_populates="status_history")
#     changed_by: Mapped[User] = relationship("User")