import logging
import re
from collections.abc import Sequence

import pycountry
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import StoragePaths
from app.models.spatial import Country
from app.models.user import User
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.base import UserRole
from app.schemas.onboarding import (
    ROLE_ALLOWED_PHOTOS,
    ROLE_SURVEY_SCHEMAS,
    BankType,
    BankWebhookPayload,
    BankWebhookPayloadResponse,
    CancelCurrentApplicationResponse,
    GlobalLanguageResponse,
    OnboardingCountryPickerResponse,
    OnboardingDraftResponse,
    OnboardingLinkResponse,
    OnboardingStart,
    OnboardingStatus,
    OnboardingUploadResponse,
    SubmitSurveyResponse,
)
from app.services.s3_service import S3Service

logger = logging.getLogger("app.services.onboarding")

ALL_WORLD_LANGUAGES_CACHE: list[GlobalLanguageResponse] = []
for lang in pycountry.languages:
    if hasattr(lang, "alpha_2"):
        ALL_WORLD_LANGUAGES_CACHE.append(
            GlobalLanguageResponse(code=lang.alpha_2.upper().strip(), name=lang.name, is_popular=False)
        )
ALL_WORLD_LANGUAGES_CACHE.sort(key=lambda x: x.name)


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
        """
        Шаг 0: Проверка и создание заявки.
        [ENTERPRISE STANDARD]: Сохраняет черновики пользователей при случайном закрытии приложения
        и выполняет очистку постоянного мусора в S3 строго при перезапуске после REJECTED/CANCELED.
        """
        # 1. Запрашиваем из репозитория абсолютно любую существующую заявку пользователя
        # (Это убирает лишнее дублирование запросов к СУБД, так как метод get_any_by_user_id мы уже добавили)
        existing = await self.onboarding.get_any_by_user_id(user_id)

        if existing:
            active_statuses = [
                OnboardingStatus.PENDING_LEGAL,
                OnboardingStatus.FILLING_SURVEY,
                OnboardingStatus.ON_MODERATION,
            ]

            # СЦЕНАРИЙ А: У пользователя есть активная заявка или живой черновик
            if str(existing.status) in active_statuses:
                # Защита от чехарды ролей (водитель не должен резко стать гидом в рамках одного черновика)
                if existing.target_role != data.target_role:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"У вас уже есть активная заявка на роль {existing.target_role}. "
                        f"Отмените её, чтобы выбрать другую роль.",
                    )

                # ИДЕАЛ ДЛЯ UX: Если статус FILLING_SURVEY, мы просто возвращаем ссылку.
                # Никакие блоки очистки или Upsert-обнуления ниже НЕ вызываются!
                # Все старые текстовые данные в СУБД и файлы в tmp/ S3 остаются полностью целыми.
                link = f"https://{existing.bank_type}.ru/bind?state=user_{user_id}"
                return OnboardingLinkResponse(status="ok", message="Продолжение заполнения черновика", link=link)

            # СЦЕНАРИЙ Б: У пользователя архивный статус (REJECTED или CANCELED)
            # Пользователь осознанно нажал кнопку "Начать регистрацию заново".
            # Только здесь перед Upsert мы выметаем из постоянного бакета S3 старый мусор, чтобы не платить за него.
            if existing.survey_payload and isinstance(existing.survey_payload, dict):
                try:
                    urls_to_delete = []
                    s3_domain = "storage.yandexcloud.net"

                    for value in existing.survey_payload.values():
                        if isinstance(value, str) and s3_domain in value:
                            urls_to_delete.append(value)

                    if urls_to_delete:
                        # Используем ваш пакетный метод из S3Service (он сам порежет на чанки по 1000 строк)
                        deleted_count = await self.s3.delete_files_batch(urls_to_delete)
                        logger.info(
                            "S3_CLEANUP: Стерто %s постоянных файлов старой "
                            "архивной анкеты перед рестартом для юзера %s",
                            deleted_count,
                            user_id,
                        )
                except Exception as s3_err:
                    # Бизнес-логика важнее: если S3 недоступен, логируем ошибку, но не срываем регистрацию человеку
                    logger.error("S3_CLEANUP_ERROR перед Upsert для юзера %s: %s", user_id, s3_err, exc_info=True)

        # 2. Если активной заявки нет (или старая архивная была успешно зачищена) — делаем Upsert в БД
        link = f"https://{data.bank}.ru/bind?state=user_{user_id}"

        # Этот вызов репозитория выполнит on_conflict_do_update, занулит старый JSON в СУБД и вернет статус PENDING
        await self.onboarding.create(
            user_id=user_id,
            target_role=data.target_role,
            bank_type=data.bank,
            status=OnboardingStatus.PENDING_LEGAL,
        )
        await self.db.commit()

        logger.info("ОНБОРДИНГ_СТАРТ: Пользователь %s начал новую регистрацию как %s", user_id, data.target_role)
        return OnboardingLinkResponse(status="ok", message="Заявка успешно создана", link=link)

    async def process_bank_webhook(self, bank_payload: BankWebhookPayload) -> BankWebhookPayloadResponse:
        # """Шаг 1: Проверяем активную заявку и идемпотентность."""
        user_id = bank_payload.user_id
        app = await self.onboarding.get_pending_by_user(user_id)

        if not app:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Активная заявка не найдена")

        if app.status in [OnboardingStatus.FILLING_SURVEY, OnboardingStatus.ON_MODERATION, OnboardingStatus.REJECTED]:
            logger.info("ВЕБХУК_ПОВТОР: Заявка %s уже в статусе %s", app.id, app.status)
            return BankWebhookPayloadResponse(status="ok", message="Данные уже были обработаны ранее")

        # """Шаг 2: Верификация данных банка."""
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

        # """Шаг 3: Атомарное обновление профиля и заявки."""
        try:
            # Разбиваем имя
            parts = [p for p in bank_payload.full_name.strip().split() if p]

            # Обновляем обе таблицы в рамках одной транзакции
            # 1. Данные пользователя
            updated_user = await self.users.update_user(
                user_id,
                last_name=parts[0] if len(parts) > 0 else user.last_name,
                first_name=parts[1] if len(parts) > 1 else user.first_name,
                middle_name=parts[2] if len(parts) > 2 else None,
            )
            if not updated_user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден при обновлении")

            # 2. Статус заявки и ИНН
            await self.onboarding.update_by_user_id(
                user_id,
                status=OnboardingStatus.FILLING_SURVEY,
                inn=bank_payload.inn,
            )

            # Финальный коммит — если что-то упадет выше, ни одна таблица не изменится
            await self.db.commit()
            logger.info("Заявка и профиль успешно обновлены для User ID %s", user_id)
        except HTTPException:
            # ИСПРАВЛЕНО: Чистый проброс без потери контекста
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("ОШИБКА_ОБНОВЛЕНИЯ_ВЕБХУКА: User ID %s, Error: %s", user_id, e, exc_info=True)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка при сохранении данных банка") from e

        return BankWebhookPayloadResponse(status="ok", message="Заявка успешно обновлена")

    async def submit_survey(self, user_id: int, survey_data: dict[str, object]) -> SubmitSurveyResponse:
        """
        Шаг 3: Динамическая валидация анкеты (включая Regex из БД),
        пакетный перенос файлов из tmp/ в permanent/ в Yandex Cloud S3 и перевод на модерацию.
        """
        # 1. Получаем активную заявку пользователя
        app = await self.onboarding.get_pending_by_user(user_id)
        if not app or app.status != OnboardingStatus.FILLING_SURVEY:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Необходимо сначала пройти юридическую проверку")

        # 2. Достаем нужный класс схемы по роли
        schema_class = ROLE_SURVEY_SCHEMAS.get(app.target_role)
        if not schema_class:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестная роль: {app.target_role}")

        try:
            # 3. Базовая валидация типов Pydantic (стаж, год авто, наличие обязательных фото бока/салона)
            instance = schema_class(**survey_data)
            validated_data = instance.model_dump(mode="json")
        except Exception as e:
            await self.db.rollback()
            logger.error("ОШИБКА_ВАЛИДАЦИИ_АНКЕТЫ: User ID %s, Error: %s", user_id, e)
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Ошибка в данных анкеты: {str(e)}") from e

        # Весь блок комплаенса, переноса файлов S3 и сохранения оборачиваем в try-except для гарантированного rollback
        try:
            # --- Динамический Enterprise-комплаенс для водителей трансферов ---
            # ИСПРАВЛЕНО: приведение к str для безопасного сравнения с Enum/строкой из БД
            if str(app.target_role) == "supplier":
                # Вытаскиваем страну выдачи прав из провалидированной анкеты (например, "RU", "AE")
                license_country_code = validated_data.get("license_country")
                if not license_country_code:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY, "Поле license_country обязательно для заполнения"
                    )

                # Ищем страну в БД по строковому ISO-коду
                country_stmt = select(Country).where(Country.iso_code == str(license_country_code).upper().strip())
                country_res = await self.db.execute(country_stmt)
                country = country_res.scalar_one_or_none()

                if not country:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"Страна выдачи водительского удостоверения '{license_country_code}' "
                        f"пока не поддерживается платформой.",
                    )

                if not country.is_allowed_for_ru_onboarding:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Согласно законодательству РФ коммерческая деятельность "
                        f"по водительским удостоверениям страны {country.name} запрещена. Требуется ВУ образца РФ.",
                    )

                # Очищаем номер прав от пробелов для точной проверки по регулярке
                clean_license_number = str(validated_data.get("license_number")).upper().replace(" ", "")

                # Применяем регулярное выражение напрямую из базы данных
                if country.license_regex and not re.match(country.license_regex, clean_license_number):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Номер водительского удостоверения не соответствует "
                        f"нормативам государственному стандарту страны {country.name}.",
                    )

                # Перезаписываем очищенный стандартизированный номер обратно в payload для сохранения
                validated_data["license_number"] = clean_license_number

            # --- СТРАТЕГИЯ ЭКОНОМИИ S3: АТОМАРНЫЙ ПЕРЕНОС ФАЙЛОВ ИЗ TMP В PERMANENT ---
            final_payload = {}
            s3_domain = "storage.yandexcloud.net"

            for field_key, file_url_or_value in validated_data.items():
                # Если значение является строкой, содержит домен S3 Яндекса и временный префикс tmp/
                if (
                    isinstance(file_url_or_value, str)
                    and s3_domain in file_url_or_value
                    and "onboarding/tmp/" in file_url_or_value
                ):
                    # 1. Вырезаем чистый временный S3-ключ из ссылки
                    tmp_s3_key = file_url_or_value.split(".net/")[-1]
                    # 2. Формируем новый постоянный ключ (меняем tmp/ на permanent/)
                    permanent_s3_key = tmp_s3_key.replace("onboarding/tmp/", "onboarding/permanent/")

                    # 3. Даем команду Yandex Cloud скопировать файл на постоянное место и удалить временный
                    await self.s3.copy_object(source_key=tmp_s3_key, destination_key=permanent_s3_key)
                    await self.s3.delete_object(tmp_s3_key)

                    # 4. Заменяем в итоговом JSON временную ссылку на постоянную
                    final_payload[field_key] = f"https://{self.s3.bucket}.{s3_domain}/{permanent_s3_key}"
                else:
                    # Все текстовые поля (марка машины, стаж, био) переносим без изменений
                    final_payload[field_key] = file_url_or_value

            # 4. Сохраняем проверенный постоянный payload через репозиторий
            await self.onboarding.update_by_user_id(
                user_id,
                survey_payload=final_payload,  # Записываем обновленный JSON с постоянными путями!
                status=OnboardingStatus.ON_MODERATION,
            )
            await self.db.commit()

            logger.info(
                "АНКЕТА_ОТПРАВЛЕНА: Пользователь ID %s успешно прошел комплаенс и переведен на модерацию.", user_id
            )
            return SubmitSurveyResponse(status="success", message="Анкета успешно отправлена")

        except HTTPException:
            # Откатываем транзакцию при любой ошибке комплаенса и пробрасываем статус (400, 422)
            await self.db.rollback()
            raise
        except Exception as e:
            # Откатываем транзакцию при системных сбоях СУБД (500 ошибка)
            await self.db.rollback()
            logger.error("КРИТИЧЕСКАЯ_ОШИБКА_СОХРАНЕНИЯ_АНКЕТЫ: User ID %s, Error: %s", user_id, e, exc_info=True)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Ошибка при сохранении анкеты") from e

    async def get_onboarding_upload_url(
        self,
        user_id: int,
        user_uuid: str,
        file_type: str,
        content_type: str,
    ) -> OnboardingUploadResponse:
        app = await self.onboarding.get_pending_by_user(user_id)
        if not app or app.status != OnboardingStatus.FILLING_SURVEY:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Загрузка недоступна")

        if file_type not in ROLE_ALLOWED_PHOTOS.get(UserRole(app.target_role), set()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Тип файла '{file_type}' не предусмотрен")

        # Ваша старая проверка типов
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        if content_type not in allowed_types:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Недопустимый формат файла")

        # Используем StoragePaths только для генерации финальной строки
        object_name = StoragePaths.onboarding_doc(user_id, user_uuid, file_type, content_type)

        try:
            s3_res = await self.s3.get_upload_params(object_name, content_type)
            return OnboardingUploadResponse(
                upload_data=s3_res["upload_data"],
                file_url=s3_res["public_url"],
            )
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка S3 при подготовке документа {file_type} для User {user_id}: {e}")
            raise HTTPException(500, "Не удалось сгенерировать ссылку для загрузки") from e

    async def purge_expired_onboarding_applications(self) -> str:
        """
        Ночная очистка просроченных заявок онбординга батчами по 200 штук.
        Использует удаление папок по префиксам. Гарантирует 100% очистку бакета,
        даже если пользователь загрузил документы, но бросил заполнение анкеты на середине.
        """
        logger.info("ONBOARDING_CLEANUP_STARTED: Запуск удаления просроченных анкет...")
        total_db_deleted = 0
        total_s3_deleted = 0

        while True:
            # 1. Загружаем порцию из 200 записей
            # (метод репозитория должен подгружать связанную модель user через joinedload)
            batch = await self.onboarding.get_expired_applications_with_payloads(limit=200)
            if not batch:
                break  # Данные закончились — выходим из цикла

            app_ids_to_delete: list[int] = []
            prefixes_to_delete: list[str] = []

            for app in batch:
                app_ids_to_delete.append(app.id)

                # Вычисляем стабильный путь 'папки' на основе ID и UUID пользователя,
                # даже если JSON survey_payload абсолютно пустой!
                if app.user:  # Проверяем наличие связи с пользователем
                    u_id = app.user_id
                    u_uuid = str(app.user.uuid)
                    prefixes_to_delete.append(f"onboarding/tmp/user_{u_id}_{u_uuid}/")

            # 2. Сначала очищаем строки в PostgreSQL и жестко фиксируем этот батч
            if app_ids_to_delete:
                await self.onboarding.batch_delete_applications(app_ids_to_delete)
                await self.db.commit()
                total_db_deleted += len(app_ids_to_delete)

            # 3. ФИЗИЧЕСКИЙ КЛИНИНГ S3 ПО ПРЕФИКСАМ (Строго после коммита в PostgreSQL)
            # Переиспользует ваш delete_files_batch внутри адаптированного метода
            for prefix in prefixes_to_delete:
                try:
                    # Метод находит файлы в S3 по префиксу, превращает их в URL и стирает вашей пакетной функцией
                    deleted_count = await self.s3.delete_directory_by_prefix(prefix)
                    total_s3_deleted += deleted_count
                except Exception as s3_err:
                    # Сбой удаления одной папки не должен мешать очистке других
                    logger.error(f"S3_PREFIX_DELETE_ERROR для префикса {prefix}: {s3_err}", exc_info=True)

        return f"Удалено анкет в БД: {total_db_deleted}, вычищено физических файлов в S3: {total_s3_deleted}"

    async def cancel_current_application(self, user_id: int) -> CancelCurrentApplicationResponse:
        """Отмена текущей заявки пользователем с защитой транзакции."""
        app = await self.onboarding.get_pending_by_user(user_id)
        if not app:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Активная заявка не найдена")

        # Если заявка на модерации, отменять уже нельзя
        if app.status == OnboardingStatus.ON_MODERATION:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заявка на проверке у администратора. Отмена невозможна.")

        try:
            # ИСПРАВЛЕНО: Код обернут в атомарный блок try-except без лишних условных операторов
            await self.onboarding.cancel_application(user_id)
            await self.db.commit()

            logger.info(f"АНКЕТА_ОТМЕНЕНА: Пользователь ID {user_id} самостоятельно отозвал заявку.")
            return CancelCurrentApplicationResponse(status="success", message="Заявка отменена")

        except Exception as e:
            # ИСПРАВЛЕНО: Гарантированно освобождаем пул соединений СУБД при сбое
            await self.db.rollback()
            logger.error(f"Ошибка при отмене заявки для User ID {user_id}: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не удалось отменить заявку") from e

    async def get_all_world_languages(self, client_user: User) -> Sequence[GlobalLanguageResponse]:
        """
        [МЕЖДУНАРОДНЫЙ СТАНДАРТ]:
        Генерирует список всех языков мира с приоритетом популярных.
        Названия языков отдаются в оригинальном ISO-формате ("Russian", "English").
        Домашний язык пользователя автоматически поднимается на позицию №1.
        """
        try:
            # 1. Запрашиваем через репозиторий ISO-код страны из профиля текущего пользователя
            client_country_iso = None
            if client_user.country_id:
                client_country_iso = await self.onboarding.get_country_iso_by_id(client_user.country_id)

            # Мапим ISO-код страны в ISO-код приоритетного языка (RU -> RU, KZ -> KK, BY -> BE)
            user_lang_code = "RU"  # Базовый дефолт
            if client_country_iso:
                country_upper = client_country_iso.upper().strip()
                if country_upper == "KZ":
                    user_lang_code = "KK"
                elif country_upper == "BY":
                    user_lang_code = "BE"
                elif country_upper == "UZ":
                    user_lang_code = "UZ"
                else:
                    user_lang_code = country_upper

            # 2. Базовый пул популярных языков платформы (бизнес-зона)
            popular_languages_codes = {"RU", "EN", "ZH", "TR", "AR", "DE", "FR", "ES"}

            # Динамически добавляем родной язык пользователя в пул популярных
            popular_languages_codes.add(user_lang_code.upper().strip())

            popular_languages: list[GlobalLanguageResponse] = []
            other_languages: list[GlobalLanguageResponse] = []

            # 3. Перебираем официальную мировую базу ISO в памяти бэкенда
            for lang in ALL_WORLD_LANGUAGES_CACHE:
                is_popular = lang.code in popular_languages_codes
                item = GlobalLanguageResponse(code=lang.code, name=lang.name, is_popular=is_popular)
                if is_popular:
                    popular_languages.append(item)
                else:
                    other_languages.append(item)

            # 4. Сортируем обе корзины по алфавиту (поскольку имена на английском, сортировка будет идеальной)
            popular_ordered = sorted(popular_languages, key=lambda x: x.name)
            other_ordered = sorted(other_languages, key=lambda x: x.name)

            # 5. ДИНАМИЧЕСКИЙ МУВ: Находим родной язык пользователя и принудительно ставим на позицию №1
            target_lang = user_lang_code.upper().strip()
            client_lang_item = next((x for x in popular_ordered if x.code == target_lang), None)

            if client_lang_item:
                popular_ordered.remove(client_lang_item)
                popular_ordered.insert(0, client_lang_item)

            # 6. Склеиваем массивы и возвращаем чистую последовательность
            return popular_ordered + other_ordered

        except Exception as e:
            # ИСПРАВЛЕНО: Оставлен один атомарный блок перехвата всех системных ошибок СУБД/памяти
            await self.db.rollback()
            logger.error(
                f"LANGUAGES_CRITICAL_ERROR: Критический сбой справочника для User {client_user.id}: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Внутренняя ошибка сервера при формировании лингвистического справочника",
            ) from e

    async def get_allowed_countries_for_picker(self, client_user: User) -> Sequence[OnboardingCountryPickerResponse]:
        """
        [ИДЕАЛ ПО JWT] Слой бизнес-логики: Отдает список активных стран для Flutter-пикера.
        ИСПРАВЛЕНО: Проверка битой связи перенесена внутрь блока IF. Новый юзер больше не блокируется.
        """
        try:
            client_country_iso = None

            # 1. Проверяем, только если у пользователя ЗАДАН country_id (4 пробела)
            if client_user.country_id:
                client_country_iso = await self.onboarding.get_country_iso_by_id(client_user.country_id)

                # СТРОГО ЗДЕСЬ (12 пробелов от начала строки):
                # Ошибка будет только если ID в профиле есть, но в СУБД его не нашли (битая связь)
                if not client_country_iso:
                    logger.error(
                        "COMPLIANCE_ERROR: User %s has invalid country_id %s", client_user.id, client_user.country_id
                    )
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="В профиле пользователя указана неподдерживаемая страна. Обратитесь в поддержку.",
                    )

            # 2. Базовый пул популярных стран по умолчанию (бизнес-зона СНГ)
            popular_countries_codes = {"RU", "KZ", "BY", "UZ"}
            if client_country_iso:
                popular_countries_codes.add(client_country_iso.upper().strip())

            # 3. ЗАПРОС ЧЕРЕЗ РЕПОЗИТОРИЙ: Получаем чистые активные страны из базы данных
            countries_db = await self.onboarding.get_active_countries()

            # ВАЛИДАЦИЯ БИЗНЕС-ДАННЫХ: Защита от «холодного старта» (база пуста)
            if not countries_db:
                logger.warning("DIRECTORY_ALERT: Справочник стран пуст. Админ не добавил ни одной активной страны.")
                return []

            popular_countries: list[OnboardingCountryPickerResponse] = []
            other_countries: list[OnboardingCountryPickerResponse] = []

            # 4. Распределяем по корзинам с проставлением флага популярности
            for c in countries_db:
                code_upper = c.iso_code.upper().strip()
                is_popular = code_upper in popular_countries_codes
                dto_item = OnboardingCountryPickerResponse(
                    iso_code=code_upper, name=c.name.strip(), is_popular=is_popular
                )
                if is_popular:
                    popular_countries.append(dto_item)
                else:
                    other_countries.append(dto_item)

            # 5. Алгоритмическая сортировка обеих групп по алфавиту
            popular_ordered = sorted(popular_countries, key=lambda x: x.name)
            other_ordered = sorted(other_countries, key=lambda x: x.name)

            # 6. ДИНАМИЧЕСКИЙ МУВ: Ставим домашнюю страну на самую первую строчку (индекс 0)
            if client_country_iso:
                target_iso = client_country_iso.upper().strip()
                client_country_item = next((x for x in popular_ordered if x.iso_code == target_iso), None)
                if client_country_item:
                    popular_ordered.remove(client_country_item)
                    popular_ordered.insert(0, client_country_item)

            # 7. Возвращаем склеенную Read-Only последовательность
            return popular_ordered + other_ordered

        except HTTPException:
            # Для чисто читающего метода убрали лишний пустой rollback()
            raise
        except Exception as e:
            logger.error(
                f"DIRECTORY_CRITICAL_ERROR: Сбой при выгрузке стран для User {client_user.id}: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Внутренняя ошибка сервера при получении справочника гео-зон",
            ) from e

    async def get_current_draft(self, user_id: int) -> OnboardingDraftResponse:
        """Отдает текущий черновик анкеты для мобильного приложения."""
        app = await self.onboarding.get_any_by_user_id(user_id)

        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="У вас нет active процесса регистрации. Начните онбординг заново.",
            )

        draft_payload = app.survey_payload if app.survey_payload else {}

        # Безопасно парсим bank_type, если он записан строкой в БД
        current_bank = None
        if app.bank_type:
            try:
                current_bank = BankType(str(app.bank_type))
            except ValueError:
                logger.warning("Неизвестный тип банка в БД для заявки %s: %s", app.id, app.bank_type)

        return OnboardingDraftResponse(
            application_id=app.id,
            status=OnboardingStatus(str(app.status)),
            target_role=UserRole(str(app.target_role)),
            target_region_id=app.target_region_id,
            # ПЕРЕДАЕМ БАНК ДЛЯ ФЛОТТЕР-КЛИЕНТА:
            bank_type=current_bank,
            inn=app.inn,
            payload=draft_payload,
        )
