from datetime import timedelta

from celery import Celery

from app.config.settings import settings

# 1. Список всех модулей с задачами (явно, как в больших проектах)
CELERY_TASKS = [
    "app.workers.auth.tasks",
    # "app.workers.payments.tasks",  # новые модули будете просто дописывать сюда
]

celery_app = Celery(
    settings.celery.name,
    broker=settings.rabbitmq.url,
    include=CELERY_TASKS,
)

celery_app.conf.update(
    timezone=settings.celery.timezone,
    task_acks_late=settings.celery.task_acks_late,
)

# какая задача должна выполняться первой
celery_app.conf.task_routes = {
    # Имя задачи : название очереди
    "send_flash_call": {"queue": "critical"},
    "cleanup_inactive_users_task": {"queue": "maintenance"},
}

celery_app.conf.beat_schedule = {
    "cleanup-daily-at-night": {
        "task": "cleanup_inactive_users_task",
        "schedule": timedelta(hours=24),
    },
}
