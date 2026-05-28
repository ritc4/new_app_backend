import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.orders import Order, OrderStatus, OrderStatusLog
from app.models.spatial import LocationHub, TransferRoute

logger = logging.getLogger("app.transfers_repository")


class TransferRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search_hubs_by_name(self, query: str) -> Sequence[LocationHub]:
        """Полнотекстовый поиск хабов для выпадающего списка во Flutter."""
        stmt = select(LocationHub).where(LocationHub.name.ilike(f"%{query}%")).limit(15)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_route_with_prices(self, from_id: int, to_id: int) -> TransferRoute | None:
        """Ищет активный маршрут вместе со связанной сеткой цен."""
        stmt = (
            select(TransferRoute)
            .options(joinedload(TransferRoute.prices))
            .where(
                TransferRoute.from_location_id == from_id,
                TransferRoute.to_location_id == to_id,
                TransferRoute.is_active.is_(True),
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_route_by_id(self, route_id: int) -> TransferRoute | None:
        """Ищет маршрут по ID для верификации цены."""
        stmt = select(TransferRoute).options(joinedload(TransferRoute.prices)).where(TransferRoute.id == route_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def add_order(self, order: Order) -> Order:
        self.db.add(order)
        return order

    async def add_status_log(self, log: OrderStatusLog) -> None:
        self.db.add(log)

    async def get_available_orders_by_region(self, region_id: int, car_class: str) -> Sequence[Order]:
        """
        Выбирает с биржи заказы, которые оплачены (searching),
        относятся к региону водителя и подходят под его класс авто.
        Использует комплексный joinedload для предотвращения N+1 багов на бирже.
        """
        stmt = (
            select(Order)
            .join(TransferRoute, Order.transfer_route_id == TransferRoute.id)
            .join(LocationHub, TransferRoute.from_location_id == LocationHub.id)
            # ИСПРАВЛЕНО: Жёстко подгружаем всю иерархию объектов в 1 SQL-запрос
            .options(
                joinedload(Order.transfer_route).options(
                    joinedload(TransferRoute.from_location), joinedload(TransferRoute.to_location)
                )
            )
            .where(
                Order.status == OrderStatus.SEARCHING_PERFORMER,
                LocationHub.region_id == region_id,
                Order.car_class == car_class,
            )
            .order_by(Order.execution_at.asc())
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_order_for_update_atomic(self, order_id: int) -> Order | None:
        """Точечный захват заказа с ПЕССИМИСТИЧЕСКОЙ БЛОКИРОВКОЙ СУБД FOR UPDATE NOWAIT."""
        stmt = select(Order).where(Order.id == order_id).with_for_update(nowait=True)
        try:
            res = await self.db.execute(stmt)
            return res.scalar_one_or_none()
        except OperationalError:
            return None
