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

    async def delete_files_batch(self, urls: list[str], client: S3Client | None = None) -> int:
        """
        ПАКЕТНОЕ УДАЛЕНИЕ (Уровень Яндекса/Uber):
        Принимает список URL, извлекает ключи и удаляет их пачками до 1000 штук одним запросом.
        Исправлен ложно-положительный подсчет удаленных файлов при сбоях API.
        """
        if not urls:
            return 0

        bucket_marker = f"{self.bucket}/"

        # 1. Извлекаем чистые S3-ключи из URL-адресов
        keys_to_delete: list[ObjectIdentifierTypeDef] = []
        for url in urls:
            if bucket_marker in url:
                object_key = url.split(bucket_marker)[-1]
                keys_to_delete.append({"Key": object_key})

        if not keys_to_delete:
            return 0

        # Функция отправки пачки в S3, которая возвращает True при успехе
        async def _send_delete_req(s3_client: S3Client, batch_keys: list[ObjectIdentifierTypeDef]) -> bool:
            try:
                await s3_client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": batch_keys, "Quiet": True},  # Экономия трафика
                )
                return True
            except Exception as e:
                logger.error(f"Ошибка пакетного удаления пачки S3: {e}", exc_info=True)
                return False

        batch_size = 1000
        deleted_count = 0

        # Разрезаем на пачки по 1000 элементов (лимит S3 API)
        if client:
            # Если клиент передан (Keep-Alive соединение из Celery)
            for i in range(0, len(keys_to_delete), batch_size):
                chunk = keys_to_delete[i : i + batch_size]
                success = await _send_delete_req(client, chunk)
                if success:
                    deleted_count += len(chunk)  # Считаем только РЕАЛЬНО удаленные
        else:
            # Если создаем сессию заново
            async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
                for i in range(0, len(keys_to_delete), batch_size):
                    chunk = keys_to_delete[i : i + batch_size]
                    success = await _send_delete_req(s3, chunk)
                    if success:
                        deleted_count += len(chunk)

        return deleted_count

    async def copy_object(self, source_key: str, destination_key: str) -> bool:
        """Перенос файла внутри бакета (из tmp/ в permanent/). Бесплатно и мгновенно."""
        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            try:
                copy_source = {"Bucket": self.bucket, "Key": source_key}
                await s3.copy_object(CopySource=copy_source, Bucket=self.bucket, Key=destination_key)
                logger.info(f"Объект скопирован из {source_key} в {destination_key}")
                return True
            except Exception as e:
                logger.error(f"Ошибка S3 при копировании {source_key} -> {destination_key}: {e}", exc_info=True)
                raise

    async def delete_object(self, object_key: str) -> bool:
        """Точечное удаление одного объекта по его S3-ключу."""
        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            try:
                await s3.delete_object(Bucket=self.bucket, Key=object_key)
                return True
            except Exception as e:
                logger.error(f"Ошибка S3 при удалении объекта {object_key}: {e}")
                return False

    async def get_upload_params_excursion(
        self, object_name: str, content_type: str, expires_in: int = 900
    ) -> S3UploadResult:
        """Низкоуровневая генерация параметров presigned-поста в AWS/Yandex бакет."""
        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            try:
                post_data = await s3.generate_presigned_post(
                    Bucket=self.bucket,
                    Key=object_name,
                    Fields={"Content-Type": content_type},
                    Conditions=[
                        {"Content-Type": content_type},
                        ["content-length-range", 1, 10485760],  # Лимит до 10 МБ на фото
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

    async def delete_directory_by_prefix(self, prefix: str, client: S3Client | None = None) -> int:
        """
        ФИЗИЧЕСКОЕ ПАКЕТНОЕ УДАЛЕНИЕ ВИРТУАЛЬНОЙ ПАПКИ:
        Сканирует бакет по префиксу папки, собирает URL-адреса всех вложенных объектов
        и перенаправляет их в ваш готовый метод delete_files_batch.
        """
        if not prefix:
            return 0

        if not prefix.endswith("/"):
            prefix = f"{prefix}/"

        async def _collect_and_delete(s3_client: S3Client) -> int:
            paginator = s3_client.get_paginator("list_objects_v2")
            total_deleted = 0

            # Постранично выгребаем файлы из S3-папки (до 1000 штук на страницу согласно лимитам AWS API)
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                if "Contents" not in page:
                    continue

                # Формируем плоские URL-адреса, которые ожидает ваш delete_files_batch
                urls = [f"{self.endpoint_url}/{self.bucket}/{obj['Key']}" for obj in page["Contents"] if "Key" in obj]

                if urls:
                    # Вызываем ваш собственный готовый метод пакетного удаления
                    deleted_count = await self.delete_files_batch(urls, client=s3_client)
                    total_deleted += deleted_count

            return total_deleted

        # Используем переданный Keep-Alive клиент воркера или открываем временную сессию
        if client:
            return await _collect_and_delete(client)

        async with self.session.client("s3", config=self.s3_config, **self.client_kwargs) as s3:
            return await _collect_and_delete(s3)
