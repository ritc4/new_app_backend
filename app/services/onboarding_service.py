import logging

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import StoragePaths
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.onboarding import (
    ROLE_ALLOWED_PHOTOS,
    ROLE_SURVEY_SCHEMAS,
    BankWebhookPayload,
    BankWebhookPayloadResponse,
    CancelCurrentApplicationResponse,
    OnboardingLinkResponse,
    OnboardingStart,
    OnboardingStatus,
    OnboardingUploadResponse,
    SubmitSurveyResponse,
)
from app.services.s3_service import S3Service

logger = logging.getLogger("app.services.onboarding")


class OnboardingService:
    def __init__(
        self,
        db: AsyncSession,
        s3: S3Service,
        user_repo: UserRepository,
        onboarding_repo: OnboardingRepository,
    ) -> None:
        self.db = db
        self.s3 = s3
        self.users = user_repo
        self.onboarding = onboarding_repo

    async def create_application(self, user_id: int, data: OnboardingStart) -> OnboardingLinkResponse:
        """Шаг 0: Проверка и создание/Upsert заявки с очисткой старых данных."""

        # 1. Ищем только АКТИВНЫЕ заявки (pending_legal, filling_survey, on_moderation)
        # Если заявка canceled или rejected, этот метод вернет None
        existing = await self.onboarding.get_pending_by_user(user_id)

        if existing:
            # Если роли не совпадают — блокируем (защита от чехарды)
            if existing.target_role != data.target_role:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"У вас уже есть активная заявка на роль {existing.target_role}. "
                    f"Отмените её, чтобы выбрать другую роль.",
                )
            # Если роли совпадают — просто отдаем старую ссылку
            link = f"https://{existing.bank_type}.ru/bind?state=user_{user_id}"
            return OnboardingLinkResponse(status="ok", message="Продолжение регистрации", link=link)

        # 2. Если активной заявки нет (она None или в архивном статусе)
        link = f"https://{data.bank}.ru/bind?state=user_{user_id}"

        # Вызываем метод репозитория (который делает on_conflict_do_update)
        # Это принудительно обнулит survey_payload, inn и admin_comment
        await self.onboarding.create(
            user_id=user_id,
            target_role=data.target_role,
            bank_type=data.bank,
            status=OnboardingStatus.PENDING_LEGAL,
        )

        await self.db.commit()
        logger.info("ОНБОРДИНГ_СТАРТ: Пользователь %s начал регистрацию как %s", user_id, data.target_role)

        return OnboardingLinkResponse(status="ok", message="Заявка успешно создана", link=link)

    async def process_bank_webhook(self, bank_payload: BankWebhookPayload) -> BankWebhookPayloadResponse:
        """Шаг 1: Проверяем активную заявку и идемпотентность."""
        user_id = bank_payload.user_id
        app = await self.onboarding.get_pending_by_user(user_id)

        if not app:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Активная заявка не найдена")

        if app.status in [OnboardingStatus.FILLING_SURVEY, OnboardingStatus.ON_MODERATION, OnboardingStatus.REJECTED]:
            logger.info("ВЕБХУК_ПОВТОР: Заявка %s уже в статусе %s", app.id, app.status)
            return BankWebhookPayloadResponse(status="ok", message="Данные уже были обработаны ранее")

        """Шаг 2: Верификация данных банка."""
        user = await self.users.get_by_id(user_id)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

        # Проверка телефона
        if user.phone != bank_payload.phone:
            logger.warning(
                "НЕСОВПАДЕНИЕ_ТЕЛЕФОНА: User %s (App: %s, Bank: %s)",
                user_id,
                user.phone,
                bank_payload.phone,
            )
            # Отклоняем заявку и сразу фиксируем
            await self.onboarding.update_by_user_id(
                user_id,
                status=OnboardingStatus.REJECTED,
                admin_comment="Номер телефона в банке не совпадает с номером в приложении",
            )
            await self.db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Телефоны не совпадают")

        """Шаг 3: Атомарное обновление профиля и заявки."""
        try:
            # Разбиваем имя
            parts = [p for p in bank_payload.full_name.strip().split() if p]

            # Обновляем обе таблицы в рамках одной транзакции
            # 1. Данные пользователя
            await self.users.update_user(
                user_id,
                last_name=parts[0] if len(parts) > 0 else user.last_name,
                first_name=parts[1] if len(parts) > 1 else user.first_name,
                middle_name=parts[2] if len(parts) > 2 else None,
            )

            # 2. Статус заявки и ИНН
            await self.onboarding.update_by_user_id(
                user_id,
                status=OnboardingStatus.FILLING_SURVEY,
                inn=bank_payload.inn,
            )

            # Финальный коммит — если что-то упадет выше, ни одна таблица не изменится
            await self.db.commit()
            logger.info("Заявка и профиль успешно обновлены для User ID %s", user_id)

        except Exception as e:
            await self.db.rollback()
            logger.error("ОШИБКА_ОБНОВЛЕНИЯ_ВЕБХУКА: User ID %s, Error: %s", user_id, e, exc_info=True)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка при сохранении данных банка") from e

        return BankWebhookPayloadResponse(status="ok", message="Заявка успешно обновлена")

    async def submit_survey(self, user_id: int, survey_data: dict[str, object]) -> SubmitSurveyResponse:
        """Шаг 3: Валидация анкеты и перевод на модерацию."""
        app = await self.onboarding.get_pending_by_user(user_id)

        if not app or app.status != OnboardingStatus.FILLING_SURVEY:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Необходимо сначала пройти юридическую проверку")

        # 1. Достаем нужный класс схемы по роли из БД
        schema_class = ROLE_SURVEY_SCHEMAS.get(app.target_role)
        if not schema_class:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестная роль: {app.target_role}")

        try:
            # 2. Валидируем и дампим в JSON
            instance = schema_class(**survey_data)
            validated_data = instance.model_dump(mode="json")
        except Exception as e:
            logger.error("ОШИБКА_ВАЛИДАЦИИ_АНКЕТЫ: User ID %s, Error: %s", user_id, e)
            # Pydantic выбросит понятную ошибку, если, например, стаж < 3 лет
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Ошибка в данных анкеты: {str(e)}") from e

        # Сохраняем через репозиторий
        await self.onboarding.update_by_user_id(
            user_id,
            survey_payload=validated_data,
            status=OnboardingStatus.ON_MODERATION,
        )

        await self.db.commit()
        logger.info("АНКЕТА_ОТПРАВЛЕНА: Пользователь ID %s переведен на модерацию.", user_id)
        return SubmitSurveyResponse(status="success", message="Анкета успешно отправлена")

    async def get_onboarding_upload_url(
        self,
        user_id: int,
        file_type: str,
        content_type: str,
    ) -> OnboardingUploadResponse:
        app = await self.onboarding.get_pending_by_user(user_id)
        if not app or app.status != OnboardingStatus.FILLING_SURVEY:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Загрузка недоступна")

        if file_type not in ROLE_ALLOWED_PHOTOS.get(app.target_role, set()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Тип файла '{file_type}' не предусмотрен")

        # Ваша старая проверка типов
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        if content_type not in allowed_types:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недопустимый формат файла")

        # Используем StoragePaths только для генерации финальной строки
        object_name = StoragePaths.onboarding_doc(user_id, file_type, content_type)

        try:
            s3_res = await self.s3.get_upload_params(object_name, content_type)
            return OnboardingUploadResponse(
                upload_data=s3_res["upload_data"]["fields"],
                file_url=s3_res["public_url"],
            )
        except Exception as e:
            logger.error(f"Ошибка S3 при подготовке документа {file_type} для User {user_id}: {e}")
            raise HTTPException(500, "Не удалось сгенерировать ссылку для загрузки") from e

    async def cancel_current_application(self, user_id: int) -> CancelCurrentApplicationResponse:
        """Новый метод для отмены заявки пользователем."""
        app = await self.onboarding.get_pending_by_user(user_id)

        if not app:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Активная заявка не найдена")

        # Если заявка на модерации, отменять уже нельзя
        if app.status == OnboardingStatus.ON_MODERATION:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заявка на проверке у администратора. Отмена невозможна.")

        success = await self.onboarding.cancel_application(user_id)
        if success:
            await self.db.commit()
            return CancelCurrentApplicationResponse(status="success", message="Заявка отменена")

        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не удалось отменить заявку")
