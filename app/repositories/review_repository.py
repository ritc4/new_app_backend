import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orders import Order
from app.models.reviews import OrderReview
from app.models.user_profiles import SupplierProfile, TripGuideProfile

logger = logging.getLogger("app.repositories.review")


class ReviewRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_review(self, review: OrderReview) -> None:
        self.db.add(review)

    async def get_order_with_context(self, order_id: int) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def calculate_and_update_rating_atomic(self, order: Order) -> None:
        """Вычисляет средний балл и обновляет нужную таблицу (водителя или гида)."""
        if not order.performer_id:
            return

        # 1. Считаем средний балл по всем отзывам этого исполнителя
        avg_stmt = select(func.avg(OrderReview.rating)).where(OrderReview.performer_id == order.performer_id)
        avg_res = await self.db.execute(avg_stmt)
        raw_avg = avg_res.scalar()

        if raw_avg is None:
            return
        new_rating = round(float(str(raw_avg)), 2)

        # 2. Магия ORM: смотрим контекст заказа и обновляем СТРОГО нужную таблицу
        if order.transfer_route_id is not None:
            # Это трансфер -> пишем в профиль водителя
            upd_stmt = (
                update(SupplierProfile).where(SupplierProfile.user_id == order.performer_id).values(rating=new_rating)
            )
            await self.db.execute(upd_stmt)
            logger.info(f"REVIEW_SYSTEM: Обновлен рейтинг водителя {order.performer_id} до {new_rating}")

        elif order.excursion_id is not None:
            # Это экскурсия -> пишем в профиль гида
            upd_stmt = (
                update(TripGuideProfile).where(TripGuideProfile.user_id == order.performer_id).values(rating=new_rating)
            )
            await self.db.execute(upd_stmt)
            logger.info(f"REVIEW_SYSTEM: Обновлен рейтинг гида {order.performer_id} до {new_rating}")
