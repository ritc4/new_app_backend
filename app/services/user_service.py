import asyncio
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import StoragePaths
from app.models.user import User
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import CompleteRegistrationRequest
from app.schemas.user import (
    AdminSchema,
    CustomerSchema,
    FullProfileResponse,
    SupplierSchema,
    TripguideSchema,
    UpdateProfileRequest,
    UserRole,
    UserShort,
)
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
        self.onboarding = OnboardingRepository(db)

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

    async def update_profile(self, user_id: int, data: UpdateProfileRequest) -> User:
        """Обновление ФИО из настроек (как в Яндекс ID)."""
        try:
            # Извлекаем только те поля, которые юзер реально прислал из Flutter
            update_data = data.model_dump(exclude_unset=True)

            if not update_data:
                raise HTTPException(400, "Нет данных для обновления")

            # Вызываем твой универсальный метод репозитория
            user = await self.users.update_user(user_id, **update_data)
            await self.db.commit()

            logger.info(f"User ID {user_id} обновил профиль в настройках: {list(update_data.keys())}")
            return user
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка обновления настроек профиля {user_id}: {e}")
            raise HTTPException(500, "Ошибка при сохранении профиля") from e

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

    async def update_email(self, user_id: int, new_email: str) -> User:
        """Смена почты с обязательным сбросом верификации (Standard Яндекс)."""
        try:
            # 1. Проверка уникальности
            existing_user = await self.users.get_by_email(new_email)
            if existing_user and existing_user.id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Этот Email уже используется другим пользователем"
                )

            # 2. Атомарное обновление через репозиторий
            user = await self.users.update_user(user_id=user_id, email=new_email, is_email_verified=False)

            await self.db.commit()
            logger.info(f"USER_EMAIL_CHANGED: ID {user_id} -> {new_email}. Status: Unverified.")
            return user

        except Exception as e:
            await self.db.rollback()
            # Пробрасываем HTTPException как есть (400 ошибка)
            if isinstance(e, HTTPException):
                raise e
            # Все остальные ошибки превращаем в 500
            logger.error(f"Ошибка обновления Email для User ID {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка при сохранении Email"
            ) from e

    async def _delete_old_s3_object_safe(self, url: str):
        """Делегируем парсинг и удаление профильному сервису."""
        try:
            # S3Service уже знает, как извлечь ключ из URL
            await self.s3.delete_file_by_url(url)
            logger.debug(f"Старый объект S3 удален: {url}")
        except Exception as e:
            logger.error(f"Не удалось удалить старый аватар: {e}")

    async def update_avatar(self, user: User, content_type: str) -> dict:
        # Оставляем валидацию как была
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        if content_type not in allowed_types:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недопустимый тип файла")

        old_photo_url = user.photo_url

        # Генерация пути через core
        object_name = StoragePaths.user_avatar(user.id, content_type)

        try:
            s3_res = await self.s3.get_upload_params(object_name, content_type)
            final_url = s3_res["public_url"]

            await self.users.update_user(user.id, photo_url=final_url)
            await self.db.commit()

            if old_photo_url:
                await self._delete_old_s3_object_safe(old_photo_url)

            return {
                "upload_data": s3_res["upload_data"],
                "photo_url": final_url,
            }
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка S3/DB при обновлении аватара: {e}")
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(500, "Ошибка при подготовке загрузки") from e

    async def delete_account(self, user: User) -> dict:
        """Мягкое удаление. Сохраняем ФИО и проф. роли, но сбрасываем админку."""
        try:
            if user.deleted_at:
                return {"status": "success", "message": "Аккаунт уже ожидает удаления"}

            # ЛОГИКА СМЕНЫ РОЛИ:
            # Если уходящий — админ, принудительно ставим роль "customer".
            # Если supplier или trip_guide — оставляем их роль как есть.
            new_role = user.role
            if user.role == UserRole.ADMIN:
                new_role = UserRole.CUSTOMER

            await self.users.update_user(
                user.id,
                deleted_at=datetime.now(UTC),
                is_active=False,
                role=new_role.value if isinstance(new_role, UserRole) else new_role,
                is_superuser=False,  # Суперюзер всегда снимается
            )

            await self.db.commit()
            await self.auth.logout_all(user.id)

            logger.warning(f"USER_DELETION: ID {user.id} (бывшая роль: {user.role}) помещен в корзину.")

            return {
                "status": "success",
                "message": "Аккаунт удален. У вас есть 30 дней для восстановления профиля при входе.",
            }
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка удаления аккаунта {user.id}: {e}")
            raise HTTPException(500, "Ошибка при удалении") from e

    async def toggle_work_status(self, user: User) -> dict:
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
            status_text = "На работе" if new_status else "Отдыхаю"
            return {"status": "success", "message": f"Ваш статус изменен на: {status_text}"}
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка переключения статуса User {user.id}: {e}")
            raise HTTPException(500, "Ошибка обновления статуса") from e

    async def perform_full_cleanup(self) -> str:
        """
        Комплексная очистка системы (Enterprise стандарт):
        1. Удаление старых временных анкет (Onboarding).
        2. Удаление заброшенных и помеченных на удаление аккаунтов.
        3. Очистка ресурсов (S3 + Redis) для удаляемых пользователей.
        """
        logger.info("CLEANUP_STARTED: Запуск плановой очистки системы...")
        # --- ШАГ 1: Очистка старых анкет онбординга ---
        # Используем локальный импорт во избежание циклической зависимости
        from app.repositories.onboarding_repository import OnboardingRepository

        onboarding_repo = OnboardingRepository(self.db)
        deleted_apps_count = await onboarding_repo.delete_expired_applications()

        # --- ШАГ 2: Поиск кандидатов на удаление аккаунта ---
        abandoned_date = datetime.now(UTC) - timedelta(days=180)
        soft_deleted_date = datetime.now(UTC) - timedelta(days=30)

        stmt = select(User.id).where(
            and_(
                User.is_superuser.is_(False),  # Никогда не удаляем суперюзеров
                or_(
                    # Условие для недореганных (брошенных на старте)
                    (User.first_name.is_(None) & (User.last_active < abandoned_date)),
                    # Условие для тех, кто сам нажал "Удалить"
                    (User.deleted_at.is_not(None) & (User.deleted_at < soft_deleted_date)),
                ),
            )
        )

        res = await self.db.execute(stmt)
        users_to_purge = res.scalars().all()

        # Если чистить нечего — выходим быстро
        if not users_to_purge and deleted_apps_count == 0:
            logger.info("CLEANUP_SKIPPED: Нет данных для удаления.")
            return "Очистка завершена: новых данных для удаления нет."

        total_users = len(users_to_purge)
        batch_size = 100
        purged_ids = []

        # --- ШАГ 3: Очистка внешних ресурсов (S3 + Redis) ---
        # Используем один S3 клиент (Keep-Alive) для всей пачки
        async with self.s3.session.client("s3", config=self.s3.s3_config, **self.s3.client_kwargs) as s3_client:
            for i in range(0, total_users, batch_size):
                batch = users_to_purge[i : i + batch_size]

                # Запускаем задачи очистки для текущего батча
                cleanup_tasks = [self._purge_resources_by_data(user_id, s3_client) for user_id in batch]
                # return_exceptions=True чтобы ошибка одного юзера не остановила весь процесс
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)

                purged_ids.extend(batch)

        # --- ШАГ 4: Окончательное удаление из БД ---
        if purged_ids:
            # Каскадное удаление (ondelete="CASCADE") само очистит связанные профили
            await self.db.execute(delete(User).where(User.id.in_(purged_ids)))

        # Фиксируем все изменения (и анкеты, и пользователей)
        await self.db.commit()

        report = f"Удалено анкет: {deleted_apps_count}, удалено пользователей: {len(purged_ids)}"
        logger.info(f"FULL_CLEANUP_SUCCESS: {report}")
        return report

    async def _purge_resources_by_data(self, user_id: int, s3_client):
        """Очистка всех ресурсов пользователя (Redis + ВСЕ файлы S3)."""
        # 1. Инвалидация всех сессий в Redis
        # 2. Удаление всех файлов из S3, где в пути есть 'user_{id}/'
        tasks = [self.auth.logout_all(user_id), self.s3.delete_all_user_files(user_id, client=s3_client)]

        # return_exceptions=True гарантирует, что если у юзера не было файлов в S3,
        # процесс не прервется ошибкой.
        await asyncio.gather(*tasks, return_exceptions=True)

    async def get_full_profile(self, user: User) -> FullProfileResponse:
        """
        Композиция профиля.
        Предполагается, что связанные профили уже подгружены в объекте user.
        """
        # 1. Базовая часть юзера
        user_base = UserShort.model_validate(user)
        response = FullProfileResponse(user=user_base)

        # 2. Логика по ролям
        if user.role == UserRole.CUSTOMER:
            # Статус онбординга проверяем асинхронно, так как это отдельная таблица
            app = await self.onboarding.get_pending_by_user(user.id)
            if app:
                response.customer_data = CustomerSchema(
                    onboarding_status=app.status,
                    onboarding_error=app.admin_comment,
                )

        elif user.role == UserRole.SUPPLIER:
            # Пользуемся тем, что профиль уже в памяти
            if user.supplier_profile:
                response.supplier_data = SupplierSchema.model_validate(user.supplier_profile)

        elif user.role == UserRole.TRIP_GUIDE:
            # Пользуемся тем, что профиль уже в памяти
            if user.trip_guide_profile:
                response.trip_guide_data = TripguideSchema.model_validate(user.trip_guide_profile)

        elif user.role == UserRole.ADMIN:
            response.admin_data = AdminSchema(access_level=user.level)

        return response
