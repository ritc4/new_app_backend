import hashlib
import logging

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.redis import redis_pool
from app.models.orders import Order, OrderStatus, OrderStatusLog
from app.models.spatial import CarClass
from app.models.user import User
from app.repositories.transfer_repository import TransferRepository
from app.schemas.base import ActionResponse
from app.schemas.payments import (
    SberRegisterSuccessResponse,
    TBankFlatSignParams,
    TBankInitDataField,
    TBankInitRequest,
    TBankInitSuccessResponse,
)
from app.schemas.transfers import (
    AcceptOrderResponse,
    AvailableOrderResponse,
    CarClassOption,
    CreateOrderHighloadResponse,
    HubResponse,
    OrderWithPaymentResponse,
    PaymentStatusResponse,
    RouteCalculateResponse,
    TransferOrderCreateRequest,
    TransferOrderResponse,
)
from app.services.payment_service import PaymentService
from app.workers.transfers.tasks import generate_payment_link_task

logger = logging.getLogger("app.services.transfer")


class TransferService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TransferRepository(db)

    async def search_location_hubs(self, query: str) -> list[HubResponse]:
        hubs = await self.repo.search_hubs_by_name(query)
        return [HubResponse.model_validate(h) for h in hubs]

    async def calculate_price(self, from_id: int, to_id: int) -> RouteCalculateResponse:
        route = await self.repo.get_route_with_prices(from_id, to_id)
        if not route:
            raise HTTPException(status_code=404, detail="Маршрут не обслуживается маркетплейсом.")
        options = [CarClassOption(car_class=CarClass(p.car_class), price=p.price) for p in route.prices]
        return RouteCalculateResponse(
            route_id=route.id,
            distance_km=route.distance_km,
            estimated_time_min=route.estimated_time_min,
            options=options,
        )

    def _generate_tbank_sign(self, params: dict[str, str | int], secret_key: str) -> str:
        """Промышленная генерация подписи Token для Т-Банка (SHA-256)."""
        sorted_params = {k: v for k, v in sorted(params.items()) if k not in ["Data", "Receipt", "Token"]}
        sorted_params["Password"] = secret_key
        sign_string = "".join(str(sorted_params[k]) for k in sorted(sorted_params.keys()))
        return hashlib.sha256(sign_string.encode("utf-8")).hexdigest()

    async def create_order_and_get_payment_url(
        self, user_id: int, data: TransferOrderCreateRequest, provider: str = "tbank"
    ) -> OrderWithPaymentResponse:
        """Оформление заказа с поддержкой Т-Банка и Сбербанка (двухстадийный HOLD)."""
        # 1. Верификация данных из БД
        route = await self.repo.get_route_by_id(data.route_id)
        if not route or not route.is_active:
            raise HTTPException(400, "Выбранный маршрут временно недоступен.")

        target_price = next((p.price for p in route.prices if p.car_class == data.car_class), None)
        if not target_price:
            raise HTTPException(400, f"Класс авто {data.car_class} недоступен на этом направлении.")

        commission = round(target_price * 0.15, 2)

        try:
            # 2. Сохраняем заказ в БД со статусом ожидания оплаты
            new_order = Order(
                client_id=user_id,
                transfer_route_id=data.route_id,
                car_class=data.car_class.value,
                status=OrderStatus.PENDING_PAYMENT,
                execution_at=data.execution_at,
                total_price=target_price,
                service_commission=commission,
                currency="RUB",
                pax_count=data.pax_count,
                client_comment=data.client_comment,
                flight_number=data.flight_number,
            )
            await self.repo.add_order(new_order)
            await self.db.flush()  # Получаем ID заказа `new_order.id`

            # 3. Фиксация начального статуса в лог
            init_log = OrderStatusLog(
                order_id=new_order.id,
                from_status=None,
                to_status=OrderStatus.PENDING_PAYMENT.value,
                changed_by_id=user_id,
                reason="Инициализация заказа клиентом",
            )
            await self.repo.add_status_log(init_log)

            # Переводим сумму в копейки (Enterprise стандарт для Сбера и Т-Банка)
            amount_in_kopecks = int(target_price * 100)
            payment_url = ""

            # 4А. ВЕТКА Т-БАНКА
            if provider == "tbank":
                # Сначала собираем только плоские параметры для Token подписи
                sign_model = TBankFlatSignParams(
                    TerminalKey="YOUR_TBANK_TERMINAL_KEY",  # Из settings
                    OrderId=str(new_order.id),
                    Amount=amount_in_kopecks,
                    Description=f"Оплата трансфера №{new_order.id}",
                    PayType="O",
                )

                # Собираем строго плоский словарь (mypy видит dict[str, str | int] и счастлив)
                sign_dict: dict[str, str | int] = {
                    k: v for k, v in sign_model.model_dump().items() if isinstance(v, (str, int))
                }
                generated_token = self._generate_tbank_sign(sign_dict, "YOUR_TBANK_SECRET_KEY")

                # Упаковываем финальный JSON-запрос через Pydantic схему
                tbank_request = TBankInitRequest(
                    TerminalKey=sign_model.TerminalKey,
                    OrderId=sign_model.OrderId,
                    Amount=sign_model.Amount,
                    Description=sign_model.Description,
                    PayType=sign_model.PayType,
                    Token=generated_token,
                    Data=TBankInitDataField(order_id=str(new_order.id), user_id=str(user_id)),
                )

                async with httpx.AsyncClient() as client:
                    pay_res = await client.post(
                        "https://tinkoff.ru",  # ИСПРАВЛЕНО НА БОЕВОЙ ШЛЮЗ
                        json=tbank_request.model_dump(),
                        headers={"Content-Type": "application/json"},
                    )

                if pay_res.status_code != 200:
                    raise HTTPException(502, f"Ошибка шлюза Т-Банка: {pay_res.text}")

                # Валидируем через Pydantic схему, уничтожая Any
                pay_data = TBankInitSuccessResponse.model_validate(pay_res.json())
                if not pay_data.is_success:
                    raise HTTPException(502, f"Отказ Т-Банка: {pay_data.status}")
                payment_url = pay_data.payment_url

            # 4Б. ВЕТКА СБЕРБАНКА (Преавторизация)
            elif provider == "sberbank":
                sber_params: dict[str, str | int] = {
                    "userName": "YOUR_SBER_LOGIN",
                    "password": "YOUR_SBER_PASSWORD",
                    "orderNumber": f"order_{new_order.id}",
                    "amount": amount_in_kopecks,
                    "returnUrl": "https://your-app.com",
                    "failUrl": "https://your-app.com",
                    "description": f"Оплата трансфера №{new_order.id}",
                }
                async with httpx.AsyncClient() as client:
                    # Сбербанк принимает строго Form-Data (application/x-www-form-urlencoded)
                    pay_res = await client.post(
                        "https://sberbank.ru",  # ИСПРАВЛЕНО НА БОЕВОЙ ШЛЮЗ
                        data=sber_params,
                    )

                if pay_res.status_code != 200:
                    raise HTTPException(502, f"Ошибка шлюза Сбербанка: {pay_res.text}")

                pay_json = pay_res.json()
                if "errorCode" in pay_json and int(str(pay_json["errorCode"])) != 0:
                    raise HTTPException(502, f"Отказ Сбербанка: {pay_json.get('errorMessage')}")

                # Валидируем через Pydantic схему, уничтожая Any и убирая CamelCase предупреждения Ruff
                sber_data = SberRegisterSuccessResponse.model_validate(pay_json)
                payment_url = sber_data.form_url

            await self.db.commit()
            logger.info(f"TRANSFER_ORDER_INITIATED: Заказ №{new_order.id}, Провайдер: {provider}. Ссылка выдана.")

            return OrderWithPaymentResponse(
                order=TransferOrderResponse.model_validate(new_order), payment_url=payment_url
            )

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка при создании заказа трансфера: {e}", exc_info=True)
            raise HTTPException(500, "Внутренняя ошибка сервера при оформлении заказа") from e

    async def get_bank_url_for_existing_order(
        self, order_id: int, user_id: int, data: TransferOrderCreateRequest, provider: str
    ) -> str:
        """Метод вызывается ВНУТРИ воркера Celery. Только связь с банком."""

        # 1. ДИНАМИЧЕСКИЙ РАСЧЕТ: Вытаскиваем цену из БД для защиты от фрода
        route = await self.repo.get_route_by_id(data.route_id)
        if not route:
            raise ValueError(f"Маршрут {data.route_id} не найден внутри воркера Celery")

        target_price = next((p.price for p in route.prices if p.car_class == data.car_class), None)
        if not target_price:
            raise ValueError(f"Тариф {data.car_class} недоступен для маршрута {data.route_id}")

        amount_in_kopecks = int(target_price * 100)

        # ==========================================
        # 4А. ВЕТКА Т-БАНКА
        # ==========================================
        if provider == "tbank":
            # 1. Собираем только плоские параметры через Pydantic
            sign_model = TBankFlatSignParams(
                TerminalKey="YOUR_TBANK_TERMINAL_KEY",
                OrderId=str(order_id),
                Amount=amount_in_kopecks,
                Description=f"Оплата трансфера №{order_id}",
                PayType="O",
            )

            # 2. model_dump() гарантированно отдает словарь типа dict[str, str | int]
            # mypy теперь на 100% уверен в типах аргумента и не выдаст [arg-type]
            sign_dict = sign_model.model_dump()
            generated_token = self._generate_tbank_sign(sign_dict, "YOUR_TBANK_SECRET_KEY")

            # 3. Собираем финальный payload запроса, объединяя данные
            tbank_request = TBankInitRequest(
                TerminalKey=sign_model.TerminalKey,
                OrderId=sign_model.OrderId,
                Amount=sign_model.Amount,
                Description=sign_model.Description,
                PayType=sign_model.PayType,
                Token=generated_token,
                Data=TBankInitDataField(order_id=str(order_id), user_id=str(user_id)),
            )

            async with httpx.AsyncClient() as client:
                pay_res = await client.post(
                    "https://tinkoff.ru",
                    json=tbank_request.model_dump(),
                    headers={"Content-Type": "application/json"},
                )

            if pay_res.status_code != 200:
                raise RuntimeError(f"Т-Банк шлюз вернул ошибку сети: {pay_res.text}")

            tbank_data = TBankInitSuccessResponse.model_validate(pay_res.json())
            if not tbank_data.is_success:
                raise RuntimeError(f"Отказ Т-Банка: {tbank_data.status}")

            return tbank_data.payment_url

        # ==========================================
        # 4Б. ВЕТКА СБЕРБАНКА (Преавторизация)
        # ==========================================
        if provider == "sberbank":
            sber_params: dict[str, str | int] = {
                "userName": "YOUR_SBER_LOGIN",
                "password": "YOUR_SBER_PASSWORD",
                "orderNumber": f"order_{order_id}",
                "amount": amount_in_kopecks,
                "returnUrl": "https://your-app.com",
                "failUrl": "https://your-app.com",
                "description": f"Оплата трансфера №{order_id}",
            }
            async with httpx.AsyncClient() as client:
                # Сбербанк строго требует x-www-form-urlencoded, поэтому data= вместо json=
                pay_res = await client.post(
                    "https://sberbank.ru",  # ИСПРАВЛЕНО НА РЕАЛЬНЫЙ ШЛЮЗ СБЕРА
                    data=sber_params,
                )

            if pay_res.status_code != 200:
                raise RuntimeError(f"Sberbank шлюз вернул ошибку сети: {pay_res.text}")

            pay_json = pay_res.json()
            if "errorCode" in pay_json and int(str(pay_json["errorCode"])) != 0:
                raise RuntimeError(f"Отказ Сбербанка: {pay_json.get('errorMessage')}")

            # Магия Pydantic: мапим camelCase Сбера в snake_case Python через alias, уничтожая Any
            sber_data = SberRegisterSuccessResponse.model_validate(pay_json)
            return sber_data.form_url

        return ""

    async def just_create_order_record(self, user_id: int, data: TransferOrderCreateRequest) -> int:
        """Быстро создает предварительную запись заказа для фиксации ID (2 миллисекунды)."""
        route = await self.repo.get_route_by_id(data.route_id)
        if not route or not route.is_active:
            raise HTTPException(400, "Выбранный маршрут временно недоступен.")

        target_price = next((p.price for p in route.prices if p.car_class == data.car_class), None)
        if not target_price:
            raise HTTPException(400, f"Класс авто {data.car_class} недоступен на этом направлении.")

        commission = round(target_price * 0.15, 2)

        try:
            new_order = Order(
                client_id=user_id,
                transfer_route_id=data.route_id,
                car_class=data.car_class.value,
                status=OrderStatus.PENDING_PAYMENT,
                execution_at=data.execution_at,
                total_price=target_price,
                service_commission=commission,
                currency="RUB",
                pax_count=data.pax_count,
                client_comment=data.client_comment,
                flight_number=data.flight_number,
            )
            await self.repo.add_order(new_order)
            await self.db.flush()  # Выделяем ID в PostgreSQL

            init_log = OrderStatusLog(
                order_id=new_order.id,
                from_status=None,
                to_status=OrderStatus.PENDING_PAYMENT.value,
                changed_by_id=user_id,
                reason="Инициализация Highload-заказа через Celery-очередь",
            )
            await self.repo.add_status_log(init_log)

            await self.db.commit()  # Завершаем транзакцию, чтобы воркер увидел запись
            return new_order.id

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка быстрой регистрации заказа: {e}")
            raise HTTPException(500, "Не удалось инициализировать заказ") from e

    async def check_order_payment_status(self, order_id: int) -> PaymentStatusResponse:
        """
        Проверяет готовность платежной ссылки в Redis.
        Инструмент Highload-поллинга для Flutter-приложения.
        """
        # Читаем данные из быстрого кэша Redis
        payment_url = await redis_pool.get(f"payment_url:{order_id}")

        # Ссылка еще не сгенерирована Celery-воркером
        if not payment_url:
            return PaymentStatusResponse(
                status="loading", message="Ссылка еще генерируется банком. Повторите запрос.", payment_url=None
            )

        # Ссылка успешно сгенерирована и получена
        url_str = payment_url.decode("utf-8") if isinstance(payment_url, bytes) else str(payment_url)

        return PaymentStatusResponse(status="ready", message="Ссылка успешно получена", payment_url=url_str)

    async def process_highload_order_creation(
        self, user_id: int, data: TransferOrderCreateRequest, provider: str
    ) -> CreateOrderHighloadResponse:
        """
        Оркестратор Highload-создания заказа.
        Регистрирует запись в БД и отправляет задачу генерации ссылки в Celery.
        """
        # 1. Быстро создаем предварительную запись заказа в СУБД (2 миллисекунды)
        order_id = await self.just_create_order_record(user_id=user_id, data=data)

        # 2. Отправляем тяжелую сетевую задачу в RabbitMQ/Celery
        generate_payment_link_task.delay(
            user_id=user_id,
            route_id=data.route_id,
            car_class=data.car_class.value,
            execution_at_iso=data.execution_at.isoformat(),
            provider=provider,
            order_id=order_id,
        )

        # 3. Возвращаем строгий объект схемы ответа
        return CreateOrderHighloadResponse(
            status="processing", message="Заказ создан, платежная ссылка генерируется банком", order_id=order_id
        )

    async def get_available_orders_for_driver(self, driver: User) -> list[AvailableOrderResponse]:
        """Возвращает список свободных оплаченных заказов в регионе водителя."""
        # БИЗНЕС-ПРАВИЛО: Если водитель выключил тумблер "На работе", биржа для него пуста
        if not driver.is_available:
            return []

        if not driver.supplier_profile:
            raise HTTPException(400, "Профиль водителя не настроен в системе.")

        orders = await self.repo.get_available_orders_by_region(
            region_id=driver.supplier_profile.base_region_id, car_class=driver.supplier_profile.car_class
        )

        result: list[AvailableOrderResponse] = []
        for o in orders:
            driver_salary = round(o.total_price - o.service_commission, 2)
            from_name = o.transfer_route.from_location.name if o.transfer_route else "Пункт А"
            to_name = o.transfer_route.to_location.name if o.transfer_route else "Пункт Б"

            result.append(
                AvailableOrderResponse(
                    id=o.id,
                    from_hub_name=from_name,
                    to_hub_name=to_name,
                    car_class=o.car_class or "economy",
                    price_for_driver=driver_salary,
                    execution_at=o.execution_at,
                    flight_number=o.flight_number,
                    pax_count=o.pax_count,
                    client_comment=o.client_comment,
                )
            )
        return result

    async def accept_order_by_driver(self, order_id: int, driver: User) -> AcceptOrderResponse:
        """Атомарный перехват заказа водителем с защитой от состояния гонки (Race Condition)."""
        # БИЗНЕС-ПРАВИЛО: Запрещаем брать заказы, если водитель в режиме отдыха
        if not driver.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вы не можете брать заказы, пока ваш статус установлен в 'Отдыхаю'.",
            )

        if not driver.supplier_profile:
            raise HTTPException(400, "У вас отсутствует рабочий профиль водителя.")

        order = await self.repo.get_order_for_update_atomic(order_id)
        if not order:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Увы, этот заказ уже перехвачен другим водителем. Обновите ленту.",
            )

        if order.status != OrderStatus.SEARCHING_PERFORMER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заказ больше недоступен для взятия.")

        try:
            old_status = order.status.value
            order.status = OrderStatus.ASSIGNED
            order.performer_id = driver.id

            log = OrderStatusLog(
                order_id=order.id,
                from_status=old_status,
                to_status=OrderStatus.ASSIGNED.value,
                changed_by_id=driver.id,
                reason=f"Водитель ID {driver.id} успешно взял заказ с биржи",
            )
            await self.repo.add_status_log(log)

            await self.db.commit()
            logger.info(f"DRIVER_ASSIGNED: Водитель {driver.id} забрал заказ №{order_id}")

            return AcceptOrderResponse(
                status="success",
                message="Вы успешно приняли заказ! Он отобразится в вашем расписании.",
                order_id=order.id,
            )

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка при транзакции фиксации водителя на заказ {order_id}: {e}")
            raise HTTPException(500, "Критический сбой СУБД при взятии заказа") from e

    async def cancel_order_by_driver(self, order_id: int, driver: User) -> ActionResponse:
        """Бизнес-логика отмены принятого заказа водителем."""
        # 1. Проверка тумблера активности водителя
        if not driver.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вы не можете совершать действия с заказами в режиме отдыха.",
            )

        # 2. Вызываем наш сквозной биллинг-сервис
        payment_service = PaymentService(db=self.db)

        await payment_service.cancel_and_refund_order_hold(
            order_id=order_id, changed_by_id=driver.id, reason="Водитель отменил поездку по техническим причинам"
        )

        return ActionResponse(status="success", message="Заказ отменен, деньги возвращаются клиенту.")
