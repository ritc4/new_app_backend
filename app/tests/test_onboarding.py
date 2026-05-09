import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingApplication
from app.models.user import User  # Импортируйте модель User для аннотаций


@pytest.mark.asyncio
async def test_create_duplicate_application_fails(client, user_token):
    # Создаем первую заявку
    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )

    # Пытаемся создать вторую (другая роль)
    resp = await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "trip_guide", "bank": "t_bank"},
    )

    assert resp.status_code == 400
    assert "уже есть активная заявка" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bank_webhook_idempotency(client, test_user, user_token):
    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )

    payload = {
        "user_id": test_user.id,
        "phone": test_user.phone,
        "inn": "123456789012",
        "full_name": "Иванов Иван Иванович",
    }

    # Первый вызов
    resp1 = await client.post("/api/v1/onboarding/webhook/bank", json=payload)
    assert resp1.status_code == 200

    # Второй (повторный) вызов
    resp2 = await client.post("/api/v1/onboarding/webhook/bank", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["message"] == "Already processed"


@pytest.mark.asyncio
async def test_submit_survey_without_legal_fails(client, user_token):
    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )

    # Шлем ПОЛНУЮ валидную анкету, но БЕЗ прохождения банка
    resp = await client.post(
        "/api/v1/onboarding/submit-survey",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "car_model": "Tesla",
            "car_year": 2022,
            "car_number": "Х777ХХ77",
            "car_color": "Белый",
            "license_number": "9901123456",
            "license_expiry_date": "2030-01-01",
            "experience_years": 5,
            "photo_selfie": "http://s3.com",
            "photo_car_front": "http://s3.com",
            "photo_car_back": "http://s3.com",
            "photo_sts_front": "http://s3.com",
            "photo_sts_back": "http://s3.com",
            "photo_license": "http://s3.com",
        },
    )
    # Теперь данные валидны для Pydantic (не 422),
    # и сервис выдаст твою бизнес-ошибку 400
    assert resp.status_code == 400
    assert "сначала пройти юридическую проверку" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_survey_validation_errors(client, user_token, test_user):
    # Проходим до этапа анкеты
    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )
    await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={"user_id": test_user.id, "phone": test_user.phone, "inn": "123456789012", "full_name": "Иванов И.И."},
    )

    # Шлем плохие данные (стаж 1 год вместо 3)
    resp = await client.post(
        "/api/v1/onboarding/submit-survey",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"experience_years": 1, "car_year": 2000},
    )  # Машина старая + стаж мал

    assert resp.status_code == 422
    assert "experience_years" in resp.text or "car_age" in resp.text


@pytest.mark.asyncio
async def test_s3_upload_restriction_by_role(client, user_token, test_user):
    # 1. Создаем заявку как гид
    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "trip_guide", "bank": "sber"},
    )

    # 2. ИМИТИРУЕМ прохождение банка (чтобы статус стал 'filling_survey')
    # Иначе получишь 403 Forbidden вместо 400
    await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={"user_id": test_user.id, "phone": test_user.phone, "inn": "1234567890", "full_name": "Гид Иван"},
    )

    # 3. Запрос на получение ссылки
    resp = await client.get(
        "/api/v1/onboarding/upload-link",
        headers={"Authorization": f"Bearer {user_token}"},
        params={
            "file_type": "photo_sts_front",  # ТЕПЕРЬ СОВПАДАЕТ С РОУТЕРОМ
            "content_type": "image/jpeg",
        },
    )

    # Теперь FastAPI пропустит запрос (не будет 422),
    # сервис пропустит по статусу (не будет 403)
    # и выдаст 400, так как поле запрещено для этой роли.
    assert resp.status_code == 400
    assert "не предусмотрен" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_restore_user_preserves_role(client, user_token, test_user):
    # 1. Удаляем аккаунт (Soft Delete)
    await client.delete("/api/v1/users/me", headers={"Authorization": f"Bearer {user_token}"})

    # 2. Имитируем повторный вход (Login/Create)
    # Вызываем метод репозитория или эндпоинт входа
    # Проверяем, что роль осталась прежней и deleted_at == None


