# from datetime import datetime

# from pydantic import BaseModel, ConfigDict, Field

# # ==========================================
# # ШАБЛОНЫ ДЛЯ ВХОДЯЩИХ ДАННЫХ (API Запросы)
# # ==========================================


# class ExcursionCreate(BaseModel):
#     """Схема валидации данных при создании экскурсии гидом."""

#     region_id: int = Field(..., description="ID региона проведения из справочника city_regions")
#     title: str = Field(..., min_length=5, max_length=150, description="Название экскурсии")
#     description: str = Field(..., min_length=20, description="Полное описание маршрута")
#     main_photo_url: str = Field(..., max_length=500, description="Ссылка на S3 превью")
#     duration_hours: float = Field(..., gt=0, le=72, description="Длительность в часах (от 0 до 72)")
#     max_people_count: int = Field(..., gt=0, description="Максимальный размер группы")
#     price: float = Field(..., ge=0, description="Стоимость за всю группу")
#     currency: str = Field(default="RUB", min_length=3, max_length=3, description="ISO-код валюты")


# class ExcursionUpdate(BaseModel):
#     """Схема для частичного редактирования экскурсии (все поля опциональны)."""

#     title: str | None = Field(None, min_length=5, max_length=150)
#     description: str | None = Field(None, min_length=20)
#     main_photo_url: str | None = Field(None, max_length=500)
#     duration_hours: float | None = Field(None, gt=0, le=72)
#     max_people_count: int | None = Field(None, gt=0)
#     price: float | None = Field(None, ge=0)
#     is_active: bool | None = Field(None, description="Включение/отключение отображения гидом")


# # ==========================================
# # ШАБЛОНЫ ДЛЯ ИСХОДЯЩИХ ДАННЫХ (API Ответы)
# # ==========================================


# class ExcursionMediaResponse(BaseModel):
#     """Схема ответа для отдельной фотографии из карусели."""

#     id: int
#     photo_url: str
#     sort_order: int

#     class Config:
#         from_attributes = True  # Позволяет Pydantic читать данные прямо из моделей SQLAlchemy


# class ExcursionResponse(BaseModel):
#     """Финальная карточка экскурсии, которую видит клиент в поиске."""

#     model_config = ConfigDict(from_attributes=True, populate_by_name=True)
#     id: int
#     guide_profile_id: int
#     region_id: int
#     title: str
#     description: str
#     main_photo_url: str
#     duration_hours: float
#     max_people_count: int
#     price: float
#     currency: str
#     is_active: bool
#     is_verified: bool
#     created_at: datetime

#     # Автоматически вложенная карусель картинок
#     medias: list[ExcursionMediaResponse] = []
