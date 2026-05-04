# import asyncio
# from app.infra.db import engine, async_session_maker
# from app.infra.redis import redis_pool
# from app.services.user_service import UserService

# async def main():
#     # Создаем всё локально внутри ОДНОГО цикла событий
#     async with async_session_maker() as session:
#         # Инициализируем сервисы
#         service = UserService(db=session, ...) 
#         await service.perform_full_cleanup()
    
#     # Полная очистка ресурсов перед выходом
#     await engine.dispose()
#     await redis_pool.aclose()

# if __name__ == "__main__":
#     asyncio.run(main())