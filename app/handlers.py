import re

from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from database import (
    add_payment,
    add_transaction,
    delete_last_payment,
    delete_last_transaction,
    get_course,
    set_course,
)
from report import format_number
from scheduler import refresh_pinned_report

HELP_TEXT = """<b>Доступные команды:</b>

/help - Показать это сообщение
/course (курс) (процент) (метка) - Установить курс
/pay (сумма USDT) (метка) - Записать выплату
/unpay (сумма USDT) (метка) - Отменить последнюю выплату

<b>Быстрые команды:</b>
+сумма метка - Добавить транзакцию (например: +5000 Пуг)
-сумма метка - Удалить последнюю транзакцию (например: -5000 Пуг)

<b>Примеры:</b>
/course 86.5 20 Пуг
/pay 465.12 Пуг
/unpay 465.12 Пуг
+5000 Пуг
-5000 Пуг"""

TRANSACTION_RE = re.compile(r"^\+(\d+(?:[.,]\d+)?)\s+(.+)$")
DELETE_TRANSACTION_RE = re.compile(r"^-(\d+(?:[.,]\d+)?)\s+(.+)$")


def register_handlers(dp: Dispatcher) -> None:
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_course, Command("course"))
    dp.message.register(cmd_pay, Command("pay"))
    dp.message.register(cmd_unpay, Command("unpay"))
    dp.message.register(handle_transaction, F.text.regexp(TRANSACTION_RE))
    dp.message.register(handle_delete_transaction, F.text.regexp(DELETE_TRANSACTION_RE))


async def cmd_help(message: Message) -> None:
    await message.reply(HELP_TEXT)


async def cmd_course(message: Message) -> None:
    if not message.text:
        return

    args = message.text.split(maxsplit=3)[1:]
    if len(args) != 3:
        await message.reply(
            "Использование: /course (курс) (процент) (метка)\nПример: /course 86.5 20 Пуг"
        )
        return

    try:
        course = float(args[0].replace(",", "."))
        percent = int(args[1])
        username = args[2].strip()
    except ValueError:
        await message.reply("Некорректный формат данных")
        return

    if course <= 0 or percent < 0 or percent > 100:
        await message.reply("Некорректные значения")
        return

    await set_course(message.chat.id, course, percent, username)
    await message.reply(
        f"Курс установлен для {username}: {course} рублей за доллар, процент: {percent}%"
    )


async def cmd_pay(message: Message) -> None:
    if not message.text:
        return

    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply(
            "Использование: /pay (сумма в USDT) (метка)\nПример: /pay 465.12 Пуг"
        )
        return

    try:
        amount_usdt = float(args[0].replace(",", "."))
    except ValueError:
        await message.reply("Некорректный формат суммы")
        return

    username = args[1].strip()

    if amount_usdt == 0:
        await message.reply("Сумма должна быть ненулевой")
        return

    course_data = await get_course(message.chat.id, username)
    if not course_data:
        await message.reply(f"Курс для {username} не установлен. Используйте /course")
        return

    course, _percent = course_data
    amount_rub = await add_payment(message.chat.id, amount_usdt, course, username)

    await message.reply(
        f"Платеж записан: {amount_usdt:.2f} USDT ({format_number(amount_rub)} руб) {username}"
    )
    await refresh_pinned_report(message.bot, message.chat.id)


async def cmd_unpay(message: Message) -> None:
    if not message.text:
        return

    args = message.text.split(maxsplit=2)[1:]
    if len(args) < 2:
        await message.reply(
            "Использование: /unpay (сумма в USDT) (метка)\nПример: /unpay 465.12 Пуг"
        )
        return

    try:
        amount_usdt = float(args[0].replace(",", "."))
    except ValueError:
        await message.reply("Некорректный формат суммы")
        return

    username = args[1].strip()

    if amount_usdt <= 0:
        await message.reply("Сумма должна быть положительной")
        return

    if await delete_last_payment(message.chat.id, amount_usdt, username):
        await message.reply(f"Платеж {amount_usdt:.2f} USDT ({username}) удален")
        await refresh_pinned_report(message.bot, message.chat.id)
    else:
        await message.reply(f"Платеж {amount_usdt:.2f} USDT ({username}) не найден")


async def handle_transaction(message: Message) -> None:
    if not message.text:
        return

    match = TRANSACTION_RE.match(message.text)
    if not match:
        await message.reply("Использование: +сумма метка\nПример: +5000 Пуг")
        return

    amount_rub = float(match.group(1).replace(",", "."))
    username = match.group(2).strip()

    if amount_rub <= 0:
        await message.reply("Сумма должна быть положительной")
        return

    course_data = await get_course(message.chat.id, username)
    if not course_data:
        await message.reply(f"Курс для {username} не установлен. Используйте /course")
        return

    course, percent = course_data
    amount_after_percent, amount_usdt = await add_transaction(
        message.chat.id, amount_rub, percent, course, username
    )

    await message.reply(
        f"Транзакция записана:\n"
        f"{format_number(amount_rub)}-{percent}% = {format_number(amount_after_percent)} / {course} = {amount_usdt:.2f} USDT"
    )
    await refresh_pinned_report(message.bot, message.chat.id)


async def handle_delete_transaction(message: Message) -> None:
    if not message.text:
        return

    match = DELETE_TRANSACTION_RE.match(message.text)
    if not match:
        await message.reply("Использование: -сумма метка\nПример: -5000 Пуг")
        return

    amount_rub = float(match.group(1).replace(",", "."))
    username = match.group(2).strip()

    if await delete_last_transaction(message.chat.id, amount_rub, username):
        await message.reply(
            f"Транзакция на {format_number(amount_rub)} ({username}) удалена"
        )
        await refresh_pinned_report(message.bot, message.chat.id)
    else:
        await message.reply(
            f"Транзакция на {format_number(amount_rub)} ({username}) не найдена"
        )
