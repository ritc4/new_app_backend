import uuid


class StoragePaths:
    @staticmethod
    def _get_ext(content_type: str) -> str:
        """Вспомогательный метод для определения расширения."""
        allowed_types = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
        return allowed_types.get(content_type, "bin")

    @staticmethod
    def onboarding_doc(user_id: int, file_type: str, content_type: str) -> str:
        """Путь: onboarding/user_1/photo_selfie_uuid.jpg"""
        ext = StoragePaths._get_ext(content_type)
        file_uuid = uuid.uuid4().hex
        return f"onboarding/user_{user_id}/{file_type}_{file_uuid}.{ext}"

    @staticmethod
    def user_avatar(user_id: int, content_type: str) -> str:
        """Путь: avatars/user_1/uuid.jpg"""
        ext = StoragePaths._get_ext(content_type)
        file_uuid = uuid.uuid4().hex
        return f"avatars/user_{user_id}/{file_uuid}.{ext}"
