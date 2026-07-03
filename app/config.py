from os import getenv

import pytz

BOT_TOKEN = getenv("BOT_TOKEN") or ""

DB_PATH = "data/data.db"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

DAILY_REPORT_HOUR = 7
DAILY_REPORT_MINUTE = 0
