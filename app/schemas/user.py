from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class UserRole(StrEnum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    TRIP_GUIDE = "trip_guide"


class UserShort(BaseModel):
    # Переход на ConfigDict для V2
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str | None = None
    last_name: str | None = None
    phone: str
