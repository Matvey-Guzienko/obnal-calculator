# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies are managed with `uv` (see `pyproject.toml`, Python 3.12).

- Install / sync deps locally: `uv sync`
- Run the bot locally: `uv run app/main.py` (requires `.env` with `BOT_TOKEN` and a writable `data/` directory)
- Build & run in Docker: `docker compose up --build` (default deployment path — restart policy is `unless-stopped`, `./data` is bind-mounted for the SQLite file)
- Add a runtime dep: `uv add <pkg>` (then rebuild the image; `Dockerfile` re-exports `requirements.txt` from `uv.lock` at build time)

There is no test suite, linter, or formatter configured.

## Architecture

Single-process Telegram bot (`aiogram` v3) that acts as a per-user RUB→USDT settlement ledger. All I/O is async — Telegram via `aiogram`, DB via `tortoise-orm` on top of `aiosqlite`. Code lives in `app/`:

- `app/main.py` — entrypoint. Exits early with a logged error if `BOT_TOKEN` is empty. Runs `init_db()` (creates the DB directory if missing, opens Tortoise connection + `generate_schemas(safe=True)`), registers handlers, runs a startup catch-up reset (`run_daily_resets`) then a pin-check, starts the APScheduler jobs, then long-polls. `try/finally` around polling shuts down the scheduler, closes the bot session, and closes DB connections.
- `app/database.py` — Tortoise ORM models (`Setting`, `Transaction`, `Payment`, `DailyMessage`, `ChatState`) and async CRUD wrappers. Tables: `settings`, `transactions`, `payments`, `daily_messages`, `chat_states` at `data/data.db`. `settings` has `unique_together=("chat_id","username")`; `chat_states.chat_id` is unique. Also home of `current_ledger_date()` — the bot's "day" runs 07:00→07:00 Moscow, so this returns `now - 7h` as a date.
- `app/handlers.py` — `aiogram` command + regex handlers. Every DB call is awaited; regexes are pre-compiled at module scope. `+`/`-` amounts accept decimals with `.` or `,`; zero/negative `+` amounts are rejected.
- `app/report.py` — async report renderer. Fetches transactions + payments once and computes per-user totals in Python (no separate aggregation query). Builds both a full and a compact (no per-line lists) variant; if the full report exceeds ~3800 chars, the compact one is returned to stay under Telegram's 4096-char message limit.
- `app/scheduler.py` — daily-reset logic (`run_daily_resets`), `check_and_pin_report` / `refresh_pinned_report`, and `build_scheduler` (07:00 cron + 30-min catch-up interval job).
- `app/config.py` — `BOT_TOKEN`, `DB_PATH`, `MOSCOW_TZ`, daily-report hour/minute.

### Data flow / domain model

The bot tracks one running day of activity per user (the "метка" / label — case-insensitive, stored lowercase in the DB):

1. `/course <rate> <percent> <label>` sets a per-user conversion rate & commission. Written via `Setting.update_or_create` — no explicit `DELETE + INSERT`.
2. `+<amount> <label>` records a RUB transaction: `amount_after_percent = amount_rub * (1 - percent/100)`, `amount_usdt = amount_after_percent / course`. Historical rows keep their original `course`/`percent` — changing `/course` later does **not** rewrite past rows.
3. `/pay <usdt> <label>` records a payout in USDT; RUB is computed from the *current* `/course` rate for that user.
4. `-<amount> <label>` / `/unpay <usdt> <label>` delete the most recent matching row (matched by exact amount + label).

Totals per user (computed in `report.py` from the fetched rows, not via SQL): `total_rub = SUM(transactions.amount_rub)`, `total_usdt = SUM(transactions.amount_usdt)`, `paid_usdt = SUM(payments.amount_usdt)`, `need_to_pay = total_usdt - paid_usdt`.

### The daily-report lifecycle (important quirk)

The ledger day runs **07:00→07:00 Europe/Moscow** (`current_ledger_date()`), not calendar days. `run_daily_resets()` is **idempotent and marker-driven**: for each known chat it compares `chat_states.last_reset_date` to the current ledger date, and only if the marker is behind does it call `clear_daily_history()` (**wipes all rows from `transactions` and `payments`**), advance the marker, and re-send + re-pin the daily report. This wipe is intentional — the bot is a fresh daily ledger, not a historical archive. `settings`, `daily_messages`, and `chat_states` are preserved. Any feature that needs cross-day data would need a schema change.

`run_daily_resets()` fires from three places, all safe to overlap because of the marker: on startup (catches up a reset missed while the server was down at 07:00), a 07:00 cron job (`misfire_grace_time=3600`, `coalesce=True`), and a 30-minute interval job (catches process suspend/sleep across 07:00). A chat with no `chat_states` row just gets its marker initialized without a wipe — so a fresh deploy never nukes existing data.

The daily message is sent, pinned, and its `message_id` is stored in `daily_messages` keyed by `(chat_id, ledger date)` via `update_or_create`. On every write handler (`+`, `-`, `/pay`, `/unpay`) the bot re-renders the report and edits that pinned message in place (`refresh_pinned_report`). Failure handling there is deliberate: a `get_chat` error is treated as "still pinned" (edit anyway) to avoid duplicate-message spam on network blips; a `TelegramBadRequest` on edit other than "message is not modified" (e.g. the pinned message was deleted) triggers a re-send + re-pin. `check_and_pin_report()` (startup) re-sends & re-pins only when `get_chat` succeeds and shows a different pin, or when there is no stored message for the current ledger date. `send_daily_report()` unpins the **last stored daily message of any date** (so pins don't accumulate across days) and **does not** clear history — only `run_daily_resets` does. Remaining `unpin/pin/edit` errors are silently swallowed; per-chat job failures are logged via `logger.exception`.

Chat discovery is dynamic — `get_known_chat_ids()` unions distinct `chat_id`s across `settings`, `transactions`, `payments`, and `daily_messages`, so any chat that has ever had a `/course`, transaction, payment, or pinned report gets the daily job.

### Config & runtime

- `.env` (loaded by docker-compose or the environment): `BOT_TOKEN` only. There is no `TARGET_CHAT_ID` — chats are discovered from stored rows.
- Timezone is hardcoded to `Europe/Moscow` in `config.py` (`MOSCOW_TZ`) and passed to Tortoise's init (`timezone="Europe/Moscow"`, `use_tz=False`). Timestamps are stored via `DatetimeField` as naive Moscow-local values written by `_now_naive()`; the daily message's `date` and `chat_states.last_reset_date` are `DateField`s holding the **ledger date** (07:00-boundary), not the calendar date.
- Tortoise ORM v1.x bundles `aiosqlite` as a core dependency — do **not** use the `[aiosqlite]` extra in `pyproject.toml`, it doesn't exist.
- Schema evolution: `generate_schemas(safe=True)` only creates missing tables and never migrates existing ones. Model changes that touch existing columns need a manual migration (aerich or hand-written SQL) or a wiped `data/data.db`.
- Bot messages use `ParseMode.HTML` and are written in Russian — preserve the existing Russian UX text when editing handlers.
