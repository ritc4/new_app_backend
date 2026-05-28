from celery import Celery
from celery.schedules import crontab  # Импортируем для точного времени

from app.config.settings import settings

CELERY_TASKS = [
    "app.workers.auth.tasks",
    "app.workers.users.tasks",
    "app.workers.onboarding.tasks",
    "app.workers.transfers.tasks",
    "app.workers.excursions.tasks",
    "app.workers.payments.tasks",
]

celery_app = Celery(
    settings.celery.name,
    broker=settings.rabbitmq.url,
    include=CELERY_TASKS,
)

celery_app.conf.update(
    timezone=settings.celery.timezone,
    task_acks_late=settings.celery.task_acks_late,
    # --- ENTERPRISE SETTINGS ---
    # Переподключение при старте, если брокер недоступен
    broker_connection_retry_on_startup=True,
    # Ограничение: сколько задач воркер берет за раз (1 = по одной).
    # Защищает от ситуации, когда один воркер захапал все тяжелые задачи.
    worker_prefetch_multiplier=1,
)

# Разделение по очередям
celery_app.conf.task_routes = {
    "send_flash_call": {"queue": "critical"},
    "generate_payment_link_task": {"queue": "critical"},
    "generate_excursion_payment_link_task": {"queue": "critical"},
    "process_bank_refund_task": {"queue": "maintenance"},
    "delete_user_s3_resources_task": {"queue": "maintenance"},
    "cleanup_inactive_users_task": {"queue": "maintenance"},
    "cleanup_expired_onboarding_task": {"queue": "maintenance"},
}

# Расписание
celery_app.conf.beat_schedule = {
    "cleanup-onboarding-nightly": {
        "task": "cleanup_expired_onboarding_task",
        "schedule": crontab(hour=2, minute=0),  # Каждую ночь в 2:00
    },
    "cleanup-users-nightly": {
        "task": "cleanup_inactive_users_task",
        "schedule": crontab(hour=3, minute=0),  # Каждую ночь в 3:00
    },
}
