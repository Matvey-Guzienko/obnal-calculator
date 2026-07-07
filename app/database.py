import os
from datetime import date, datetime, timedelta
from typing import Optional

from config import DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, DB_PATH, MOSCOW_TZ
from tortoise import Tortoise, fields
from tortoise.models import Model


def _now_naive() -> datetime:
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None)


def current_ledger_date() -> date:
    day_start_offset = timedelta(hours=DAILY_REPORT_HOUR, minutes=DAILY_REPORT_MINUTE)
    return (_now_naive() - day_start_offset).date()


class Setting(Model):
    id = fields.IntField(primary_key=True)
    chat_id = fields.BigIntField()
    username = fields.CharField(max_length=255)
    course = fields.FloatField()
    percent = fields.IntField()

    class Meta:
        table = "settings"
        unique_together = (("chat_id", "username"),)
        indexes = (("chat_id", "username"),)


class Transaction(Model):
    id = fields.IntField(primary_key=True)
    chat_id = fields.BigIntField()
    timestamp = fields.DatetimeField()
    amount_rub = fields.FloatField()
    percent = fields.IntField()
    amount_after_percent = fields.FloatField()
    course = fields.FloatField()
    amount_usdt = fields.FloatField()
    username = fields.CharField(max_length=255)
    added_by = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "transactions"
        indexes = (("chat_id", "username"), ("chat_id", "id"))


class Payment(Model):
    id = fields.IntField(primary_key=True)
    chat_id = fields.BigIntField()
    timestamp = fields.DatetimeField()
    amount_usdt = fields.FloatField()
    amount_rub = fields.FloatField()
    course = fields.FloatField()
    username = fields.CharField(max_length=255)
    added_by = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "payments"
        indexes = (("chat_id", "username"), ("chat_id", "id"))


class DailyMessage(Model):
    id = fields.IntField(primary_key=True)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField()
    date = fields.DateField()

    class Meta:
        table = "daily_messages"
        indexes = (("chat_id", "date"),)


class ChatState(Model):
    id = fields.IntField(primary_key=True)
    chat_id = fields.BigIntField(unique=True)
    last_reset_date = fields.DateField()

    class Meta:
        table = "chat_states"


async def init_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    await Tortoise.init(
        db_url=f"sqlite://{DB_PATH}",
        modules={"models": ["database"]},
        use_tz=False,
        timezone="Europe/Moscow",
    )
    await Tortoise.generate_schemas(safe=True)


async def close_db() -> None:
    await Tortoise.close_connections()


async def set_course(chat_id: int, course: float, percent: int, username: str) -> None:
    await Setting.update_or_create(
        chat_id=chat_id,
        username=username.lower(),
        defaults={"course": course, "percent": percent},
    )


async def get_course(chat_id: int, username: str) -> Optional[tuple[float, int]]:
    row = await Setting.get_or_none(chat_id=chat_id, username=username.lower()).only(
        "course", "percent"
    )
    return (row.course, row.percent) if row else None


async def get_courses(chat_id: int) -> dict[str, tuple[float, int]]:
    rows = await Setting.filter(chat_id=chat_id).only("username", "course", "percent")
    return {row.username: (row.course, row.percent) for row in rows}


async def add_transaction(
    chat_id: int,
    amount_rub: float,
    percent: int,
    course: float,
    username: str,
    added_by: Optional[str] = None,
) -> tuple[float, float]:
    amount_after_percent = amount_rub * (1 - percent / 100)
    amount_usdt = amount_after_percent / course
    await Transaction.create(
        chat_id=chat_id,
        timestamp=_now_naive(),
        amount_rub=amount_rub,
        percent=percent,
        amount_after_percent=amount_after_percent,
        course=course,
        amount_usdt=amount_usdt,
        username=username.lower(),
        added_by=added_by,
    )
    return amount_after_percent, amount_usdt


async def add_payment(
    chat_id: int,
    amount_usdt: float,
    course: float,
    username: str,
    added_by: Optional[str] = None,
) -> float:
    amount_rub = amount_usdt * course
    await Payment.create(
        chat_id=chat_id,
        timestamp=_now_naive(),
        amount_usdt=amount_usdt,
        amount_rub=amount_rub,
        course=course,
        username=username.lower(),
        added_by=added_by,
    )
    return amount_rub


async def get_transactions(chat_id: int) -> list[Transaction]:
    return await Transaction.filter(chat_id=chat_id).order_by("id")


async def get_payments(chat_id: int) -> list[Payment]:
    return await Payment.filter(chat_id=chat_id).order_by("id")


async def save_daily_message(chat_id: int, message_id: int) -> None:
    await DailyMessage.update_or_create(
        chat_id=chat_id,
        date=current_ledger_date(),
        defaults={"message_id": message_id},
    )


async def get_today_message(chat_id: int) -> Optional[int]:
    row = (
        await DailyMessage.filter(chat_id=chat_id, date=current_ledger_date())
        .only("message_id")
        .order_by("-id")
        .first()
    )
    return row.message_id if row else None


async def get_last_daily_message_id(chat_id: int) -> Optional[int]:
    row = (
        await DailyMessage.filter(chat_id=chat_id)
        .only("message_id")
        .order_by("-id")
        .first()
    )
    return row.message_id if row else None


async def get_last_reset_date(chat_id: int) -> Optional[date]:
    row = await ChatState.get_or_none(chat_id=chat_id).only("last_reset_date")
    return row.last_reset_date if row else None


async def set_last_reset_date(chat_id: int, reset_date: date) -> None:
    await ChatState.update_or_create(
        chat_id=chat_id,
        defaults={"last_reset_date": reset_date},
    )


async def clear_daily_history(chat_id: int) -> None:
    await Transaction.filter(chat_id=chat_id).delete()
    await Payment.filter(chat_id=chat_id).delete()


async def delete_last_transaction(
    chat_id: int, amount_rub: float, username: str
) -> bool:
    row = (
        await Transaction.filter(
            chat_id=chat_id, amount_rub=amount_rub, username=username.lower()
        )
        .order_by("-id")
        .only("id")
        .first()
    )
    if row is None:
        return False
    await row.delete()
    return True


async def delete_last_payment(chat_id: int, amount_usdt: float, username: str) -> bool:
    row = (
        await Payment.filter(
            chat_id=chat_id, amount_usdt=amount_usdt, username=username.lower()
        )
        .order_by("-id")
        .only("id")
        .first()
    )
    if row is None:
        return False
    await row.delete()
    return True


async def migrate_chat(old_chat_id: int, new_chat_id: int) -> None:
    for model in (Setting, Transaction, Payment, DailyMessage, ChatState):
        await model.filter(chat_id=old_chat_id).update(chat_id=new_chat_id)


async def delete_chat_data(chat_id: int) -> None:
    for model in (Setting, Transaction, Payment, DailyMessage, ChatState):
        await model.filter(chat_id=chat_id).delete()


async def get_known_chat_ids() -> list[int]:
    ids: set[int] = set()
    for model in (Setting, Transaction, Payment, DailyMessage):
        rows = await model.all().distinct().values_list("chat_id", flat=True)
        ids.update(rows)
    return list(ids)
