from typing import TypedDict


class S3PresignedPost(TypedDict):
    """Структура, которую возвращает метод generate_presigned_post в boto3."""

    url: str
    fields: dict[str, str]


class S3UploadResult(TypedDict):
    """Контракт нашего S3 сервиса."""

    upload_data: S3PresignedPost
    public_url: str