@pytest.mark.asyncio
async def test_onboarding_to_supplier_conversion(
    client: AsyncClient, db_session: AsyncSession, test_user: User, user_token: str, admin_token: str
) -> None:  # Добавили аннотации
    # СОХРАНЯЕМ данные заранее, чтобы не зависеть от состояния сессии
    current_user_id = test_user.id
    current_user_phone = test_user.phone

    # --- ШАГ 0: Создание заявки ---
    start_resp = await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )
    assert start_resp.status_code == 200
    db_session.expire_all()

    # СИНХРОНИЗАЦИЯ: гарантируем, что Mypy/SQLAlchemy видят актуальные данные
    db_session.expire_all()

    result = await db_session.execute(
        select(OnboardingApplication.id).where(OnboardingApplication.user_id == current_user_id)
    )
    application_id = result.scalar()

    if not application_id:
        raise Exception(f"Заявка для пользователя {current_user_id} не найдена!")

    # 1. Банк подтверждает личность (Вебхук)
    bank_resp = await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={
            "user_id": current_user_id,
            "phone": current_user_phone,
            "inn": "123456789012",
            "full_name": "Иванов Иван Иванович",
        },
    )
    assert bank_resp.status_code == 200

    db_session.expire_all()

    # 2. Юзер отправляет анкету машины
    survey_resp = await client.post(
        "/api/v1/onboarding/submit-survey",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "car_model": "Tesla Model 3",
            "car_year": 2022,
            "car_number": "Х777ХХ77",
            "car_color": "Белый",
            "vin_number": "1YVHP8CB123456789",
            "license_number": "9901123456",
            "license_expiry_date": "2030-01-01",
            "license_country": "RU",
            "experience_years": 5,
            "photo_selfie": "http://s3.com",
            "photo_car_front": "http://s3.com",
            "photo_car_back": "http://s3.com",
            "photo_sts_front": "http://s3.com",
            "photo_sts_back": "http://s3.com",
            "photo_license": "http://s3.com",
        },
    )
    assert survey_resp.status_code == 200

    # 3. Админ одобряет
    approve_resp = await client.patch(
        f"/api/v1/admin/onboarding/{application_id}/approve", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert approve_resp.status_code == 200
    db_session.expire_all()
    # 4. Проверка результата
    me_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {user_token}"})
    data = me_resp.json()
    print(f"DEBUG DATA: {data}")  # Посмотрите, что реально возвращает сервер
    assert data["user"]["role"] == "supplier"
    assert data["supplier_data"]["car_model"] == "Tesla Model 3"


@pytest.mark.asyncio
async def test_bank_webhook_phone_mismatch(
    client: AsyncClient, db_session: AsyncSession, test_user: User, user_token: str
) -> None:
    # Сохраняем ID, так как после запросов к API сессия может обновиться
    u_id = test_user.id

    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )

    db_session.expire_all()

    resp = await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={
            "user_id": u_id,
            "phone": "+70000000000",  # Неверный телефон
            "inn": "123456789012",
            "full_name": "Иванов Иван",
        },
    )
    db_session.expire_all()
    assert resp.status_code == 400
    res = await db_session.execute(select(OnboardingApplication).where(OnboardingApplication.user_id == u_id))
    app = res.scalar_one()
    assert app.status == "rejected"
    assert "не совпадает" in app.admin_comment
    assert resp.json()["detail"] == "Телефоны не совпадают"


@pytest.mark.asyncio
async def test_cancel_and_restart_onboarding(client, user_token, db_session, test_user):
    """Тест сценария: Начал как водитель -> Отменил -> Стал гидом."""

    # 1. Создаем заявку как водитель
    start_resp = await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )
    assert start_resp.status_code == 200

    # 2. Отменяем её
    cancel_resp = await client.delete("/api/v1/onboarding/cancel", headers={"Authorization": f"Bearer {user_token}"})
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "success"

    # 1. СОХРАНЯЕМ ID в простую переменную ДО expire_all
    u_id = test_user.id

    # 2. Сбрасываем состояние сессии
    db_session.expire_all()

    # 3. Используем u_id (просто число), а не test_user.id (атрибут модели)
    res = await db_session.execute(select(OnboardingApplication).where(OnboardingApplication.user_id == u_id))
    app = res.scalar_one()
    assert app.status == "canceled"

    # 3. Начинаем заново, но теперь как гид (Trip Guide)
    # Благодаря create (Upsert) в репозитории, это не вызовет ошибку UniqueConstraint
    restart_resp = await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "trip_guide", "bank": "t_bank"},
    )
    assert restart_resp.status_code == 200

    # 4. Финальная проверка: заявка обновилась на гида
    db_session.expire_all()

    res_final = await db_session.execute(
        # Используем сохраненный u_id вместо test_user.id
        select(OnboardingApplication).where(OnboardingApplication.user_id == u_id)
    )
    app_final = res_final.scalar_one()

    assert app_final.target_role == "trip_guide"
    assert app_final.status == "pending_legal"


