from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.excursions import Excursion, ExcursionSlot
from app.models.orders import Order, OrderStatus


class ExcursionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, excursion_id: int) -> Excursion | None:
        """Получить карточку со всеми медиа-файлами по ID."""
        stmt = select(Excursion).options(joinedload(Excursion.medias)).where(Excursion.id == excursion_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_active_excursions_by_region(self, region_id: int) -> Sequence[Excursion]:
        """Выборка верифицированных и включенных экскурсий в конкретном регионе."""
        stmt = (
            select(Excursion)
            .options(joinedload(Excursion.medias))
            .where(Excursion.region_id == region_id, Excursion.is_active.is_(True), Excursion.is_verified.is_(True))
            .order_by(Excursion.price.asc())
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def add_excursion(self, excursion: Excursion) -> Excursion:
        self.db.add(excursion)
        return excursion

    async def add_slot(self, slot: ExcursionSlot) -> ExcursionSlot:
        self.db.add(slot)
        return slot

    async def get_slots_by_excursion(self, excursion_id: int) -> Sequence[ExcursionSlot]:
        """Возвращает календарь будущих активных выездов, где есть свободные места."""
        stmt = (
            select(ExcursionSlot)
            .where(
                ExcursionSlot.excursion_id == excursion_id,
                ExcursionSlot.is_active.is_(True),
                ExcursionSlot.execution_at > func.now(),
                ExcursionSlot.available_slots > 0,
            )
            .order_by(ExcursionSlot.execution_at.asc())
        )
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def get_slot_for_update_atomic(self, slot_id: int) -> ExcursionSlot | None:
        """Захват слота с блокировкой строки для безопасного бронирования мест."""
        stmt = select(ExcursionSlot).where(ExcursionSlot.id == slot_id).with_for_update(nowait=True)
        try:
            res = await self.db.execute(stmt)
            return res.scalar_one_or_none()
        except OperationalError:
            return None

    async def delete_excursion(self, excursion: Excursion) -> None:
        """Физическое удаление объекта экскурсии из сессии базы данных."""
        await self.db.delete(excursion)

    async def count_active_orders_for_excursion(self, excursion_id: int) -> int:
        """Подсчитывает количество оплаченных и активных заказов, привязанных к экскурсии."""
        active_statuses = [
            OrderStatus.SEARCHING_PERFORMER,
            OrderStatus.ASSIGNED,
            OrderStatus.IN_PROGRESS,
        ]

        stmt = select(func.count(Order.id)).where(Order.excursion_id == excursion_id, Order.status.in_(active_statuses))
        res = await self.db.execute(stmt)
        return res.scalar() or 0

    async def get_excursion_ids_by_guides(self, guide_ids: list[int]) -> Sequence[int]:
        """
        Находит ID всех экскурсий, связанных с переданным списком идентификаторов гидов.
        Необходим для корректного сбора префиксов S3 перед физическим удалением каскадов СУБД.
        """
        if not guide_ids:
            return []
        stmt = select(Excursion.id).where(Excursion.guide_profile_id.in_(guide_ids))
        res = await self.db.execute(stmt)
        return res.scalars().all()
