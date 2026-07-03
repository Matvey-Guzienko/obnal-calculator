from os import getenv
from pathlib import Path

import pytz

BOT_TOKEN = getenv("BOT_TOKEN") or ""
TELEGRAM_API_URL = getenv("TELEGRAM_API_URL") or ""

DB_PATH = "data/data.db"
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

DAILY_REPORT_HOUR = 7
DAILY_REPORT_MINUTE = 0