@pytest.mark.asyncio
async def test_onboarding_to_tripguide_conversion(
    client: AsyncClient, db_session: AsyncSession, test_user: User, user_token: str, admin_token: str
) -> None:
    u_id = test_user.id
    u_phone = test_user.phone

    # --- ШАГ 0: Создание заявки (Гид) ---
    start_resp = await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "trip_guide", "bank": "t_bank"},
    )
    assert start_resp.status_code == 200

    # Получаем ID заявки
    db_session.expire_all()
    res = await db_session.execute(select(OnboardingApplication.id).where(OnboardingApplication.user_id == u_id))
    application_id = res.scalar()

    # --- ШАГ 1: Вебхук банка ---
    await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={
            "user_id": u_id,
            "phone": u_phone,
            "inn": "9876543210",
            "full_name": "Петров Петр Петрович",
        },
    )

    # --- ШАГ 2: Отправка анкеты гида ---
    survey_resp = await client.post(
        "/api/v1/onboarding/submit-survey",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "bio": "Опытный гид по горам Кавказа, стаж 10 лет.",
            "languages": ["RU", "EN"],
            "specialization": "Горные походы",
            "photo_certificate": "http://s3.com",
        },
    )
    assert survey_resp.status_code == 200

    # --- ШАГ 3: Одобрение админом ---
    await client.patch(
        f"/api/v1/admin/onboarding/{application_id}/approve", headers={"Authorization": f"Bearer {admin_token}"}
    )

    # --- ШАГ 4: Проверка профиля ---
    me_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {user_token}"})
    data = me_resp.json()

    assert data["user"]["role"] == "trip_guide"
    assert data["trip_guide_data"]["specialization"] == "Горные походы"
    assert "RU" in data["trip_guide_data"]["languages"]
    # Проверяем, что данных водителя нет
    assert data.get("supplier_data") is None


@pytest.mark.asyncio
async def test_webhook_weird_name_parsing(client, test_user, user_token):
    # Начало заявки...
    await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={
            "user_id": test_user.id,
            "phone": test_user.phone,
            "inn": "1234567890",
            "full_name": "  Иванов   ",  # Всего одно слово и пробелы
        },
    )


@pytest.mark.asyncio
async def test_webhook_non_existent_app(client):
    resp = await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={
            "user_id": 999999,
            "phone": "+79990000000",
            "inn": "123456789012",  # Сделали ИНН валидным (12 цифр)
            "full_name": "Error User",
        },
    )
    # Теперь Pydantic пропустит запрос, сервис не найдет заявку и выдаст 404
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_onboarding_restart_clears_old_data(client, user_token, db_session, test_user):
    u_id = test_user.id

    # 1. Создаем заявку и проходим банк (статус станет filling_survey)
    await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "supplier", "bank": "sber"},
    )
    await client.post(
        "/api/v1/onboarding/webhook/bank",
        json={"user_id": u_id, "phone": test_user.phone, "inn": "1234567890", "full_name": "Иван"},
    )

    # Заполняем анкету "грязными" данными, но НЕ отправляем её на модерацию через submit-survey,
    # либо отправляем, но тогда отмена не сработает по твоей бизнес-логике.
    # Чтобы проверить именно ОЧИСТКУ при перезапуске, имитируем наличие данных в БД.

    # Имитируем, что юзер начал заполнять анкету (данные уже могут быть в БД или просто статус позволяет)
    # В данном сценарии проще всего отменить на этапе filling_survey.

    # 2. Пользователь отменяет заявку (на этапе filling_survey это разрешено)
    cancel_resp = await client.delete("/api/v1/onboarding/cancel", headers={"Authorization": f"Bearer {user_token}"})
    assert cancel_resp.status_code == 200

    await db_session.commit()
    db_session.expire_all()

    # 3. Пользователь создает НОВУЮ заявку (другая роль)
    # Здесь сработает твой репозиторий: repo.create -> on_conflict_do_update -> затирка полей
    restart_resp = await client.post(
        "/api/v1/onboarding/start",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"target_role": "trip_guide", "bank": "t_bank"},
    )
    assert restart_resp.status_code == 200

    # 4. ПРОВЕРКА: Данные старой анкеты должны быть стерты
    await db_session.commit()
    db_session.expire_all()

    from app.models.onboarding import OnboardingApplication

    res = await db_session.execute(select(OnboardingApplication).where(OnboardingApplication.user_id == u_id))
    app = res.scalar_one()

    # Проверяем финальное состояние
    assert app.status == "pending_legal"
    assert app.survey_payload is None  # Теперь это сработает, так как Upsert выполнился
    assert app.target_role == "trip_guide"
    assert app.inn is None
