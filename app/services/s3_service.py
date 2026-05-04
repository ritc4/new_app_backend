# import logging

# import aioboto3
# from botocore.config import Config  # Добавь импорт

# from app.config.settings import settings

# logger = logging.getLogger("app.services.s3")


# class S3Service:
#     def __init__(self):
#         self.session = aioboto3.Session()
#         self.bucket = settings.s3.bucket_name
#         # Добавляем настройки для совместимости с кастомными S3
#         self.s3_config = Config(
#             s3={"addressing_style": "path"},  # Важно для MinIO/Yandex
#             signature_version="s3v4",
#         )
#         self.config = {
#             "endpoint_url": settings.s3.endpoint_url,
#             "aws_access_key_id": settings.s3.access_key.get_secret_value(),
#             "aws_secret_access_key": settings.s3.secret_key.get_secret_value(),
#             "region_name": settings.s3.region,
#         }

#     async def delete_file(self, object_name: str) -> bool:
#         """Удаляет файл из S3 по его имени (Key)."""
#         async with self.session.client("s3", config=self.s3_config, **self.config) as s3:
#             try:
#                 # В S3 delete_object всегда возвращает успех, даже если ключа нет
#                 await s3.delete_object(Bucket=self.bucket, Key=object_name)
#                 logger.info(f"Запрос на удаление {object_name} отправлен в S3")
#                 return True
#             except Exception as e:
#                 logger.error(f"Ошибка при удалении файла {object_name} из S3: {e}")
#                 return False

#     async def get_presigned_post_data(self, object_name: str, content_type: str, expires_in: int = 3600) -> dict:
#         """
#         Генерирует данные для POST-загрузки с жестким ограничением размера (5МБ).
#         """
#         async with self.session.client("s3", config=self.s3_config, **self.config) as s3:
#             try:
#                 post_data = await s3.generate_presigned_post(
#                     Bucket=self.bucket,
#                     Key=object_name,
#                     Fields={"Content-Type": content_type},
#                     Conditions=[
#                         {"Content-Type": content_type},
#                         ["content-length-range", 1, 5242880],  # 5 МБ
#                     ],
#                     ExpiresIn=expires_in,
#                 )
#                 logger.info(f"Сгенерирована ссылка на загрузку: {object_name}")
#                 return post_data
#             except Exception as e:
#                 logger.error(f"Ошибка генерации Presigned POST: {e}")
#                 raise


import logging

import aioboto3
from botocore.config import Config

from app.config.settings import settings

logger = logging.getLogger("app.services.s3")


class S3Service:
    def __init__(self):
        self.session = aioboto3.Session()
        self.bucket = settings.s3.bucket_name
        self.endpoint_url = settings.s3.endpoint_url.rstrip("/")

        self.s3_config = Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
        )
        self.client_kwargs = {
            "endpoint_url": self.endpoint_url,
            "aws_access_key_id": settings.s3.access_key.get_secret_value(),
            "aws_secret_access_key": settings.s3.secret_key.get_secret_value(),
            "region_name": settings.s3.region,
        }

    async def get_upload_params(self, object_name: str, content_type: str, expires_in: int = 900) -> dict:
        """Генерирует данные для загрузки и финальный URL."""
        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            try:
                post_data = await s3.generate_presigned_post(
                    Bucket=self.bucket,
                    Key=object_name,
                    Fields={"Content-Type": content_type},
                    Conditions=[
                        {"Content-Type": content_type},
                        ["content-length-range", 1, 5242880],
                    ],
                    ExpiresIn=expires_in,
                )
                public_url = f"{self.endpoint_url}/{self.bucket}/{object_name}"
                return {"post_data": post_data, "public_url": public_url}
            except Exception as e:
                logger.error(f"Ошибка генерации параметров загрузки: {e}")
                raise

    async def delete_file_by_url(self, url: str, client=None) -> bool:
        """
        Извлекает ключ из URL и удаляет файл.
        Поддерживает передачу внешнего клиента для batch-операций.
        """
        try:
            bucket_marker = f"{self.bucket}/"
            if bucket_marker not in url:
                return False

            object_key = url.split(bucket_marker)[-1]
            # Пробрасываем клиент дальше
            return await self.delete_file(object_key, client=client)
        except Exception as e:
            logger.error(f"Не удалось распарсить URL для удаления: {url}. Ошибка: {e}")
            return False

    async def delete_file(self, object_name: str, client=None) -> bool:
        """
        Низкоуровневое удаление объекта.
        Если client передан, использует его (Highload mode).
        """
        if client:
            return await self._execute_delete(client, object_name)

        # Если клиента нет, создаем временный (обычный режим)
        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            return await self._execute_delete(s3, object_name)

    async def _execute_delete(self, s3_client, object_name: str) -> bool:
        """Внутренняя логика удаления через конкретный клиент."""
        try:
            await s3_client.delete_object(Bucket=self.bucket, Key=object_name)
            logger.info(f"Объект S3 удален: {object_name}")
            return True
        except Exception as e:
            logger.error(f"Ошибка S3 при удалении {object_name}: {e}")
            return False
