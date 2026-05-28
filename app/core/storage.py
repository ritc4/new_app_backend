import uuid


class StoragePaths:
    @staticmethod
    def _get_ext(content_type: str) -> str:
        """Вспомогательный метод для определения расширения."""
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        return allowed_types.get(content_type, "bin")

    @staticmethod
    def onboarding_doc(user_id: int, user_uuid: str, file_type: str, content_type: str) -> str:
        """
        ИСПРАВЛЕНО: user_uuid передается снаружи (из БД/сессии), а не генерируется случайно!
        Путь всегда стабилен для конкретного юзера: onboarding/user_1_56f02c1b.../photo_selfie.jpg
        """
        ext = StoragePaths._get_ext(content_type)
        return f"onboarding/tmp/user_{user_id}_{user_uuid}/{file_type}.{ext}"  

    @staticmethod
    def user_avatar(user_id: int, content_type: str) -> str:
        """Путь: avatars/user_1/uuid.jpg"""
        ext = StoragePaths._get_ext(content_type)
        file_uuid = uuid.uuid4().hex
        return f"avatars/user_{user_id}/{file_uuid}.{ext}"
    
    @staticmethod
    def excursion_gallery_photo(excursion_id: int, position_index: int, content_type: str) -> str:
        """
        Путь всегда стабилен для конкретной позиции в карусели экскурсии (0-9):
        excursions/excursion_42/gallery_slot_0.jpg
        """
        ext = StoragePaths._get_ext(content_type)
        # Страхуем индекс на уровне генерации пути
        safe_index = min(max(0, position_index), 9)
        return f"excursions/excursion_{excursion_id}/gallery_slot_{safe_index}.{ext}"
