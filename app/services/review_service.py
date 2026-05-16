# import logging

# from sqlalchemy import func, update
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy.future import select

# from app.models.reviews import Review, ReviewTargetType
# from app.models.user_profiles import SupplierProfile

# logger = logging.getLogger("app.services")


# class ReviewService:
#     def __init__(self, db: AsyncSession) -> None:
#         self.db = db

#     async def add_review(
#         self, author_id: int, target_type: ReviewTargetType, target_id: int, rating: int, comment: str
#     ) -> None:
#         # 1. Сохраняем отзыв в базу
#         new_review = Review(
#             author_id=author_id, target_type=target_type, target_id=target_id, rating=rating, comment=comment
#         )
#         self.db.add(new_review)
#         await self.db.flush()

#         # 2. Асинхронно пересчитываем средний рейтинг
#         if target_type == ReviewTargetType.SUPPLIER:
#             avg_rating = await self.db.scalar(
#                 select(func.avg(Review.rating)).where(
#                     Review.target_type == ReviewTargetType.SUPPLIER, Review.target_id == target_id
#                 )
#             )

#             # Избегаем ошибки, если отзывов еще нет (avg_rating ис None)
#             final_rating = round(float(avg_rating), 2) if avg_rating else 0.0

#             # Обновляем кешированное поле в профиле
#             await self.db.execute(
#                 update(SupplierProfile).where(SupplierProfile.id == target_id).values(rating=final_rating)
#             )

#         await self.db.commit()
