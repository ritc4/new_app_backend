from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aioboto3
from botocore.config import Config

from app.config.settings import settings
from app.schemas.s3 import S3UploadResult

logger = logging.getLogger("app.services.s3")


if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client
    from types_aiobotocore_s3.type_defs import ObjectIdentifierTypeDef


class S3Service:
    def __init__(self) -> None:
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

    async def get_upload_params(self, object_name: str, content_type: str, expires_in: int = 900) -> S3UploadResult:
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
                return {
                    "upload_data": {"url": str(post_data["url"]), "fields": dict(post_data["fields"])},
                    "public_url": public_url,
                }
            except Exception as e:
                logger.error(f"Ошибка генерации параметров загрузки: {e}")
                raise

    # --- МАССОВОЕ УДАЛЕНИЕ ПО ПРЕФИКСУ ---

    async def delete_all_user_files(self, user_id: int, client: S3Client | None = None) -> bool:
        """
        Находит и удаляет ВСЕ объекты в S3, в пути которых есть 'user_{id}/'.
        Это избавляет от необходимости дописывать новые поля при расширении профилей.
        """
        marker = f"user_{user_id}/"

        if client:
            return await self._purge_by_marker(client, marker)

        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            return await self._purge_by_marker(s3, marker)

    async def _purge_by_marker(self, s3_client: S3Client, marker: str) -> bool:
        """Логика поиска и пакетного удаления объектов."""
        try:
            # Используем пагинатор, так как файлов может быть больше 1000
            paginator = s3_client.get_paginator("list_objects_v2")
            found_any = False

            async for page in paginator.paginate(Bucket=self.bucket):
                contents = page.get("Contents", [])
                # Собираем ключи объектов, которые содержат наш маркер
                objects_to_delete: list[ObjectIdentifierTypeDef] = [
                    {"Key": str(obj["Key"])} for obj in contents if obj.get("Key") and marker in str(obj["Key"])
                ]

                if objects_to_delete:
                    found_any = True
                    # Удаляем пачкой (до 1000 за раз по лимиту S3 API)
                    await s3_client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects_to_delete})

            if found_any:
                logger.info(f"S3_CLEANUP: Все файлы с маркером {marker} удалены.")
            return True
        except Exception as e:
            logger.error(f"S3_CLEANUP_ERROR: Не удалось очистить файлы {marker}: {e}")
            return False

    # --- КЛАССИЧЕСКОЕ УДАЛЕНИЕ ПО URL/KEY ---

    async def delete_file_by_url(self, url: str, client: S3Client | None = None) -> bool:
        try:
            bucket_marker = f"{self.bucket}/"
            if bucket_marker not in url:
                return False
            object_key = url.split(bucket_marker)[-1]
            return await self.delete_file(object_key, client=client)
        except Exception as e:
            logger.error(f"Не удалось распарсить URL для удаления: {url}. Ошибка: {e}")
            return False

    async def delete_file(self, object_name: str, client: S3Client | None = None) -> bool:
        if client:
            return await self._execute_delete(client, object_name)
        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            return await self._execute_delete(s3, object_name)

    async def _execute_delete(self, s3_client: S3Client, object_name: str) -> bool:
        try:
            await s3_client.delete_object(Bucket=self.bucket, Key=object_name)
            logger.info(f"Объект S3 удален: {object_name}")
            return True
        except Exception as e:
            logger.error(f"Ошибка S3 при удалении {object_name}: {e}")
            return False
