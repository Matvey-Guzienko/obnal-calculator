import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database import close_db, init_db
from handlers import register_handlers
from scheduler import build_scheduler, check_all_pinned_reports, run_daily_resets


async def main() -> None:
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    register_handlers(dp)

    await run_daily_resets(bot)
    await check_all_pinned_reports(bot)

    scheduler = build_scheduler(bot)
    scheduler.start()

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN is not set")
        sys.exit(1)
    asyncio.run(main())
