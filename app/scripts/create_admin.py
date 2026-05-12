import asyncio
import logging
import sys

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db import async_session_maker, engine
from app.infra.redis import get_redis_client
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService

logger = logging.getLogger("app.scripts.create_admin")


class AdminPromoter:
    """Оркестратор процесса назначения администратора."""

    def __init__(self, session: AsyncSession, redis_client: "Redis[str]") -> None:
        self.session = session
        self.repo = UserRepository(session)
        self.auth = AuthService(session, redis_client)

    async def execute(self, phone: str) -> None:
        user = await self.repo.get_by_phone_include_deleted(phone)

        if not user:
            logger.error(f"Пользователь {phone} не найден.")
            return

        # ИСПРАВЛЕНО: Проверяем через поле role или флаг суперюзера
        if user.role == "admin" and user.is_superuser:
            logger.info(f"Пользователь {phone} уже является главным администратором.")
            return

        await self._promote(user)
        logger.info(f"Права СУПЕР-администратора для {phone} успешно выданы.")

    async def _promote(self, user: User) -> None:
        """Атомарная операция повышения прав до Суперюзера."""
        # ИСПРАВЛЕНО: Устанавливаем новую роль и статус владельца
        user.role = "admin"
        user.is_superuser = True

        await self.session.commit()
        # Сброс сессий мгновенно аннулирует старые токены 'customer'
        await self.auth.logout_all(user.id)


async def main(phone: str) -> None:
    redis = await get_redis_client()
    async with async_session_maker() as session:
        promoter = AdminPromoter(session, redis)
        await promoter.execute(phone)

    await engine.dispose()


if __name__ == "__main__":
    # Выносим получение телефона в переменную, чтобы код был читаемее
    if len(sys.argv) < 2:
        print("Usage: python -m app.scripts.promote_admin <phone>")
        sys.exit(1)

    target_phone = sys.argv[1]
    asyncio.run(main(target_phone))
