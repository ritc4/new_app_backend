from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies.reviews import get_review_service
from app.core.dependencies.user import get_current_customer
from app.models.user import User
from app.schemas.reviews import CreateReviewRequest, CreateReviewSuccessResponse
from app.services.review_service import ReviewService

router = APIRouter()

ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]
CustomerDep = Annotated[User, Depends(get_current_customer)]


@router.post(
    "/order",
    response_model=CreateReviewSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Оценить выполненный заказ (Трансфер или Экскурсию)",
)
async def leave_order_review(
    data: CreateReviewRequest, current_user: CustomerDep, service: ReviewServiceDep
) -> CreateReviewSuccessResponse:
    """Единый легкий эндпоинт для Flutter UI."""
    return await service.create_review(client_id=current_user.id, data=data)
