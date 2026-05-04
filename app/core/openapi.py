from enum import StrEnum


class RouteTag(StrEnum):
    AUTH = "Авторизация"
    USERS = "Профиль пользователя"
    ADMIN = "Управление доступом"


tags_metadata = [
    {
        "name": RouteTag.AUTH,
        "description": "Вход по OTP, управление сессиями и конфигурация приложения.",
    },
    {
        "name": RouteTag.USERS,
        "description": "Личные данные пользователя, смена никнейма и загрузка аватарок.",
    },
    {
        "name": RouteTag.ADMIN,
        "description": "Админ-панель для управления ролями и блокировками пользователей.",
    },
]
