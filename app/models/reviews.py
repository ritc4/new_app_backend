# from datetime import datetime
# from enum import StrEnum
# from typing import TYPE_CHECKING

# from sqlalchemy import ForeignKey, Integer, String, Text, func
# from sqlalchemy.orm import Mapped, mapped_column, relationship

# from app.infra.db import Base

# if TYPE_CHECKING:
#     from .user import User


# class ReviewTargetType(StrEnum):
#     SUPPLIER = "supplier"  # Отзыв на водителя
#     TRIP_GUIDE = "trip_guide"  # Отзыв на гида
#     EXCURSION = "excursion"  # Отзыв на конкретную экскурсию


# class Review(Base):
#     """Маркетплейс-система отзывов и оценок."""

#     __tablename__ = "reviews"

#     id: Mapped[int] = mapped_column(primary_key=True)
#     author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

#     target_type: Mapped[ReviewTargetType] = mapped_column(String(20), index=True)
#     target_id: Mapped[int] = mapped_column(index=True)  # ID профиля водителя или гида

#     rating: Mapped[int] = mapped_column(Integer)
#     comment: Mapped[str | None] = mapped_column(Text, nullable=True)
#     created_at: Mapped[datetime] = mapped_column(server_default=func.now())

#     author: Mapped[User] = relationship("User")
