"""
Главный файл запуска Telegram-бота для хостинга (Bothost.ru и др.).
Потребляет ~45 МБ памяти и идеально работает на бесплатном тарифе Free.
"""
import asyncio
from bot_only import main

if __name__ == "__main__":
    asyncio.run(main())
