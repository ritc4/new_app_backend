# from app.services.s3_service import S3Service

# # 1. Глобальная переменная (кэш экземпляра)
# _s3_instance = None


# async def get_s3_service() -> S3Service:
#     global _s3_instance
#     # 2. Если экземпляра еще нет — создаем его
#     if _s3_instance is None:
#         _s3_instance = S3Service()

#     # 3. Возвращаем существующий экземпляр
#     return _s3_instance


from app.services.s3_service import S3Service

# 1. Явно указываем тип для MyPy. Без этого будет ошибка "Need type annotation"
_s3_instance: S3Service | None = None


async def get_s3_service() -> S3Service:
    """Dependency Injection для S3Service (Singleton)."""
    global _s3_instance

    if _s3_instance is None:
        _s3_instance = S3Service()

    return _s3_instance
