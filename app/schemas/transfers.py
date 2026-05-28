from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.orders import OrderStatus
from app.models.spatial import CarClass
from app.schemas.base import ActionResponse


class CreateOrderHighloadResponse(ActionResponse):
    order_id: int = Field(..., description="Числовой ID созданного заказа из PostgreSQL")


class PaymentStatusResponse(ActionResponse):
    payment_url: str | None = Field(None, description="Готовая ссылка на оплату Сбера/Т-Банка")


class HubResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    region_id: int
    name: str
    address: str
    type: str
    latitude: float
    longitude: float


class CarClassOption(BaseModel):
    car_class: CarClass = Field(..., description="Класс автомобиля")
    price: float = Field(..., description="Фиксированная стоимость")


class RouteCalculateResponse(BaseModel):
    route_id: int
    distance_km: float
    estimated_time_min: int
    options: list[CarClassOption] = Field(..., description="Доступные тарифы")


class TransferOrderCreateRequest(BaseModel):
    route_id: int = Field(..., description="ID выбранного маршрута")
    car_class: CarClass = Field(..., description="Выбранный класс машины")
    execution_at: datetime = Field(..., description="Дата и время подачи машины (ISO)")
    flight_number: str | None = Field(None, max_length=30)
    pax_count: int = Field(default=1, ge=1, le=20)
    client_comment: str | None = Field(None, max_length=1000)


class TransferOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    route_id: int
    status: OrderStatus
    car_class: str | None
    price: float = Field(..., alias="total_price")
    execution_at: datetime
    flight_number: str | None
    pax_count: int


class OrderWithPaymentResponse(BaseModel):
    order: TransferOrderResponse
    payment_url: str = Field(..., description="Ссылка на безопасную страницу банка")


class AvailableOrderResponse(BaseModel):
    """Схема заказа, отображаемая на бирже в приложении водителя."""

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(..., alias="id")
    from_hub_name: str = Field(..., description="Название хаба отправления")
    to_hub_name: str = Field(..., description="Название хаба назначения")
    car_class: str
    price_for_driver: float = Field(..., description="Чистый заработок водителя (за вычетом комиссии)")
    execution_at: datetime
    flight_number: str | None = None
    pax_count: int
    client_comment: str | None = None


class AcceptOrderResponse(ActionResponse):
    """Ответ водителю при попытке перехватить заказ."""

    order_id: int
