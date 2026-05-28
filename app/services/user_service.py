import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import StoragePaths
from app.models.user import User
from app.repositories.excursion_repository import ExcursionRepository
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import CompleteRegistrationRequest, RegistrationResponse
from app.schemas.base import UserRole
from app.schemas.user import (
    AdminSchema,
    AvailabilityResponse,
    AvatarUploadResponse,
    CustomerSchema,
    DeleteAccountResponse,
    FullProfileResponse,
    SupplierSchema,
    TripguideSchema,
    UpdateEmailResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    UpdateUsernameResponse,
    UserShort,
)
from app.services.auth_service import AuthService
from app.services.s3_service import S3Service

if TYPE_CHECKING:
    pass

# Иерархическое имя логгера для Enterprise-мониторинга
logger = logging.getLogger("app.services.user")


class UserService:
    def __init__(
        self,
        db: AsyncSession,
        s3: S3Service,
        auth_service: AuthService,
        user_repo: UserRepository,
        excursion_repo: ExcursionRepository,
        onboarding_repo: OnboardingRepository,
    ) -> None:
        self.db = db
        self.s3 = s3
        self.auth = auth_service
        self.users = user_repo
        self.excursions = excursion_repo
        self.onboarding = onboarding_repo

    async def complete_registration(self, user_id: int, data: CompleteRegistrationRequest) -> RegistrationResponse:
        """Завершение регистрации с фиксацией транзакции."""
        try:
            # Используем универсальный update_user из репозитория
            updated_user = await self.users.update_user(
                user_id=user_id,
                first_name=data.first_name,
                last_name=data.last_name,
            )

            if not updated_user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
            await self.db.commit()
            logger.info(f"Профиль User ID {user_id} успешно обновлен.")
            return RegistrationResponse(
                status="success",
                message="Регистрация успешно завершена",
                user=UserShort.model_validate(updated_user),
            )
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка регистрации User ID {user_id}: {e}")
            raise HTTPException(500, "Ошибка сохранения данных") from e

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

    async def update_profile(self, user_id: int, data: UpdateProfileRequest) -> UpdateProfileResponse:
        """Обновление ФИО из настроек (как в Яндекс ID)."""
        try:
            # Извлекаем только те поля, которые юзер реально прислал из Flutter
            update_data = data.model_dump(exclude_unset=True)

            if not update_data:
                raise HTTPException(400, "Нет данных для обновления")

            # Вызываем твой универсальный метод репозитория
            user = await self.users.update_user(user_id, **update_data)
            if not user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
            await self.db.commit()

            logger.info(f"User ID {user_id} обновил профиль в настройках: {list(update_data.keys())}")
            return UpdateProfileResponse(
                status="success",
                message="Профиль успешно обновлен",
                user=UserShort.model_validate(user),
            )
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка обновления настроек профиля {user_id}: {e}")
            raise HTTPException(500, "Ошибка при сохранении профиля") from e

    async def update_username(self, user_id: int, username: str) -> UpdateUsernameResponse:
        """Обновление ника с проверкой уникальности."""
        try:
            existing_user = await self.users.get_by_username(username)
            if existing_user and existing_user.id != user_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ник занят")

            user = await self.users.update_user(user_id, username=username)
            if not user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
            await self.db.commit()
            logger.info(f"User ID {user_id} сменил ник на '{username}'")
            return UpdateUsernameResponse(
                status="success",
                message="Ник успешно обновлен",
                user=UserShort.model_validate(user),
            )
        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка обновления ника") from e

    async def update_email(self, user_id: int, new_email: str) -> UpdateEmailResponse:
        """Смена почты с обязательным сбросом верификации (Standard Яндекс)."""
        try:
            # 1. Проверка уникальности
            existing_user = await self.users.get_by_email(new_email)
            if existing_user and existing_user.id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Этот Email уже используется другим пользователем",
                )

            # 2. Атомарное обновление через репозиторий
            user = await self.users.update_user(user_id=user_id, email=new_email, is_email_verified=False)
            if not user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

            await self.db.commit()
            logger.info(f"USER_EMAIL_CHANGED: ID {user_id} -> {new_email}. Status: Unverified.")
            return UpdateEmailResponse(
                status="success",
                message="Email успешно обновлен",
                user=UserShort.model_validate(user),
            )

        except Exception as e:
            await self.db.rollback()
            # Пробрасываем HTTPException как есть (400 ошибка)
            if isinstance(e, HTTPException):
                raise e
            # Все остальные ошибки превращаем в 500
            logger.error(f"Ошибка обновления Email для User ID {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка при сохранении Email",
            ) from e

    async def update_avatar(self, user: User, content_type: str) -> AvatarUploadResponse:
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

            updated_user = await self.users.update_user(user.id, photo_url=final_url)
            if not updated_user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

            await self.db.commit()

            if old_photo_url:
                await self._delete_old_s3_object_safe(old_photo_url)

            return AvatarUploadResponse(
                status="success",
                message="Ссылка для загрузки аватара успешно сформирована",
                upload_data=s3_res["upload_data"],
                photo_url=final_url,
            )
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка S3/DB при обновлении аватара: {e}")
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(500, "Ошибка при подготовке загрузки") from e

    async def delete_account(self, user: User) -> DeleteAccountResponse:
        """Мягкое удаление (Enterprise Standard)."""
        # 1. Выносим срок в константу
        restore_days = 30

        try:
            # Если уже помечен на удаление
            if user.deleted_at:
                # Рассчитываем дату исходя из того, когда было нажато удаление
                limit_date = user.deleted_at + timedelta(days=restore_days)
                return DeleteAccountResponse(
                    status="success",
                    message="Аккаунт уже ожидает удаления",
                    restore_until_days=restore_days,
                    restore_until_date=limit_date,
                    user=UserShort.model_validate(user),
                )

            # 2. Логика смены роли (подготовка значения для репозитория)
            new_role = user.role
            if user.role == UserRole.ADMIN:
                new_role = UserRole.CUSTOMER

            role_value = new_role.value if isinstance(new_role, UserRole) else new_role

            # Фиксируем время удаления прямо сейчас
            deletion_time = datetime.now(UTC)
            limit_date = deletion_time + timedelta(days=restore_days)

            updated_user = await self.users.update_user(
                user_id=user.id,
                deleted_at=deletion_time,
                is_active=False,
                role=role_value,
                is_superuser=False,
            )
            if not updated_user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
            await self.db.commit()
            await self.auth.logout_all(user.id)

            logger.warning(f"USER_DELETION: ID {user.id} помещен в корзину до {limit_date}")

            # 3. Возвращаем строгий объект схемы
            return DeleteAccountResponse(
                status="success",
                message=f"Аккаунт удален. Восстановление возможно до {limit_date.strftime('%d.%m.%Y')}",
                restore_until_days=restore_days,
                restore_until_date=limit_date,
                user=UserShort.model_validate(updated_user),
            )

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка удаления аккаунта {user.id}: {e}")
            raise HTTPException(500, "Ошибка при удалении") from e

    async def toggle_work_status(self, user: User) -> AvailabilityResponse:
        """Переключает статус: доступен для заказов / занят (офлайн)."""

        # 1. ПРОВЕРКА ДОСТУПА (Бизнес-правило ролей)
        if user.level < 20:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Только исполнители услуг могут менять статус доступности"
            )

        # 2. ПРОВЕРКА АКТИВНОЙ РАБОТЫ (Бизнес-правило маркетплейса)
        # Если воркер СЕЙЧАС на линии (user.is_available == True) и хочет уйти (станет False)
        if user.is_available:
            # Делегируем SQL-запрос репозиторию
            has_work = await self.users.has_active_orders(user.id)
            if has_work:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Нельзя уйти с линии, пока у вас есть активный или назначенный заказ!",
                )

        # 3. ТРАНЗАКЦИОННОЕ ОБНОВЛЕНИЕ
        try:
            new_status = not user.is_available

            # Вызываем ваш существующий метод обновления юзера в репозитории
            updated_user = await self.users.update_user(user.id, is_available=new_status)
            if not updated_user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

            await self.db.commit()
            logger.info(f"User {user.id} (role: {user.role}) изменил статус на: {new_status}")

            # 4. СИНХРОНИЗАЦИЯ С ОПЕРАТИВНЫМ КЭШЕМ (Бизнес-логика инфраструктуры)
            # Если водитель ушел с линии — полностью стираем его из Redis GEO
            if not new_status:
                from app.infra.redis import redis_pool

                await redis_pool.delete(f"driver_location:{user.id}")
                await redis_pool.delete(f"driver_active_status:{user.id}")

            status_text = "На работе" if new_status else "Отдыхаю"
            return AvailabilityResponse(
                status="success",
                message=f"Ваш статус изменен на: {status_text}",
                is_available=new_status,
            )

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка переключения статуса User {user.id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка обновления статуса на сервере"
            ) from e

    async def purge_abandoned_and_deleted_users(self) -> str:
        """
        Полная автоматическая зачистка просроченных и брошенных аккаунтов.
        Абсолютно чистая архитектура: СУБД-запросы полностью делегированы репозиторию.
        """
        logger.info("USER_CLEANUP_STARTED: Поиск кандидатов на удаление аккаунтов...")

        abandoned_date = datetime.now(UTC) - timedelta(days=180)
        soft_deleted_date = datetime.now(UTC) - timedelta(days=30)

        # 1. Запрашиваем кандидатов через репозиторий
        expired_users = await self.users.get_expired_and_abandoned_users(
            abandoned_date=abandoned_date, soft_deleted_date=soft_deleted_date
        )

        if not expired_users:
            return "Пользователей для удаления не найдено."

        user_ids_to_delete: list[int] = []
        user_prefixes_to_delete: list[str] = []

        # Накапливаем стабильные префиксы папок согласно вашему StoragePaths
        for user in expired_users:
            u_id = user.id
            u_uuid = str(user.uuid)
            user_ids_to_delete.append(u_id)

            user_prefixes_to_delete.append(f"avatars/user_{u_id}/")
            user_prefixes_to_delete.append(f"onboarding/tmp/user_{u_id}_{u_uuid}/")

        # 2. Собираем ID всех экскурсий удаляемых гидов через репозиторий (до очистки каскадов БД)
        excursion_ids = await self.excursions.get_excursion_ids_by_guides(user_ids_to_delete)

        for exc_id in excursion_ids:
            user_prefixes_to_delete.append(f"excursions/excursion_{exc_id}/")

        # 3. Принудительный логаут сессий в Redis пачками по 100 штук
        redis_batch_size = 100
        for i in range(0, len(user_ids_to_delete), redis_batch_size):
            batch_ids = user_ids_to_delete[i : i + redis_batch_size]
            logout_tasks = [self.auth.logout_all(u_id) for u_id in batch_ids]
            await asyncio.gather(*logout_tasks, return_exceptions=True)

        # 4. Полное каскадное удаление пользователей из PostgreSQL пачками по 500 штук
        db_batch_size = 500
        for i in range(0, len(user_ids_to_delete), db_batch_size):
            chunk_ids = user_ids_to_delete[i : i + db_batch_size]
            await self.users.delete_users_permanently_batch(chunk_ids)
            await self.db.flush()

        # Фиксируем изменения в PostgreSQL. Транзакция СУБД закрыта и безопасна
        await self.db.commit()

        # 5. ДЕЛЕГИРОВАНИЕ КЛИНИНГ-НАГРУЗКИ В CELERY (Выполняется строго после commit)
        if user_prefixes_to_delete:
            from app.workers.users.tasks import delete_user_s3_resources_task

            delete_user_s3_resources_task.delay(user_prefixes_to_delete)

            logger.info(
                f"CELERY_CLEANUP_DISPATCHED: {len(user_prefixes_to_delete)} префиксов папок "
                f"переданы в Celery для пользователей: {user_ids_to_delete}"
            )

        return f"Успешно удалено аккаунтов из СУБД: {len(user_ids_to_delete)}. Фоновая зачистка S3 запущена."

    async def _delete_old_s3_object_safe(self, url: str) -> None:
        """Делегируем парсинг и удаление профильному сервису (остается без изменений)."""
        try:
            await self.s3.delete_file_by_url(url)
            logger.debug(f"Старый объект S3 удален: {url}")
        except Exception as e:
            logger.error(f"Не удалось удалить старый аватар: {e}")
