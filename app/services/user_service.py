import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import CompleteRegistrationRequest
from app.services.auth_service import AuthService
from app.services.s3_service import S3Service

# Иерархическое имя логгера для Enterprise-мониторинга
logger = logging.getLogger("app.services.user")


class UserService:
    def __init__(self, db: AsyncSession, s3: S3Service, auth_service: AuthService):
        self.db = db
        self.s3 = s3
        self.auth = auth_service
        self.users = UserRepository(db)

    async def complete_registration(self, user_id: int, data: CompleteRegistrationRequest) -> User:
        """Завершение регистрации с фиксацией транзакции."""
        try:
            # Используем универсальный update_user из репозитория
            updated_user = await self.users.update_user(
                user_id=user_id, first_name=data.first_name, last_name=data.last_name
            )

            await self.db.commit()
            logger.info(f"Профиль User ID {user_id} успешно обновлен.")
            return updated_user
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка регистрации User ID {user_id}: {e}")
            raise HTTPException(500, "Ошибка сохранения данных") from e

    async def update_username(self, user_id: int, username: str) -> User:
        """Обновление ника с проверкой уникальности."""
        try:
            existing_user = await self.users.get_by_username(username)
            if existing_user and existing_user.id != user_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ник занят")

            user = await self.users.update_user(user_id, username=username)
            await self.db.commit()
            logger.info(f"User ID {user_id} сменил ник на '{username}'")
            return user
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка обновления ника") from e

    async def _delete_old_s3_object_safe(self, url: str):
        """Делегируем парсинг и удаление профильному сервису."""
        try:
            # S3Service уже знает, как извлечь ключ из URL
            await self.s3.delete_file_by_url(url)
            logger.debug(f"Старый объект S3 удален: {url}")
        except Exception as e:
            logger.error(f"Не удалось удалить старый аватар: {e}")

    async def update_avatar(self, user: User, content_type: str) -> dict:
        """Подготовка к загрузке через Presigned POST."""
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        if content_type not in allowed_types:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недопустимый тип файла")

        old_photo_url = user.photo_url
        file_ext = allowed_types[content_type]
        object_name = f"avatars/user_{user.id}/{uuid.uuid4()}.{file_ext}"

        try:
            # 1. Данные для POST загрузки
            presigned_data = await self.s3.get_upload_params(object_name, content_type)

            # 2. Формируем финальный публичный URL
            base_url = settings.s3.endpoint_url.rstrip("/")
            final_url = f"{base_url}/{settings.s3.bucket_name}/{object_name}"

            # 3. Обновляем БД
            await self.users.update_user(user.id, photo_url=final_url)
            await self.db.commit()

            # 4. Удаляем старый файл (только если URL был и БД успешно обновилась)
            if old_photo_url:
                await self._delete_old_s3_object_safe(old_photo_url)

            return {
                "upload_data": presigned_data,
                "photo_url": final_url,
            }
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка S3/DB при обновлении аватара: {e}")
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(500, "Ошибка при подготовке загрузки") from e

    async def delete_account(self, user: User) -> None:
        """Мягкое удаление (Soft Delete) и сброс сессий."""
        try:
            if user.deleted_at:
                return

            # ИЗМЕНЕНИЕ: Используем репозиторий для согласованности слоев
            await self.users.update_user(
                user.id,
                deleted_at=datetime.now(UTC),
                is_active=False,
                role="customer",  # Сбрасываем роль
                is_superuser=False,  # Снимаем статус владельца
            )

            await self.db.commit()
            await self.auth.logout_all(user.id)

            logger.warning(f"Аккаунт User {user.id} помечен на удаление.")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка удаления аккаунта {user.id}: {e}")
            raise HTTPException(500, "Ошибка при удалении") from e

    async def toggle_work_status(self, user: User) -> bool:
        """Переключает статус: доступен для заказов / занят (офлайн)."""
        # БИЗНЕС-ПРАВИЛО: Кнопка работает только для тех, у кого уровень доступа 20 (воркеры)
        # Админам (50) и Суперюзерам (100) тоже разрешаем для тестов
        if user.level < 20:
            raise HTTPException(status_code=403, detail="Только исполнители услуг могут менять статус доступности")

        try:
            new_status = not user.is_available
            await self.users.update_user(user.id, is_available=new_status)
            await self.db.commit()

            logger.info(f"User {user.id} (role: {user.role}) изменил статус на: {new_status}")
            return new_status
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка переключения статуса User {user.id}: {e}")
            raise HTTPException(500, "Ошибка обновления статуса") from e

    async def perform_full_cleanup(self) -> str:
        """Массовая очистка заброшенных аккаунтов (Enterprise Highload стандарт)."""

        abandoned_date = datetime.now(UTC) - timedelta(days=180)
        soft_deleted_date = datetime.now(UTC) - timedelta(days=30)

        # 1. Получаем список кандидатов
        stmt = select(User.id, User.photo_url).where(
            and_(
                User.is_superuser.is_(False),  # ГЛАВНОЕ УСЛОВИЕ: только не суперюзеры
                or_(
                    # Условие для заброшенных (недореганных)
                    (User.first_name.is_(None) & (User.last_active < abandoned_date)),
                    # Условие для тех, кто сам нажал "Удалить аккаунт"
                    (User.deleted_at.is_not(None) & (User.deleted_at < soft_deleted_date)),
                ),
            )
        )

        res = await self.db.execute(stmt)
        users_to_purge = res.all()

        if not users_to_purge:
            return "Удалено: 0"

        total_users = len(users_to_purge)
        batch_size = 100
        purged_ids = []

        # 2. Оптимизация: Открываем ОДИН клиент S3 на весь процесс очистки
        # Это позволяет использовать одно TCP-соединение (Keep-Alive) для всех удалений
        async with self.s3.session.client("s3", config=self.s3.s3_config, **self.s3.client_kwargs) as s3_client:
            for i in range(0, total_users, batch_size):
                batch = users_to_purge[i : i + batch_size]

                # Прокидываем s3_client в каждую задачу пачки
                cleanup_tasks = [self._purge_resources_by_data(u.id, u.photo_url, s3_client) for u in batch]
                await asyncio.gather(*cleanup_tasks)

                purged_ids.extend([u.id for u in batch])

        # 3. Bulk Delete
        if purged_ids:
            bulk_del_stmt = delete(User).where(User.id.in_(purged_ids))
            await self.db.execute(bulk_del_stmt)
            await self.db.commit()

        return f"Окончательно очищено пользователей: {len(purged_ids)}"

    async def _purge_resources_by_data(self, user_id: int, photo_url: str | None, s3_client):
        """Очистка ресурсов с переиспользованием S3 клиента."""
        # 1. Сброс сессий в Redis
        tasks = [self.auth.logout_all(user_id)]

        # 2. Удаление фото из S3 (если есть) через общий клиент
        if photo_url:
            tasks.append(self.s3.delete_file_by_url(photo_url, client=s3_client))

        # return_exceptions=True важен, чтобы ошибка одного юзера не прервала всю пачку
        await asyncio.gather(*tasks, return_exceptions=True)
