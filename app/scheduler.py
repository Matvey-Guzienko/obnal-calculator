import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramMigrateToChat
from aiogram.types import BufferedInputFile, InputMediaDocument
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, MOSCOW_TZ
from database import (
    clear_daily_history,
    current_ledger_date,
    delete_chat_data,
    get_known_chat_ids,
    get_last_daily_message_id,
    get_last_reset_date,
    get_today_message,
    migrate_chat,
    save_daily_message,
    set_last_reset_date,
)
from report import generate_report_photo

logger = logging.getLogger(__name__)

_refresh_tasks: dict[int, asyncio.Task] = {}


async def send_daily_report(
    bot: Bot, chat_id: int, media: tuple[bytes, str] | None = None
) -> None:
    if media is None:
        media = await generate_report_photo(chat_id)

    old_message_id = await get_last_daily_message_id(chat_id)
    if old_message_id:
        try:
            await bot.unpin_chat_message(chat_id=chat_id, message_id=old_message_id)
        except Exception:
            pass

    try:
        message = await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(media[0], filename="report.png"),
            caption=media[1],
        )
    except TelegramMigrateToChat as e:
        await migrate_chat(chat_id, e.migrate_to_chat_id)
        await send_daily_report(bot, e.migrate_to_chat_id, media=media)
        return
    except TelegramBadRequest as e:
        if "chat not found" in str(e).lower():
            await delete_chat_data(chat_id)
            return
        raise

    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message.message_id)
    except Exception:
        pass

    await save_daily_message(chat_id, message.message_id)


async def check_and_pin_report(bot: Bot, chat_id: int) -> None:
    message_id = await get_today_message(chat_id)
    if message_id:
        try:
            chat = await bot.get_chat(chat_id)
        except TelegramMigrateToChat as e:
            await migrate_chat(chat_id, e.migrate_to_chat_id)
            return
        except TelegramBadRequest as e:
            if "chat not found" in str(e).lower():
                await delete_chat_data(chat_id)
            return
        except Exception:
            return
        if chat.pinned_message and chat.pinned_message.message_id == message_id:
            return

    await send_daily_report(bot, chat_id)


async def refresh_pinned_report(bot: Bot, chat_id: int) -> None:
    task = _refresh_tasks.pop(chat_id, None)
    if task:
        task.cancel()
    _refresh_tasks[chat_id] = asyncio.create_task(_refresh_after_delay(bot, chat_id))


async def _refresh_after_delay(bot: Bot, chat_id: int) -> None:
    await asyncio.sleep(3)
    _refresh_tasks.pop(chat_id, None)

    media = await generate_report_photo(chat_id)
    message_id = await get_today_message(chat_id)

    if not message_id:
        await send_daily_report(bot, chat_id, media=media)
        return

    needs_resend = False
    try:
        chat = await bot.get_chat(chat_id)
        needs_resend = not (
            chat.pinned_message and chat.pinned_message.message_id == message_id
        )
    except Exception:
        pass

    if needs_resend:
        await send_daily_report(bot, chat_id, media=media)
        return

    try:
        await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=InputMediaDocument(
                media=BufferedInputFile(media[0], filename="report.png"),
                caption=media[1],
                parse_mode=ParseMode.HTML,
            ),
        )
    except TelegramMigrateToChat as e:
        await migrate_chat(chat_id, e.migrate_to_chat_id)
        await send_daily_report(bot, e.migrate_to_chat_id, media=media)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            await send_daily_report(bot, chat_id, media=media)
    except Exception:
        pass


async def run_daily_resets(bot: Bot) -> None:
    ledger_date = current_ledger_date()
    for chat_id in await get_known_chat_ids():
        try:
            last_reset = await get_last_reset_date(chat_id)
            if last_reset is None:
                await set_last_reset_date(chat_id, ledger_date)
                continue
            if last_reset >= ledger_date:
                continue
            await clear_daily_history(chat_id)
            await set_last_reset_date(chat_id, ledger_date)
            await send_daily_report(bot, chat_id)
        except Exception:
            logger.exception("Daily reset failed for chat %s", chat_id)


async def check_all_pinned_reports(bot: Bot) -> None:
    for chat_id in await get_known_chat_ids():
        try:
            await check_and_pin_report(bot, chat_id)
        except Exception:
            logger.exception("Pin check failed for chat %s", chat_id)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
    scheduler.add_job(
        run_daily_resets,
        trigger=CronTrigger(
            hour=DAILY_REPORT_HOUR,
            minute=DAILY_REPORT_MINUTE,
            timezone=MOSCOW_TZ,
        ),
        id="daily_report",
        kwargs={"bot": bot},
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        run_daily_resets,
        trigger=IntervalTrigger(minutes=30),
        id="daily_reset_catchup",
        kwargs={"bot": bot},
        misfire_grace_time=None,
        coalesce=True,
    )
    return scheduler
