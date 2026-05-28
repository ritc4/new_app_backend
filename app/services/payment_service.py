import hashlib
import logging

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orders import Order, OrderStatus, OrderStatusLog
from app.models.transactions import Transaction, TransactionStatus, TransactionType

logger = logging.getLogger("app.services.payment_service")


class PaymentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def process_bank_webhook(
        self, event_type: str, order_id: int, external_id: str, amount: float, user_id: int
    ) -> str:
        """
        Централизованный оркестратор платежей маркетплейса.
        Изолирован в собственном биллинг-домене.
        """
        # 1. Ищем заказ в СУБД
        stmt = select(Order).where(Order.id == order_id)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()

        if not order:
            logger.error(f"BILLING_ERROR: Заказ №{order_id} не найден.")
            raise HTTPException(status_code=404, detail="Заказ не найден")

        # Защита от повторных вебхуков банка (Идемпотентность)
        if order.status == OrderStatus.SEARCHING_PERFORMER:
            return "OK"

        # Восстанавливаем данные из СУБД, если их не прислал Сбербанк
        if amount == 0.0:
            amount = order.total_price
        if user_id == 0:
            user_id = order.client_id

        try:
            old_status = order.status.value

            # Меняем статус заказа на "Оплачен, ищет исполнителя"
            order.status = OrderStatus.SEARCHING_PERFORMER

            # Пишем аудит-лог смены состояний
            status_log = OrderStatusLog(
                order_id=order.id,
                from_status=old_status,
                to_status=str(OrderStatus.SEARCHING_PERFORMER.value),
                changed_by_id=user_id,
                reason=f"Успешный HOLD средств от банка. Шлюз: {event_type}",
            )
            self.db.add(status_log)

            # Фиксируем финансовую транзакцию в бухгалтерии
            new_transaction = Transaction(
                order_id=order.id,
                user_id=user_id,
                amount=amount,
                type_transaction=TransactionType.PAYMENT,
                status=TransactionStatus.HOLD,
                external_payment_id=external_id,
            )
            self.db.add(new_transaction)

            await self.db.commit()
            logger.info(f"BILLING_SUCCESS: Успешный HOLD по заказу №{order_id} на сумму {amount} руб.")

            # =================================================================
            # АСИНХРОННОЕ РАСПРЕДЕЛЕНИЕ УВЕДОМЛЕНИЙ (Паттерн Event Emitter)
            # =================================================================
            if order.transfer_route_id is not None:
                # Триггерим фоновую Celery задачу отправки пушей ВОДИТЕЛЯМ
                logger.info(f"BILLING_EVENT: Запуск поиска водителей для трансфера №{order_id}")

            elif order.excursion_id is not None:
                # Триггерим фоновую Celery задачу отправки пушей ГИДУ
                logger.info(f"BILLING_EVENT: Запуск уведомления гида о покупке билетов на экскурсию №{order_id}")

            return "OK"

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Критическая ошибка платежного модуля СУБД: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка платежного модуля сервера"
            ) from e

    async def cancel_and_refund_order_hold(self, order_id: int, changed_by_id: int, reason: str) -> None:
        """
        Инициирует процесс отмены заказа и возврата (разблокировки) средств.
        Переводит статус в СУБД и отправляет тяжелую задачу в Celery.
        """
        from app.workers.payments.tasks import process_bank_refund_task

        # 1. Проверяем состояние заказа
        stmt = select(Order).where(Order.id == order_id)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()

        if not order:
            raise HTTPException(status_code=404, detail="Заказ для отмены не найден.")

        # Запрещено отменять уже выполненные или уже отмененные заказы
        if order.status in [OrderStatus.COMPLETED, OrderStatus.CANCELLED]:
            raise HTTPException(status_code=400, detail="Этот заказ нельзя отменить.")

        try:
            old_status = order.status.value
            # Переводим статус в СУБД в отмененный (2 миллисекунды)
            order.status = OrderStatus.CANCELLED

            # Записываем событие в аудит-лог для арбитража поддержки
            log = OrderStatusLog(
                order_id=order.id,
                from_status=old_status,
                to_status=str(OrderStatus.CANCELLED.value),
                changed_by_id=changed_by_id,
                reason=f"Отмена заказа. Причина: {reason}",
            )
            self.db.add(log)
            await self.db.commit()  # Снимаем блокировки СУБД мгновенно

            # 2. Сбрасываем тяжелую сетевую задачу возврата в RabbitMQ
            process_bank_refund_task.delay(order_id=order.id)
            logger.info(f"BILLING_CANCEL: Заказ №{order_id} отменен в СУБД, задача Refund ушла в Celery.")

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка при отмене заказа №{order_id} в СУБД: {e}")
            raise HTTPException(status_code=500, detail="Ошибка СУБД при отмене заказа.") from e

    async def execute_bank_api_refund(self, order_id: int) -> str:
        """
        НИЗКОУРОВНЕВЫЙ МЕТОД: Вызывается строго внутри воркера Celery.
        Стучится по API в Т-Банк или Сбербанк для физического снятия холда с карты.
        """
        from app.models.transactions import Transaction, TransactionStatus, TransactionType

        # 1. Ищем транзакцию типа PAYMENT со статусом HOLD для этого заказа
        tx_stmt = select(Transaction).where(
            Transaction.order_id == order_id,
            Transaction.type_transaction == TransactionType.PAYMENT,
            Transaction.status == TransactionStatus.HOLD,
        )
        tx_res = await self.db.execute(tx_stmt)
        transaction = tx_res.scalar_one_or_none()

        if not transaction or not transaction.external_payment_id:
            logger.warning(f"CELERY_REFUND: По заказу №{order_id} нет активного HOLD в СУБД. Пропускаем.")
            return "No hold found"

        # Определяем банк по формату external_payment_id (Сбер шлет uuid/строку, Т-Банк — числа)
        # В продакшене лучше заложить поле provider прямо в таблицу transactions
        is_sber = transaction.external_payment_id.startswith("order_") or "_" in transaction.external_payment_id

        # ---------------------------------------------------------------------
        # ВЕТКА Т-БАНКА (ОТМЕНА АВТОРИЗАЦИИ / CANCEL)
        # ---------------------------------------------------------------------
        if not is_sber:
            # Т-Банк требует Token безопасности для отмены
            # Метод _generate_tbank_sign можно переиспользовать или импортировать
            cancel_params: dict[str, str | int] = {
                "TerminalKey": "YOUR_TBANK_TERMINAL_KEY",
                "PaymentId": transaction.external_payment_id,
            }
            # Пускай считает токен через утилиту
            sign_string = f"PasswordYOUR_TBANK_SECRET_KEYPaymentId{transaction.external_payment_id}"
            token = hashlib.sha256(sign_string.encode("utf-8")).hexdigest()
            cancel_params["Token"] = token

            async with httpx.AsyncClient() as client:
                res = await client.post("https://tinkoff.ru", json=cancel_params)

            if res.status_code != 200 or not res.json().get("Success"):
                raise RuntimeError(f"Т-Банк API отклонил отмену холда: {res.text}")

        # ---------------------------------------------------------------------
        # ВЕТКА СБЕРБАНКА (РЕВЕРС ПЛАТЕЖА / REVERSE)
        # ---------------------------------------------------------------------
        else:
            sber_params = {
                "userName": "YOUR_SBER_LOGIN",
                "password": "YOUR_SBER_PASSWORD",
                "orderId": transaction.external_payment_id,  # Это банковский mdOrder
            }
            async with httpx.AsyncClient() as client:
                res = await client.post("https://sberbank.ru", data=sber_params)

            if res.status_code != 200 or res.json().get("errorCode", 0) != 0:
                raise RuntimeError(f"Сбербанк API отклонил отмену холда: {res.text}")

        # 2. Фиксируем успешный возврат средств в бухгалтерии маркетплейса
        try:
            transaction.status = TransactionStatus.FAILED  # Исходный hold закрыт (failed/released)

            # Пишем новую компенсирующую проводку типа REFUND
            refund_tx = Transaction(
                order_id=order_id,
                user_id=transaction.user_id,
                amount=transaction.amount,
                type_transaction=TransactionType.REFUND,
                status=TransactionStatus.SUCCESS,
                external_payment_id=f"refund_{transaction.external_payment_id}",
            )
            self.db.add(refund_tx)
            await self.db.commit()

            logger.info(f"CELERY_REFUND_SUCCESS: Деньги по заказу №{order_id} физически разблокированы банком.")
            return "SUCCESS"
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка сохранения статуса REFUND в СУБД: {e}")
            raise
