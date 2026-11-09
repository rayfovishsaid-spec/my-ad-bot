import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import setup_routers
from bot.middlewares import UserContextMiddleware
from bot.workers import (
    broadcast_queue_worker,
    public_feed_announcer_worker,
    unsubscribe_guard_worker,
)
from core.config import get_env_config
from core.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("adpartner.bot")


async def run_telegram_bot(bot_token: str) -> None:
    await init_db(seed_demo=False)
    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(UserContextMiddleware())
    dp.callback_query.middleware(UserContextMiddleware())
    dp.include_router(setup_routers())

    me = await bot.get_me()
    if me.username:
        os.environ["BOT_USERNAME"] = me.username
    logger.info("🚀 Telegram-бот @%s (ID %s) успешно запущен!", me.username, me.id)

    bg_tasks = [
        asyncio.create_task(unsubscribe_guard_worker(bot)),
        asyncio.create_task(broadcast_queue_worker(bot)),
        asyncio.create_task(public_feed_announcer_worker(bot)),
    ]
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        for t in bg_tasks:
            t.cancel()
        await bot.session.close()


async def main() -> None:
    cfg = get_env_config()
    if not cfg["bot_token"]:
        logger.error(
            "❌ Не найден токен бота (BOT_TOKEN / TELEGRAM_BOT_TOKEN)! "
            "Укажите токен от @BotFather в настройках хостинга (или в .env) и перезапустите."
        )
        return
    await run_telegram_bot(cfg["bot_token"])


if __name__ == "__main__":
    asyncio.run(main())
