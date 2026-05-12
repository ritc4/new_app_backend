import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_profiles import SupplierProfile, TripGuideProfile
from app.repositories.admin_log_repository import AdminLogRepository
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.admin import AdminActionResponse, UserAdminView
from app.schemas.base import UserRole
from app.schemas.onboarding import OnboardingAppShort, SupplierSurvey, TripguideSurvey
from app.services.auth_service import AuthService

logger = logging.getLogger("app.services.admin")


class AdminService:
    def __init__(
        self,
        db: AsyncSession,
        auth_service: AuthService,
        onboarding_repo: OnboardingRepository,
        user_repo: UserRepository,
        log_repo: AdminLogRepository,
    ) -> None:
        self.db = db
        self.auth = auth_service
        self.repo = user_repo
        self.onboarding = onboarding_repo
        self.log_repo = log_repo

    def _validate_hierarchy(self, actor: User, target: User, new_role: UserRole | None = None) -> None:
        # Если это один и тот же человек (редактирую сам себя)
        if actor.id == target.id:
            # Суперюзеру нельзя менять свою роль на что-то ниже,
            # иначе он потеряет доступ и не сможет вернуть его.
            if new_role and actor.is_superuser and new_role != UserRole.ADMIN:
                raise HTTPException(400, "Суперюзер не может понизить самого себя")
            return  # Свои данные (телефон, имя) менять можно всегда

        # Защита СУПЕРЮЗЕРА от других
        # Если цель — суперюзер, то actor.level (макс 50) всегда <= 100.
        # Доступ будет закрыт для всех, кто не является этим же суперюзером.
        if actor.level <= target.level:
            raise HTTPException(403, "У вас нет власти над этим пользователем")

        # Возможность НАЗНАЧАТЬ админов
        if new_role:
            new_level = User.get_role_level(new_role.value)
            # Обычный админ (50) <= Новая роль Админ (50) -> True (Запрещено)
            # Суперюзер (100) <= Новая роль Админ (50) -> False (Разрешено)
            if actor.level <= new_level:
                raise HTTPException(403, "Вы не можете назначать роль равную или выше вашей")

    async def set_user_role(self, admin: User, user_uuid: UUID, role: UserRole) -> AdminActionResponse:
        """Смена роли (Aдмин/Клиент). Сбрасывает сессии только при назначении/снятии админки."""
        self._ensure_admin_access(admin)
        user = await self.repo.get_by_uuid(user_uuid)
        if not user:
            raise HTTPException(404, "Пользователь не найден")

        # Запрещаем делать пользователя водителем или гидом через этот "рубильник"
        # Для этого админ должен использовать метод approve_partner_application
        if role in [UserRole.SUPPLIER, UserRole.TRIP_GUIDE] and user.role == UserRole.CUSTOMER:
            raise HTTPException(
                status_code=400,
                detail="Для получения проф. роли пользователь должен заполнить анкету и пройти онбординг",
            )

        # 1. Проверяем иерархию (кто кого может менять и на что)
        self._validate_hierarchy(admin, user, new_role=role)

        # 2. Определяем, нужно ли сбрасывать сессии
        # Сбрасываем если:
        # - ТЕКУЩАЯ роль была админом (мы его снимаем с должности)
        # - НОВАЯ роль будет админом (мы его назначаем)
        old_role = user.role
        needs_logout = user.role == UserRole.ADMIN or role == UserRole.ADMIN

        try:
            # Обновляем роль.
            # is_superuser=False — это защита, чтобы через смену ролей
            # нельзя было стать супером.
            updated_user = await self.repo.update_user(user.id, role=role.value, is_superuser=False)

            if updated_user is None:
                raise HTTPException(500, "Не удалось обновить данные пользователя в базе")

            # --- АУДИТ ---
            await self.log_repo.create_admin_log(
                admin_id=admin.id,
                target_id=user.id,
                action="role_change",
                details={"old_role": old_role, "new_role": role.value},
            )
            await self.db.commit()

            # 3. Применяем сброс сессий только если это критично для безопасности
            if needs_logout:
                await self.auth.logout_all(user.id)
                logger.info(f"Сессии пользователя {user.id} сброшены (смена админ-прав)")

            logger.info(f"Админ {admin.id} установил роль {role} пользователю {user.id}")
            return AdminActionResponse(
                status="success",
                message=f"Пользователю {updated_user.phone} назначена роль {role}",
                user=UserAdminView.model_validate(updated_user),
            )
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, "Ошибка при сохранении роли") from e

    async def admin_change_phone(self, admin: User, user_uuid: UUID, new_phone: str) -> AdminActionResponse:
        """Принудительная смена номера телефона."""
        self._ensure_admin_access(admin)
        user = await self.repo.get_by_uuid(user_uuid)
        if not user:
            raise HTTPException(404, "Пользователь не найден")

        # Защита: нельзя менять телефон равному или высшему по уровню
        self._validate_hierarchy(admin, user)
        old_phone = user.phone

        existing_user = await self.repo.get_by_phone(new_phone)
        if existing_user:
            raise HTTPException(400, "Номер уже занят активным пользователем")

        try:
            updated_user = await self.repo.change_phone(user.id, new_phone)

            # --- АУДИТ ---
            await self.log_repo.create_admin_log(
                admin_id=admin.id,
                target_id=user.id,
                action="phone_change",
                details={"old_phone": old_phone, "new_phone": new_phone},
            )
            await self.db.commit()
            await self.auth.logout_all(user.id)
            logger.info(f"Админ {admin.id} сменил номер для User {user.id} на {new_phone}")
            return AdminActionResponse(
                status="success",
                message=f"Номер пользователя {updated_user.uuid} изменен на {new_phone}",
                user=UserAdminView.model_validate(updated_user),
            )
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, "Ошибка смены номера телефона") from e

    # --- Вспомогательные методы ---

    def _ensure_admin_access(self, admin: User) -> None:
        """Проверка прав администратора через уровень доступа (Fail Fast)."""
        # Уровень 50 — это минимальный порог для доступа к админ-панели
        if admin.level < 50:
            logger.warning(f"SECURITY: Попытка доступа к админ-функциям: User {admin.id} (lvl {admin.level})")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав администратора")
        if admin.is_banned:
            logger.error("SECURITY_ALERT: Заблокированный админ ID %s пытался выполнить действие!", admin.id)
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Ваш аккаунт администратора заблокирован")

        # 3. Проверяем активность аккаунта (например, если админ в процессе удаления)
        if not admin.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт администратора неактивен")

    async def toggle_user_ban(self, admin: User, user_uuid: UUID) -> AdminActionResponse:
        """Блокировка или разблокировка пользователя."""
        self._ensure_admin_access(admin)

        user = await self.repo.get_by_uuid(user_uuid)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

        # 1. Защита от "самобана"
        if user.id == admin.id:
            raise HTTPException(400, "Нельзя заблокировать самого себя")

        # 2. ИЕРАРХИЯ: Универсальная проверка через уровни.
        # Обычный админ не может забанить другого админа или Супера.
        self._validate_hierarchy(admin, user)

        try:
            # 3. Инвертируем статус бана
            new_ban_status = not user.is_banned

            # 4. Обновляем в БД
            action_type = "ban" if new_ban_status else "unban"

            updated_user = await self.repo.update_user(user.id, is_banned=new_ban_status)

            if updated_user is None:
                raise HTTPException(500, "Не удалось обновить статус блокировки в базе данных")

            # --- АУДИТ ---
            await self.log_repo.create_admin_log(admin_id=admin.id, target_id=user.id, action=action_type)
            await self.db.commit()

            # 5. СБРОС СЕССИЙ: Если забанили — выкидываем из приложения мгновенно
            if new_ban_status:
                await self.auth.logout_all(user.id)
                logger.warning(f"БЛОКИРОВКА: Админ {admin.id} забанил пользователя {user.id}")
            else:
                logger.info(f"РАЗБЛОКИРОВКА: Админ {admin.id} разблокировал пользователя {user.id}")

            # 6. Возвращаем результат
            status_ru = "заблокирован" if new_ban_status else "разблокирован"

            return AdminActionResponse(
                message=f"Пользователь {updated_user.phone} успешно {status_ru}",
                is_banned=new_ban_status,  # Можно оставить для удобства фронта
                user=UserAdminView.model_validate(updated_user),
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при смене статуса бана User {user.id}: {e}")
            raise HTTPException(500, "Ошибка при изменении статуса блокировки") from e

    async def approve_partner_application(self, admin: User, application_id: int) -> AdminActionResponse:
        """Одобрение партнера: перенос данных в профиль и смена роли."""
        self._ensure_admin_access(admin)

        # 1. Получаем заявку
        app = await self.onboarding.get_by_id(application_id)
        if not app or app.status != "on_moderation":
            raise HTTPException(400, "Заявка не найдена или не готова к проверке")

        try:
            survey_data = app.survey_payload or {}

            # --- ЛОГИКА ОДОБРЕНИЯ (Простой и строгий Type Safety) ---
            if app.target_role == UserRole.SUPPLIER:
                # Прямая валидация конкретной схемой — MyPy видит все поля
                survey_sup = SupplierSurvey.model_validate(survey_data)

                self.db.add(
                    SupplierProfile(
                        user_id=app.user_id,
                        car_model=survey_sup.car_model,
                        car_year=survey_sup.car_year,
                        car_number=survey_sup.car_number,
                        car_color=survey_sup.car_color,
                        vin_number=survey_sup.vin_number,
                        license_number=survey_sup.license_number,
                        license_expiry_date=survey_sup.license_expiry_date,
                        license_country=survey_sup.license_country,
                        experience_years=survey_sup.experience_years,
                        photo_selfie=survey_sup.photo_selfie,
                        photo_car_front=survey_sup.photo_car_front,
                        photo_car_back=survey_sup.photo_car_back,
                        photo_sts_front=survey_sup.photo_sts_front,
                        photo_sts_back=survey_sup.photo_sts_back,
                        photo_license=survey_sup.photo_license,
                    ),
                )
                # Обновляем фото пользователя из анкеты
                await self.repo.update_user(app.user_id, photo_url=survey_sup.photo_selfie)

            elif app.target_role == UserRole.TRIP_GUIDE:
                # Валидация схемой гида
                survey_guide = TripguideSurvey.model_validate(survey_data)

                self.db.add(
                    TripGuideProfile(
                        user_id=app.user_id,
                        bio=survey_guide.bio,
                        languages=survey_guide.languages,
                        specialization=survey_guide.specialization,
                    ),
                )

            else:
                raise HTTPException(400, f"Неподдерживаемая роль: {app.target_role}")

            # 2. Обновляем статусы и транзакцию
            await self.repo.update_user(app.user_id, role=app.target_role)
            await self.onboarding.update_by_user_id(app.user_id, status="approved")

            # 3. Аудит
            await self.log_repo.create_admin_log(
                admin_id=admin.id,
                target_id=app.user_id,
                action="approve_onboarding",
                details={"role": app.target_role, "app_id": application_id},
            )

            # Фиксируем всё одной транзакцией
            await self.db.commit()

            # 4. Подготовка ответа
            updated_user = await self.repo.get_by_id(app.user_id)
            if not updated_user:
                raise HTTPException(404, "Пользователь не найден после обновления")

            # Принудительно обновляем, чтобы SQLAlchemy увидела созданный профиль
            await self.db.refresh(updated_user)

            logger.info(f"Админ {admin.id} одобрил партнера {app.user_id} ({app.target_role})")

            return AdminActionResponse(
                status="success",
                message="Партнер успешно активирован и профиль создан",
                user=UserAdminView.model_validate(updated_user),
            )

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Критическая ошибка активации {application_id}: {e}")
            raise HTTPException(500, "Ошибка при сохранении профиля партнера") from e

    async def reject_partner_application(self, admin: User, application_id: int, reason: str) -> AdminActionResponse:
        """Отклонение заявки с указанием причины (Standard Яндекс)."""
        self._ensure_admin_access(admin)

        clean_reason = reason.strip()
        if not clean_reason:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Причина отклонения не может быть пустой")

        app = await self.onboarding.get_by_id(application_id)

        # Проверяем статус: отклонить можно только то, что на модерации
        if not app or app.status != "on_moderation":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Заявка не найдена или не находится на проверке")

        try:
            # 1. Меняем статус и записываем причину
            app.status = "rejected"
            app.admin_comment = reason  # Тот самый текст для пользователя

            # 2. Аудит для суперюзера (чтобы видеть, не банит ли админ всех подряд)
            await self.log_repo.create_admin_log(
                admin_id=admin.id,
                target_id=app.user_id,
                action="reject_onboarding",
                details={"reason": reason, "app_id": application_id},
            )

            await self.db.commit()

            # 3. Уведомление (опционально в будущем)
            # await self.notifications.send_push(app.user_id, f"Заявка отклонена: {reason}")
            user = await self.repo.get_by_id(app.user_id)
            if not user:
                raise HTTPException(404, "Пользователь не найден")

            logger.info(f"Админ {admin.id} отклонил заявку {application_id}. Причина: {reason}")
            return AdminActionResponse(
                status="success",
                message="Заявка отклонена, пользователю отправлено уведомление",
                user=UserAdminView.model_validate(user),
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при отклонении заявки {application_id}: {e}")
            raise HTTPException(500, "Ошибка сохранения данных") from e

    async def get_pending_applications(self, admin: User, limit: int = 20, offset: int = 0) -> list[OnboardingAppShort]:
        """Получить очередь на модерацию."""
        self._ensure_admin_access(admin)
        applications = await self.onboarding.get_moderation_list(limit, offset)
        return [OnboardingAppShort.model_validate(app) for app in applications]
