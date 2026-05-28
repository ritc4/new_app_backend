from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ActionResponse


class CreateReviewRequest(BaseModel):
    order_id: int = Field(..., description="ID завершенного заказа")
    rating: int = Field(..., ge=1, le=5, description="Оценка от 1 до 5")
    comment: str | None = Field(None, max_length=1000, description="Текстовый комментарий пассажира")


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    rating: int
    comment: str | None
    created_at: datetime


class CreateReviewSuccessResponse(ActionResponse):
    review: ReviewResponse
