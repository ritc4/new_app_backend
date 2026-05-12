from pydantic import BaseModel


class CeleryConfig(BaseModel):
    # Имя воркера
    name: str = "new_app"
    # Часовой пояс (важно для очистки базы в 3 утра)
    timezone: str = "UTC"
    # Нужно ли хранить результаты задач
    result_backend: str | None = None
    # Подтверждение задачи только после выполнения (защита от сбоев)
    task_acks_late: bool = True
