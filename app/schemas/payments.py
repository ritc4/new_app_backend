from pydantic import BaseModel, ConfigDict, Field


class TBankInitSuccessResponse(BaseModel):
    """Строгий типизированный ответ от Т-Банка при успешной инициализации HOLD."""

    model_config = ConfigDict(populate_by_name=True)

    is_success: bool = Field(..., alias="Success", description="Флаг успешности операции")
    status: str = Field(..., alias="Status", description="Статус транзакции (например, NEW)")
    payment_id: str = Field(..., alias="PaymentId", description="ID транзакции в системе Т-Банка")
    payment_url: str = Field(..., alias="PaymentURL", description="Платежная ссылка для Flutter")
    amount: int = Field(..., alias="Amount", description="Сумма платежа в копейках")
    order_id: str = Field(..., alias="OrderId", description="ID заказа в нашей системе")


class SberRegisterSuccessResponse(BaseModel):
    """Строгий типизированный ответ от Сбербанка при успешной преавторизации."""

    model_config = ConfigDict(populate_by_name=True)

    order_id: str = Field(..., alias="orderId", description="Внутренний ID транзакции в системе Сбербанка")
    form_url: str = Field(..., alias="formUrl", description="Безопасная платежная ссылка для Flutter")


class TBankInitDataField(BaseModel):
    """Кастомные метаданные для вебхука Т-Банка."""

    order_id: str
    user_id: str


class TBankFlatSignParams(BaseModel):
    """Строгие параметры для генерации подписи (Token) Т-Банка."""

    TerminalKey: str
    OrderId: str
    Amount: int
    Description: str
    PayType: str


class TBankInitRequest(BaseModel):
    """Строгая схема тела запроса (Payload) к API Т-Банка."""

    TerminalKey: str
    OrderId: str
    Amount: int
    Description: str
    PayType: str
    Token: str | None = None  # Сначала None, запишем после генерации подписи
    Data: TBankInitDataField  # Вложенная схема метаданных
