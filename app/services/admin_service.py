# import logging
# from uuid import UUID

# from fastapi import HTTPException, status
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.models.user import User
# from app.repositories.user_repository import UserRepository
# from app.schemas.user import UserRole
# from app.services.auth_service import AuthService

# logger = logging.getLogger("app.services.admin")


# class AdminService:
#     def __init__(self, db: AsyncSession, auth_service: AuthService):
#         self.db = db
#         self.auth = auth_service
#         self.repo = UserRepository(db)

#     def _validate_hierarchy(self, actor: User, target: User, new_role: UserRole | None = None):
#         # Если это один и тот же человек (редактирую сам себя)
#         if actor.id == target.id:
#             # Суперюзеру нельзя менять свою роль на что-то ниже,
#             # иначе он потеряет доступ и не сможет вернуть его.
#             if new_role and actor.is_superuser and new_role != UserRole.ADMIN:
#                 raise HTTPException(400, "Суперюзер не может понизить самого себя")
#             return  # Свои данные (телефон, имя) менять можно всегда

#         # Защита СУПЕРЮЗЕРА от других
#         # Если цель — суперюзер, то actor.level (макс 50) всегда <= 100.
#         # Доступ будет закрыт для всех, кто не является этим же суперюзером.
#         if actor.level <= target.level:
#             raise HTTPException(403, "У вас нет власти над этим пользователем")

#         # Возможность НАЗНАЧАТЬ админов
#         if new_role:
#             new_level = User.get_role_level(new_role.value)
#             # Обычный админ (50) <= Новая роль Админ (50) -> True (Запрещено)
#             # Суперюзер (100) <= Новая роль Админ (50) -> False (Разрешено)
#             if actor.level <= new_level:
#                 raise HTTPException(403, "Вы не можете назначать роль равную или выше вашей")

#     async def set_user_role(self, admin: User, user_uuid: UUID, role: UserRole) -> User:
#         """Смена роли (Aдмин/Клиент/Гид/Водитель). Сбрасывает сессии только при назначении/снятии админки."""
#         self._ensure_admin_access(admin)
#         user = await self.repo.get_by_uuid(user_uuid)
#         if not user:
#             raise HTTPException(404, "Пользователь не найден")

#         # 1. Проверяем иерархию (кто кого может менять и на что)
#         self._validate_hierarchy(admin, user, new_role=role)

#         # 2. Определяем, нужно ли сбрасывать сессии
#         # Сбрасываем если:
#         # - ТЕКУЩАЯ роль была админом (мы его снимаем с должности)
#         # - НОВАЯ роль будет админом (мы его назначаем)
#         needs_logout = user.role == UserRole.ADMIN or role == UserRole.ADMIN

#         try:
#             # Обновляем роль.
#             # is_superuser=False — это защита, чтобы через смену ролей
#             # нельзя было стать супером.
#             user = await self.repo.update_user(user.id, role=role.value, is_superuser=False)
#             await self.db.commit()

#             # 3. Применяем сброс сессий только если это критично для безопасности
#             if needs_logout:
#                 await self.auth.logout_all(user.id)
#                 logger.info(f"Сессии пользователя {user.id} сброшены (смена админ-прав)")

#             logger.info(f"Админ {admin.id} установил роль {role} пользователю {user.id}")
#             return user
#         except Exception as e:
#             await self.db.rollback()
#             raise HTTPException(500, "Ошибка при сохранении роли") from e

#     async def admin_change_phone(self, admin: User, user_uuid: UUID, new_phone: str) -> None:
#         """Принудительная смена номера телефона."""
#         self._ensure_admin_access(admin)
#         user = await self.repo.get_by_uuid(user_uuid)
#         if not user:
#             raise HTTPException(404, "Пользователь не найден")

#         # Защита: нельзя менять телефон равному или высшему по уровню
#         self._validate_hierarchy(admin, user)

#         existing_user = await self.repo.get_by_phone(new_phone)
#         if existing_user:
#             raise HTTPException(400, "Номер уже занят активным пользователем")

#         try:
#             await self.repo.change_phone(user.id, new_phone)
#             await self.db.commit()
#             await self.auth.logout_all(user.id)
#             logger.info(f"Админ {admin.id} сменил номер для User {user.id} на {new_phone}")
#         except Exception as e:
#             await self.db.rollback()
#             raise HTTPException(500, "Ошибка смены номера телефона") from e

#     # --- Вспомогательные методы ---

#     def _ensure_admin_access(self, admin: User):
#         """Проверка прав администратора через уровень доступа (Fail Fast)."""
#         # Уровень 50 — это минимальный порог для доступа к админ-панели
#         if admin.level < 50:
#             logger.warning(f"SECURITY: Попытка доступа к админ-функциям: User {admin.id} (lvl {admin.level})")
#             raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет прав администратора")

#     async def toggle_user_ban(self, admin: User, user_uuid: UUID) -> bool:
#         """Блокировка или разблокировка пользователя."""
#         self._ensure_admin_access(admin)

#         user = await self.repo.get_by_uuid(user_uuid)
#         if not user:
#             raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

#         # 1. Защита от "самобана"
#         if user.id == admin.id:
#             raise HTTPException(400, "Нельзя заблокировать самого себя")

#         # 2. ИЕРАРХИЯ: Универсальная проверка через уровни.
#         # Обычный админ не может забанить другого админа или Супера.
#         self._validate_hierarchy(admin, user)

#         try:
#             # 3. Инвертируем статус бана
#             new_ban_status = not user.is_banned

#             # 4. Обновляем в БД
#             await self.repo.update_user(user.id, is_banned=new_ban_status)
#             await self.db.commit()

#             # 5. СБРОС СЕССИЙ: Если забанили — выкидываем из приложения мгновенно
#             if new_ban_status:
#                 await self.auth.logout_all(user.id)
#                 logger.warning(f"БЛОКИРОВКА: Админ {admin.id} забанил пользователя {user.id}")
#             else:
#                 logger.info(f"РАЗБЛОКИРОВКА: Админ {admin.id} разблокировал пользователя {user.id}")

#             return new_ban_status

#         except Exception as e:
#             await self.db.rollback()
#             logger.error(f"Ошибка при смене статуса бана User {user.id}: {e}")
#             raise HTTPException(500, "Ошибка при изменении статуса блокировки") from e


import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.admin_log_repository import AdminLogRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserRole
from app.services.auth_service import AuthService

logger = logging.getLogger("app.services.admin")


class AdminService:
    def __init__(
        self, db: AsyncSession, auth_service: AuthService, user_repo: UserRepository, log_repo: AdminLogRepository
    ):
        self.db = db
        self.auth = auth_service
        self.repo = user_repo
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
        """Смена роли (Aдмин/Клиент/Гид/Водитель). Сбрасывает сессии только при назначении/снятии админки."""
        self._ensure_admin_access(admin)
        user = await self.repo.get_by_uuid(user_uuid)
        if not user:
            raise HTTPException(404, "Пользователь не найден")

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

            return {
                "message": f"Пользователь {updated_user.phone} успешно {action_type}ed",
                "is_banned": new_ban_status,  # Можно оставить для удобства фронта
                "user": updated_user,
            }

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при смене статуса бана User {user.id}: {e}")
            raise HTTPException(500, "Ошибка при изменении статуса блокировки") from e
