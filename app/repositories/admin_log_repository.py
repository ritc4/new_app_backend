from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_log import AdminLog


class AdminLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_admin_log(
        self,
        admin_id: int,
        target_id: int,
        action: str,
        details: dict[str, object] | None = None,
    ) -> None:
        log = AdminLog(admin_id=admin_id, target_id=target_id, action=action, details=details)
        self.db.add(log)

    async def get_admin_logs(self, admin_id: int | None = None, limit: int = 20, offset: int = 0) -> Sequence[AdminLog]:
        """
        Получение списка логов с пагинацией.
        Защищает базу от падения при миллионах записей.
        """
        stmt = select(AdminLog).order_by(AdminLog.id.desc()).limit(limit).offset(offset)
        if admin_id:
            stmt = stmt.where(AdminLog.admin_id == admin_id)

        res = await self.db.execute(stmt)
        return res.scalars().all() 
