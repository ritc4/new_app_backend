FROM python:3.12-slim AS builder

# Устанавливаем uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Устанавливаем системные зависимости для сборки C-расширений
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей
# ВАЖНО: Копируем только их, чтобы кешировать установку библиотек
COPY pyproject.toml uv.lock ./

# Синхронизируем зависимости. 
# --no-install-project говорит uv не искать исходный код нашего приложения на этом этапе.
RUN uv sync --frozen --no-dev --no-install-project

# Этап 2: Финальный образ
FROM python:3.12-slim

WORKDIR /app

# Копируем виртуальное окружение из builder
COPY --from=builder /app/.venv /app/.venv
# Добавляем его в PATH
ENV PATH="/app/.venv/bin:$PATH"

# Копируем исходный код проекта
COPY . .

# Окружение
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Добавляем PYTHONPATH, чтобы Python видел папку app как модуль
ENV PYTHONPATH=/app

EXPOSE 8000

# Запускаем через путь в окружении
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]