import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.onboarding import OnboardingStart, SupplierSurvey, TripguideSurvey
from app.schemas.user import UserRole
from app.services.s3_service import S3Service

logger = logging.getLogger("app.services.onboarding")


class OnboardingService:
    def __init__(
        self,
        db: AsyncSession,
        s3: S3Service,
        user_repo: UserRepository,
        onboarding_repo: OnboardingRepository,
    ):
        self.db = db
        self.s3 = s3
        self.users = user_repo
        self.onboarding = onboarding_repo

    async def create_application(self, user_id: int, data: OnboardingStart) -> dict[str, str]:
        """Шаг 1: Создаем заявку через репозиторий и генерируем ссылку."""
        link = f"https://{data.bank}.ru/bind?state=user_{user_id}"

        # Используем репозиторий вместо self.db.add
        await self.onboarding.create(user_id=user_id, target_role=data.target_role, bank_type=data.bank)

        await self.db.commit()
        logger.info("ЗАЯВКА_НА_ОНБОРДИНГ_СОЗДАНА: Пользователь ID %s", user_id)
        return {"link": link}

    async def process_bank_webhook(self, bank_payload: dict[str, Any]) -> dict[str, str]:
        """Шаг 2: Верификация данных банка и обновление профиля."""
        user_id = bank_payload["user_id"]
        bank_phone = bank_payload["phone"]
        inn = bank_payload["inn"]
        full_name = bank_payload["full_name"]

        user = await self.users.get_by_id(user_id)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

        # Проверка телефона
        if user.phone != bank_phone:
            logger.warning(
                "НЕСОВПАДЕНИЕ_ТЕЛЕФОНА: Пользователь %s (В приложении: %s, От банка: %s)",
                user_id,
                user.phone,
                bank_phone,
            )

            # Обновляем через репозиторий
            await self.onboarding.update_by_user_id(
                user_id, status="rejected", admin_comment="Номер телефона в банке не совпадает с номером в приложении"
            )
            await self.db.commit()
            logger.info("ЮРИДИЧЕСКИЙ_СТАТУС_ОТКЛОНЕН: Пользователь %s отклонен (телефоны не совпали).", user_id)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Телефоны не совпадают")

        # Обновляем ФИО в таблице пользователей
        parts = full_name.split()
        await self.users.update_user(
            user_id,
            last_name=parts[0] if len(parts) > 0 else None,
            first_name=parts[1] if len(parts) > 1 else None,
            middle_name=parts[2] if len(parts) > 2 else None,
        )

        # Переводим заявку на следующий этап через репозиторий
        await self.onboarding.update_by_user_id(user_id, status="filling_survey", inn=inn)

        await self.db.commit()
        logger.info("Заявка обновлена для User ID %s", user_id)
        return {"status": "ok"}

    async def submit_survey(self, user_id: int, survey_data: dict[str, Any]) -> dict[str, str]:
        """Шаг 3: Валидация анкеты и перевод на модерацию."""
        # Используем твой метод get_pending_by_user из репозитория
        app = await self.onboarding.get_pending_by_user(user_id)

        if not app or app.status != "filling_survey":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Необходимо сначала пройти юридическую проверку")

        # Валидация данных
        try:
            if app.target_role == UserRole.SUPPLIER:
                SupplierSurvey(**survey_data)
            elif app.target_role == UserRole.TRIP_GUIDE:
                TripguideSurvey(**survey_data)
        except Exception as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Ошибка в данных анкеты: {str(e)}") from e

        # Сохраняем анкету через репозиторий
        await self.onboarding.update_by_user_id(user_id, survey_payload=survey_data, status="on_moderation")

        await self.db.commit()
        logger.info("АНКЕТА_ОТПРАВЛЕНА: Пользователь ID %s переведен на модерацию.", user_id)
        return {"status": "success", "message": "Анкета успешно отправлена"}

    async def get_onboarding_upload_url(self, user_id: int, file_type: str, content_type: str) -> dict[str, Any]:
        """
        Генерирует ссылку для загрузки фото документов в S3 с проверкой типа.
        file_type: 'car_front', 'sts', 'license' и т.д.
        content_type: 'image/jpeg', 'image/png' и т.g.
        """
        # 1. Ограничение по типам файлов (как в аватаре)
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        if content_type not in allowed_types:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Недопустимый формат файла. Разрешены: {', '.join(allowed_types.keys())}"
            )

        file_ext = allowed_types[content_type]
        file_uuid = uuid.uuid4().hex
        object_name = f"onboarding/user_{user_id}/{file_type}_{file_uuid}.{file_ext}"

        try:
            # 2. Получаем параметры из S3Service (там уже стоит лимит 5МБ в Conditions)
            s3_res = await self.s3.get_upload_params(object_name, content_type)

            return {
                "upload_data": s3_res["upload_data"],  # Используем твой ключ
                "file_url": s3_res["public_url"],
            }
        except Exception as e:
            logger.error(f"Ошибка S3 при подготовке загрузки документа {file_type}: {e}")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "Не удалось сгенерировать ссылку для загрузки"
            ) from e
