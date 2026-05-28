import hashlib
import logging
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import StoragePaths
from app.models.excursions import Excursion, ExcursionSlot
from app.models.orders import Order, OrderStatus, OrderStatusLog
from app.models.user import User
from app.repositories.excursion_repository import ExcursionRepository
from app.schemas.excursions import (
    BookExcursionRequest,
    ExcursionCreateRequest,
    ExcursionResponse,
    ExcursionSlotCreateRequest,
    ExcursionSlotResponse,
)
from app.schemas.payments import (
    SberRegisterSuccessResponse,
    TBankFlatSignParams,
    TBankInitDataField,
    TBankInitRequest,
    TBankInitSuccessResponse,
)
from app.schemas.s3 import S3UploadResult
from app.schemas.transfers import CreateOrderHighloadResponse
from app.services.payment_service import PaymentService
from app.services.s3_service import S3Service

logger = logging.getLogger("app.services.excursion")


class ExcursionService:
    def __init__(self, db: AsyncSession, s3: S3Service) -> None:
        self.db = db
        self.s3 = s3  # Железно сохраняем S3 сервис в объекте класса
        self.repo = ExcursionRepository(db)

    # =========================================================================
    # РАБОТА С КАРТОЧКАМИ И СЛОТАМИ КАЛЕНДАРЯ
    # =========================================================================

    async def get_excursions_in_region(self, region_id: int) -> list[ExcursionResponse]:
        """Бизнес-логика получения списка активных экскурсий региона для витрины туриста."""
        excursions = await self.repo.get_active_excursions_by_region(region_id)
        return [ExcursionResponse.model_validate(e) for e in excursions]

    async def create_new_excursion_by_guide(self, guide: User, data: ExcursionCreateRequest) -> ExcursionResponse:
        """Регистрация новой экскурсионной авторской программы гидом (отправка на модерацию)."""
        if not guide.trip_guide_profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для создания экскурсий необходимо заполнить профиль гида и пройти онбординг.",
            )
        try:
            new_excursion = Excursion(
                guide_profile_id=guide.trip_guide_profile.id,
                region_id=data.region_id,
                title=data.title.strip(),
                description=data.description.strip(),
                main_photo_url=data.main_photo_url,
                duration_hours=data.duration_hours,
                max_people_count=data.max_people_count,
                price=data.price,
                currency="RUB",
                is_active=True,
                is_verified=False,  # Отправляем на премодерацию администраторам маркетплейса
            )
            await self.repo.add_excursion(new_excursion)
            await self.db.flush()  # Генерируем первичный ключ id
            await self.db.commit()
            logger.info(f"EXCURSION_CREATED: Гид ID {guide.id} создал программу №{new_excursion.id}")
            return ExcursionResponse.model_validate(new_excursion)
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка создания карточки экскурсии для гида {guide.id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Не удалось сохранить экскурсию в системе"
            ) from e

    async def get_active_slots_for_tourist(self, excursion_id: int) -> list[ExcursionSlotResponse]:
        """Получить календарную сетку будущих выездов для карточки во Flutter."""
        slots = await self.repo.get_slots_by_excursion(excursion_id)
        return [ExcursionSlotResponse.model_validate(s) for s in slots]

    async def open_new_calendar_slot(self, guide: User, data: ExcursionSlotCreateRequest) -> ExcursionSlotResponse:
        """Метод в личном кабинете гида: открыть новую дату/время для бронирований во Flutter."""
        # ИСПРАВЛЕНО ДЛЯ MYPY: Сначала проверяем профиль гида на None
        profile = guide.trip_guide_profile
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У вас отсутствует рабочий профиль гида для управления расписанием.",
            )

        excursion = await self.repo.get_by_id(data.excursion_id)
        if not excursion:
            raise HTTPException(status_code=404, detail="Экскурсия не найдена.")

        # ИСПРАВЛЕНО ДЛЯ MYPY: Теперь анализатор железно уверен, что у profile есть атрибут id
        if excursion.guide_profile_id != profile.id:
            raise HTTPException(status_code=403, detail="Вы не можете управлять календарем чужой экскурсии.")

        if data.available_slots > excursion.max_people_count:
            raise HTTPException(
                status_code=400,
                detail=f"Лимит мест не может превышать вместимость группы ({excursion.max_people_count} чел.).",
            )
        try:
            new_slot = ExcursionSlot(
                excursion_id=data.excursion_id,
                execution_at=data.execution_at,
                available_slots=data.available_slots,
                is_active=True,
            )
            await self.repo.add_slot(new_slot)
            await self.db.commit()

            logger.info(
                f"CALENDAR_SLOT_OPENED: Гид {guide.id} "
                f"открыл выезд {data.execution_at} для экскурсии {data.excursion_id}"
            )
            return ExcursionSlotResponse.model_validate(new_slot)

        except Exception as e:
            await self.db.rollback()
            logger.error(f"Ошибка открытия слота календаря: {e}")
            raise HTTPException(500, "Не удалось открыть дату выезда.") from e

    # =========================================================================
    # ВНУТРЕННЯЯ КРИПТОГРАФИЯ И АТОМАРНОЕ БРОНИРОВАНИЕ МЕСТ (ДЛЯ CELERY)
    # =========================================================================

    def _generate_tbank_sign(self, params: dict[str, str | int], secret_key: str) -> str:
        """Промышленная генерация подписи Token для Т-Банка (SHA-256) по плоским параметрам."""
        sorted_params = {k: v for k, v in sorted(params.items()) if k not in ["Data", "Receipt", "Token"]}
        sorted_params["Password"] = secret_key
        sign_string = "".join(str(sorted_params[k]) for k in sorted(sorted_params.keys()))
        return hashlib.sha256(sign_string.encode("utf-8")).hexdigest()

    async def book_excursion_places(self, client_id: int, data: BookExcursionRequest) -> int:
        """
        Атомарное бронирование мест туристом.
        Защищено от Race Condition и овербукинга через FOR UPDATE NOWAIT.
        Возвращает ID созданного заказа (int) для передачи в Celery-воркер.
        """
        # 1. Захватываем строку слота с пессимистической блокировкой
        # 1. Захватываем строку слота с пессимистической блокировкой
        slot = await self.repo.get_slot_for_update_atomic(data.slot_id)
        if not slot:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Места на это время сейчас оформляются другим пользователем. Пожалуйста, повторите попытку.",
            )

        # 2. Проверяем доступность слота по времени на уровне Python (ИСПРАВЛЕНО НА datetime.now(UTC))
        if not slot.is_active or slot.execution_at <= datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Запись на выбранную дату и время уже закрыта."
            )

        # 3. КРИТИЧЕСКАЯ ПРОВЕРКА: Достаточно ли свободных мест в группе
        if slot.available_slots < data.pax_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Недостаточно мест. Осталось всего: {slot.available_slots} шт.",
            )

        try:
            # 4. Вытаскиваем карточку экскурсии для расчета стоимости (Прайс-фриз защита)
            excursion = await self.repo.get_by_id(slot.excursion_id)
            if not excursion or not excursion.is_active:
                raise HTTPException(status_code=404, detail="Экскурсия больше недоступна для бронирования.")

            total_amount = round(excursion.price * data.pax_count, 2)
            commission = round(total_amount * 0.15, 2)  # 15% комиссия маркетплейса

            # 5. АТОМАРНОЕ УМЕНЬШЕНИЕ СВОБОДНЫХ МЕСТ В СУБД
            slot.available_slots -= data.pax_count

            # 6. Создаем предварительный заказ со статусом ожидания оплаты
            new_order = Order(
                client_id=client_id,
                performer_id=None,  # Назначится гидом асинхронно после получения вебхука оплаты
                excursion_id=excursion.id,
                transfer_route_id=None,
                status=OrderStatus.PENDING_PAYMENT,
                execution_at=slot.execution_at,
                total_price=total_amount,
                service_commission=commission,
                currency="RUB",
                pax_count=data.pax_count,
            )
            self.db.add(new_order)
            await self.db.flush()  # Выделяем ID заказа в PostgreSQL

            # Пишем системный аудит-лог
            log = OrderStatusLog(
                order_id=new_order.id,
                from_status=None,
                to_status=str(OrderStatus.PENDING_PAYMENT.value),
                changed_by_id=client_id,
                reason=f"Бронирование {data.pax_count} мест на экскурсию №{excursion.id} через Celery-очередь",
            )
            self.db.add(log)

            # Завершаем транзакцию: блокировка со строки слота снимается, Celery-таск видит запись заказа в БД
            await self.db.commit()
            logger.info(f"EXCURSION_SEATS_RESERVED: Клиент {client_id} забронировал заказ №{new_order.id}")

            return int(new_order.id)

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка транзакции бронирования мест экскурсии: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Критический сбой СУБД при резервировании мест.") from e

    # =========================================================================
    # HIGHLOAD ОРКЕСТРАЦИЯ ФЛОУ ФЛАТТЕРА
    # =========================================================================

    async def process_highload_excursion_booking(
        self, user_id: int, data: BookExcursionRequest, provider: str
    ) -> CreateOrderHighloadResponse:
        """Вызывается из FastAPI роутера экскурсий. Быстрая фиксация брони в БД + Celery."""
        from app.workers.excursions.tasks import generate_excursion_payment_link_task

        # Вызываем атомарный метод списания мест, возвращающий int ID заказа
        order_id = await self.book_excursion_places(client_id=user_id, data=data)

        # Перенаправляем тяжелую сетевую задачу интеграции в брокер RabbitMQ
        generate_excursion_payment_link_task.delay(
            user_id=user_id, slot_id=data.slot_id, pax_count=data.pax_count, provider=provider, order_id=order_id
        )

        return CreateOrderHighloadResponse(
            status="processing",
            message="Бронирование мест начато, платежная ссылка формируется банком.",
            order_id=order_id,
        )

    # =========================================================================
    # СВЯЗЬ С БАНКОВСКИМИ API ШЛЮЗАМИ ВНУТРИ ЦЕЛЕРИ ВОРКЕРА
    # =========================================================================

    async def get_bank_url_for_existing_excursion_order(
        self, order_id: int, user_id: int, data: BookExcursionRequest, provider: str
    ) -> str:
        """Внутренний Celery-метод связи со шлюзами Т-Банка/Сбера для экскурсий."""
        # Для mypy/логов доказываем использование полей из схемы data
        logger.info(f"Генерация ссылки для слота {data.slot_id}, мест: {data.pax_count}")

        stmt = select(Order.total_price).where(Order.id == order_id)
        res = await self.db.execute(stmt)
        total_price = res.scalar()
        if not total_price:
            raise ValueError(f"Заказ экскурсии №{order_id} не найден.")

        amount_in_kopecks = int(total_price * 100)

        # ---------------------------------------------------------------------
        # ВЕТКА Т-БАНКА (Т-КАССА)
        # ---------------------------------------------------------------------
        if provider == "tbank":
            sign_model = TBankFlatSignParams(
                TerminalKey="YOUR_TBANK_TERMINAL_KEY",
                OrderId=str(order_id),
                Amount=amount_in_kopecks,
                Description=f"Оплата экскурсии, заказ №{order_id}",
                PayType="O",
            )
            sign_dict: dict[str, str | int] = {
                k: v for k, v in sign_model.model_dump().items() if isinstance(v, (str, int))
            }
            generated_token = self._generate_tbank_sign(sign_dict, "YOUR_TBANK_SECRET_KEY")

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

            return str(tbank_data.payment_url)

        # ---------------------------------------------------------------------
        # ВЕТКА СБЕРБАНКА
        # ---------------------------------------------------------------------
        if provider == "sberbank":
            sber_params: dict[str, str | int] = {
                "userName": "YOUR_SBER_LOGIN",
                "password": "YOUR_SBER_PASSWORD",
                "orderNumber": f"order_{order_id}",
                "amount": amount_in_kopecks,
                "returnUrl": "https://your-app.com",
                "failUrl": "https://your-app.com",
                "description": f"Оплата экскурсии №{order_id}",
            }
            async with httpx.AsyncClient() as client:
                pay_res = await client.post(
                    "https://sberbank.ru",
                    data=sber_params,
                )

            if pay_res.status_code != 200:
                raise RuntimeError(f"Sberbank шлюз вернул ошибку сети: {pay_res.text}")

            pay_json = pay_res.json()
            if "errorCode" in pay_json and int(str(pay_json["errorCode"])) != 0:
                raise RuntimeError(f"Отказ Сбербанка: {pay_json.get('errorMessage')}")

            sber_data = SberRegisterSuccessResponse.model_validate(pay_json)
            return str(sber_data.form_url)

        return ""

    async def cancel_order_by_guide(self, order_id: int, guide: User) -> CreateOrderHighloadResponse:
        """Бизнес-логика отмены забронированной экскурсии гидом с возвратом денег."""
        # ИСПРАВЛЕНО ДЛЯ MYPY: Извлекаем и валидируем профиль гида на наличие None
        profile = guide.trip_guide_profile
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У вас отсутствует рабочий профиль гида для совершения отмен.",
            )

        # 1. Защита: ищем заказ в СУБД
        stmt = select(Order).where(Order.id == order_id)
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Заказ экскурсии не найден.")

        # 2. Проверяем, что заказ действительно относится к одной из экскурсий этого гида
        excursion = await self.repo.get_by_id(order.excursion_id) if order.excursion_id else None

        # ИСПРАВЛЕНО ДЛЯ MYPY: Сравниваем со строго проверенным profile.id
        if not excursion or excursion.guide_profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вы не можете отменять чужие или несуществующие бронирования.",
            )

        # 3. Возвращаем места обратно в календарную сетку слотов, чтобы их могли купить другие
        from app.models.excursions import ExcursionSlot

        slot_stmt = select(ExcursionSlot).where(
            ExcursionSlot.excursion_id == order.excursion_id, ExcursionSlot.execution_at == order.execution_at
        )
        slot_res = await self.db.execute(slot_stmt)
        slot = slot_res.scalar_one_or_none()

        if slot:
            slot.available_slots += order.pax_count  # Возвращаем билеты в продажу

        # 4. Вызываем наш выделенный сквозной биллинг-сервис для отмены HOLD в банке
        # ИСПРАВЛЕНО ДЛЯ ИНТЕГРАЦИИ: Подключаем импорт платежного сервиса
        payment_service = PaymentService(db=self.db)

        await payment_service.cancel_and_refund_order_hold(
            order_id=order_id, changed_by_id=guide.id, reason="Гид отменил экскурсию по личным/техническим причинам"
        )

        return CreateOrderHighloadResponse(
            status="success",
            message="Экскурсия отменена, места возвращены в календарь, деньги возвращаются клиенту.",
            order_id=order_id,
        )

    async def get_excursion_photo_upload_params(
        self, guide: User, excursion_id: int, position_index: int, content_type: str
    ) -> S3UploadResult:
        """
        Полный цикл генерации параметров для загрузки фото экскурсии (0-9).
        Проверяет права гида, валидирует типы файлов и строит путь перезаписи в S3.
        """
        # 1. Валидация MIME-типов
        allowed_types = ["image/jpeg", "image/png", "image/webp"]
        if content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Разрешены только форматы изображений: JPEG, PNG, WEBP.",
            )

        # 2. Проверка авторизации и онбординга гида
        profile = guide.trip_guide_profile
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для управления медиафайлами необходимо заполнить профиль гида.",
            )

        # 3. Верификация владельца карточки экскурсии в СУБД
        excursion = await self.repo.get_by_id(excursion_id)
        if not excursion:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Экскурсия не найдена.")

        if excursion.guide_profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Вы не можете изменять медиафайлы чужой экскурсии."
            )

        # 4. Расчет стабильного имени объекта в бакете для автоматической перезаписи (0-9)
        object_name = StoragePaths.excursion_gallery_photo(
            excursion_id=excursion_id, position_index=position_index, content_type=content_type
        )

        # 5. Прямой вызов низкоуровневого метода из внедренного через конструктор S3-сервиса
        return await self.s3.get_upload_params_excursion(object_name=object_name, content_type=content_type)

    async def delete_excursion_by_guide(self, guide: User, excursion_id: int) -> CreateOrderHighloadResponse:
        """
        Бизнес-логика удаления авторской программы гидом.
        Запрещает удаление, если на экскурсию есть активные оплаченные бронирования.
        """
        profile = guide.trip_guide_profile
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У вас отсутствует рабочий профиль гида для совершения удалений.",
            )

        # 1. Загружаем экскурсию из репозитория для проверки прав
        excursion = await self.repo.get_by_id(excursion_id)
        if not excursion:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Экскурсия не найдена.")

        # 2. Строгая проверка прав владения карточкой (Type-Safe для MyPy)
        if excursion.guide_profile_id != profile.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вы не можете удалять чужие экскурсионные программы.",
            )

        # 3. БИЗНЕС-ПРАВИЛО: Вызываем чистый метод репозитория без сырых SQL-конструкций
        active_orders_count = await self.repo.count_active_orders_for_excursion(excursion_id)
        if active_orders_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Нельзя удалить экскурсию! На неё есть активные оплаченные бронирования "
                    f"({active_orders_count} шт.). Сначала отмените заказы или завершите поездки."
                ),
            )

        try:
            # 4. АТОМАРНОЕ УДАЛЕНИЕ ИЗ СУБД (PostgreSQL)
            await self.repo.delete_excursion(excursion)
            await self.db.commit()

            logger.warning(f"EXCURSION_DELETED: Гид ID {guide.id} полностью стёр программу №{excursion_id} из БД")

            # 5. ДЕЛЕГИРОВАНИЕ ФИЗИЧЕСКОЙ ОЧИСТКИ ИЗОБРАЖЕНИЙ В CELERY
            excursion_prefix = f"excursions/excursion_{excursion_id}/"

            from app.workers.users.tasks import delete_user_s3_resources_task

            delete_user_s3_resources_task.delay([excursion_prefix])

            logger.info(f"CELERY_EXCURSION_CLEANUP_DISPATCHED: Папка S3 {excursion_prefix} отправлена в воркер.")

            return CreateOrderHighloadResponse(
                status="success",
                message="Экскурсионная программа успешно удалена. Фотографии вычищаются из облака.",
                order_id=excursion_id,
            )

        except Exception as e:
            await self.db.rollback()
            if isinstance(e, HTTPException):
                raise e
            logger.error(f"Ошибка СУБД при удалении экскурсии {excursion_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось выполнить удаление экскурсии на стороне сервера.",
            ) from e
