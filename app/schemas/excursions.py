from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ActionResponse


class ExcursionMediaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    photo_url: str
    sort_order: int


class ExcursionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    guide_profile_id: int
    region_id: int
    title: str
    description: str
    main_photo_url: str
    duration_hours: float
    max_people_count: int
    price: float
    currency: str
    is_active: bool
    is_verified: bool
    medias: list[ExcursionMediaResponse] = Field(default=[])


class ExcursionCreateRequest(BaseModel):
    region_id: int = Field(..., description="ID региона деятельности из city_regions")
    title: str = Field(..., min_length=5, max_length=150)
    description: str = Field(..., min_length=20, max_length=2000)
    main_photo_url: str = Field(..., max_length=500, description="Ссылка из S3")
    duration_hours: float = Field(..., ge=0.5, le=24.0)
    max_people_count: int = Field(..., ge=1, le=100)
    price: float = Field(..., ge=0.0)


class ExcursionSlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    excursion_id: int
    execution_at: datetime
    available_slots: int
    is_active: bool


class ExcursionSlotCreateRequest(BaseModel):
    excursion_id: int
    execution_at: datetime = Field(..., description="Дата и время старта экскурсии")
    available_slots: int = Field(..., ge=1, le=100)


class BookExcursionRequest(BaseModel):
    slot_id: int = Field(..., description="ID выбранного временного слота из календаря")
    pax_count: int = Field(..., ge=1, le=50, description="Сколько билетов покупает турист")


class BookExcursionSuccessResponse(ActionResponse):
    """Ответ клиенту при успешном резервировании мест на экскурсию."""

    slot_id: int
    reserved_seats: int
    amount_to_pay: float
