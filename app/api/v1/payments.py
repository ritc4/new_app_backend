import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

# ИМПОРТИРУЕМ глобальную фабрику зависимости биллинга из единого места
from app.core.dependencies.payment import get_payment_service
from app.services.payment_service import PaymentService

logger = logging.getLogger("app.api.payments")
router = APIRouter()

# Создаем красивый алиас типа на основе выделенного сервиса платежей
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]


@router.post("/webhook-t-bank-payment", status_code=status.HTTP_200_OK, summary="Прием POST-вебхуков от Т-Банка")
async def tbank_payment_webhook(request: Request, service: PaymentServiceDep) -> str:
    """Прием асинхронных JSON-вебхуков от Т-Банка при успешной HOLD-заморозке денег."""
    payload = await request.json()

    status_bank = payload.get("Status")
    order_id = payload.get("OrderId")
    external_id = payload.get("PaymentId")
    amount_kopecks = payload.get("Amount")

    metadata = payload.get("Data", {})
    user_id = metadata.get("user_id")

    if not order_id or not user_id:
        return "OK"

    # AUTHORIZED в Т-Банке означает, что деньги успешно захолдированы на карте клиента
    if status_bank == "AUTHORIZED":
        amount_rub = float(amount_kopecks) / 100.0

        # Вызываем универсальный биллинг-сервис
        await service.process_bank_webhook(
            event_type=str(status_bank),
            order_id=int(order_id),
            external_id=str(external_id),
            amount=amount_rub,
            user_id=int(user_id),
        )
    return "OK"


@router.get("/webhook-sber-bank-payment", status_code=status.HTTP_200_OK, summary="Прием GET-вебхуков от Сбербанка")
async def sber_payment_webhook(
    md_order: Annotated[str, Query(alias="mdOrder")],
    order_number: Annotated[str, Query(alias="orderNumber")],
    operation: str,
    status_code: Annotated[int, Query(alias="status")],
    service: PaymentServiceDep,
) -> str:
    """Прием асинхронных GET-уведомлений о статусах транзакции от Сбербанка."""
    try:
        # Извлекаем чистый ID заказа из строки вида "order_123"
        clean_order_id = int(order_number.replace("order_", ""))
    except ValueError:
        return "OK"

    # status_code == 1 и операция approved/deposited означает успешный HOLD в Сбере
    if status_code == 1 and (operation in ("approved", "deposited")):
        # Вызываем универсальный биллинг-сервис.
        # Передаем amount=0.0 и user_id=0, сервис сам подгрузит их из модели Order в PostgreSQL
        await service.process_bank_webhook(
            event_type=f"SBER_{operation}",
            order_id=clean_order_id,
            external_id=md_order,
            amount=0.0,
            user_id=0,
        )
    return "OK"
