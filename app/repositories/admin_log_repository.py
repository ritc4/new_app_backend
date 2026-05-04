from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_log import AdminLog


class AdminLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_admin_log(self, admin_id: int, target_id: int, action: str, details: dict = None):
        log = AdminLog(admin_id=admin_id, target_id=target_id, action=action, details=details)
        self.db.add(log)
