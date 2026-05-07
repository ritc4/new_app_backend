import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingApplication
from app.models.user import User
from app.models.user_profiles import SupplierProfile, TripGuideProfile
from app.repositories.admin_log_repository import AdminLogRepository
from app.repositories.onboarding_repository import OnboardingRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserRole
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
    ):
        self.db = db
        self.auth = auth_service
        self.repo = user_repo
        self.onboarding = onboarding_repo
        self.log_repo = log_repo

    def _validate_hierarchy(self, actor: User, target: User, new_role: UserRole | None = None):
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

    async def set_user_role(self, admin: User, user_uuid: UUID, role: UserRole) -> dict:
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
            return {"message": f"Пользователю {updated_user.phone} назначена роль {role}", "user": updated_user}
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, "Ошибка при сохранении роли") from e

    async def admin_change_phone(self, admin: User, user_uuid: UUID, new_phone: str) -> dict:
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
            return {"message": f"Номер пользователя {updated_user.uuid} изменен на {new_phone}", "user": updated_user}
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, "Ошибка смены номера телефона") from e

    # --- Вспомогательные методы ---

    def _ensure_admin_access(self, admin: User):
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

    async def toggle_user_ban(self, admin: User, user_uuid: UUID) -> dict:
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

            # --- АУДИТ ---
            await self.log_repo.create_admin_log(admin_id=admin.id, target_id=user.id, action=action_type)
            await self.db.commit()

            # 5. СБРОС СЕССИЙ: Если забанили — выкидываем из приложения мгновенно
            if new_ban_status:
                await self.auth.logout_all(user.id)
                logger.warning(f"БЛОКИРОВКА: Админ {admin.id} забанил пользователя {user.id}")
            else:
                logger.info(f"РАЗБЛОКИРОВКА: Админ {admin.id} разблокировал пользователя {user.id}")
            status_ru = "заблокирован" if new_ban_status else "разблокирован"

            return {
                "message": f"Пользователь {updated_user.phone} успешно {status_ru}",
                "is_banned": new_ban_status,  # Можно оставить для удобства фронта
                "user": updated_user,
            }

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при смене статуса бана User {user.id}: {e}")
            raise HTTPException(500, "Ошибка при изменении статуса блокировки") from e

    async def approve_partner_application(self, admin: User, application_id: int) -> dict:
        """Одобрение партнера: перенос данных в профиль и смена роли."""
        self._ensure_admin_access(admin)

        # 1. Получаем заявку
        app = await self.onboarding.get_by_id(application_id)

        if not app or app.status != "on_moderation":
            raise HTTPException(400, "Заявка не найдена или не готова к проверке")

        try:
            survey = app.survey_payload or {}  # Защита от None

            if app.target_role == UserRole.SUPPLIER:
                # ВАЖНО: Убедитесь, что имена полей совпадает с тем, что мы писали в модели SupplierProfile
                new_profile = SupplierProfile(
                    user_id=app.user_id,
                    car_model=survey.get("car_model"),
                    car_number=survey.get("car_number"),
                    license_number=survey.get("license_number"),  # Добавил, если оно есть в анкете
                    experience_years=int(survey.get("experience_years", 0)),
                    photo_car_front=survey.get("photo_car_front"),
                    photo_sts_front=survey.get("photo_sts_front"),
                )
                self.db.add(new_profile)

            elif app.target_role == UserRole.TRIP_GUIDE:
                # Создаем запись в таблице гидов
                new_profile = TripGuideProfile(
                    user_id=app.user_id,
                    bio=survey.get("bio"),
                    languages=survey.get("languages", []),
                    specialization=survey.get("specialization"),
                )
                self.db.add(new_profile)

            # 2. Меняем роль в основной таблице пользователей
            await self.repo.update_user(app.user_id, role=app.target_role)

            # 3. Закрываем заявку
            await self.onboarding.update_by_user_id(app.user_id, status="approved")

            # 4. Аудит
            await self.log_repo.create_admin_log(
                admin_id=admin.id,
                target_id=app.user_id,
                action="approve_onboarding",
                details={"role": app.target_role, "app_id": application_id},
            )

            # Теперь фиксируем всё одной транзакцией
            await self.db.commit()

            logger.info(f"Админ {admin.id} одобрил партнера {app.user_id} ({app.target_role})")
            return {"status": "success", "message": "Партнер успешно активирован и профиль создан"}

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Критическая ошибка активации {application_id}: {e}")
            raise HTTPException(500, "Ошибка при сохранении профиля") from e

    async def reject_partner_application(self, admin: User, application_id: int, reason: str) -> dict:
        """Отклонение заявки с указанием причины (Standard Яндекс)."""
        self._ensure_admin_access(admin)

        app = await self.onboarding.get_by_id(application_id)
        if not app or app.status != "on_moderation":
            raise HTTPException(400, "Заявка не найдена или не находится на проверке")

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

            logger.info(f"Админ {admin.id} отклонил заявку {application_id}. Причина: {reason}")
            return {"status": "success", "message": "Заявка отклонена, пользователю отправлено уведомление"}

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при отклонении заявки {application_id}: {e}")
            raise HTTPException(500, "Ошибка сохранения данных") from e

    async def get_pending_applications(
        self, admin: User, limit: int = 20, offset: int = 0
    ) -> list[OnboardingApplication]:
        """Получить очередь на модерацию."""
        self._ensure_admin_access(admin)
        return await self.onboarding.get_moderation_list(limit, offset)
