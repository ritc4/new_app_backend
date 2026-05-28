from enum import StrEnum


class RouteTag(StrEnum):
    AUTH = "Авторизация"
    USERS = "Профиль пользователя"
    ADMIN = "Управление доступом"
    ONBOARDING = "Регистрация партнеров"
    TRANSFERS = "Трансферы"
    PAYMENTS = "Оплата"
    SUPPLIERS = "Кабинет Водителя (Биржа трансферов)"
    REVIEWS = "Универсальная система отзывов"
    EXCURSIONS = "Биржа экскурсий"
    GUIDE = "Кабинет Гида"


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
    {
        "name": RouteTag.ONBOARDING,
        "description": "Регистрация  партнеров (водителей/гидов).",
    },
    {
        "name": RouteTag.TRANSFERS,
        "description": "Трансферы.",
    },
    {
        "name": RouteTag.PAYMENTS,
        "description": "Оплата.",
    },
    {
        "name": RouteTag.SUPPLIERS,
        "description": "Кабинет Водителя (Биржа трансферов).",
    },
    {
        "name": RouteTag.REVIEWS,
        "description": "Универсальная система отзывов.",
    },
    {
        "name": RouteTag.EXCURSIONS,
        "description": "Биржа экскурсий.",
    },
    {
        "name": RouteTag.GUIDE,
        "description": "Кабинет Гида.",
    },
]
