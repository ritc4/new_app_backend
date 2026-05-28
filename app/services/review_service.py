import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orders import OrderStatus
from app.models.reviews import OrderReview
from app.repositories.review_repository import ReviewRepository
from app.schemas.reviews import CreateReviewRequest, CreateReviewSuccessResponse, ReviewResponse

logger = logging.getLogger("app.services.review")


class ReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ReviewRepository(db)

    async def create_review(self, client_id: int, data: CreateReviewRequest) -> CreateReviewSuccessResponse:
        """Универсальное создание отзывов без дублирования кода."""
        order = await self.repo.get_order_with_context(data.order_id)

        if not order:
            raise HTTPException(status_code=404, detail="Заказ не найден.")
        if order.client_id != client_id:
            raise HTTPException(status_code=403, detail="Вы не можете оценивать чужой заказ.")
        if order.status != OrderStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="Оценить услугу можно только после её завершения.")
        if not order.performer_id:
            raise HTTPException(status_code=400, detail="На этот заказ не назначен исполнитель.")

        try:
            # 1. Записываем отзыв
            new_review = OrderReview(
                order_id=order.id,
                client_id=client_id,
                performer_id=order.performer_id,
                rating=data.rating,
                comment=data.comment,
            )
            await self.repo.add_review(new_review)
            await self.db.flush()

            # 2. Вызываем атомарный пересчет в репозитории
            await self.repo.calculate_and_update_rating_atomic(order)

            await self.db.commit()
            return CreateReviewSuccessResponse(
                status="success",
                message="Спасибо! Ваш отзыв успешно сохранен.",
                review=ReviewResponse.model_validate(new_review),
            )

        except Exception as e:
            await self.db.rollback()
            from sqlalchemy.exc import IntegrityError

            if isinstance(e, IntegrityError):
                raise HTTPException(status_code=400, detail="Вы уже оставили отзыв на этот заказ.") from e
            logger.error(f"Ошибка сохранения отзыва: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Не удалось сохранить отзыв.") from e
