import asyncio
import io
from datetime import date
from html import escape

from PIL import Image, ImageDraw, ImageFont

from config import FONTS_DIR
from database import current_ledger_date, get_courses, get_payments, get_transactions

BG = "#17212B"
CARD = "#232E3C"
DIVIDER = "#2B3A4C"
PRIMARY = "#F5F5F5"
SECONDARY = "#708499"
POSITIVE = "#4FAE4E"
NEGATIVE = "#E8A33D"

WIDTH = 900
MARGIN = 32
PAD = 24
LINE_H = 40
CARD_GAP = 24
MAX_HEIGHT = 8500


def format_number(num: float) -> str:
    formatted = f"{num:,.2f}"
    if formatted.endswith(".00"):
        formatted = formatted[:-3]
    return formatted


def render_report_image(ledger_date: date, cards: list[tuple]) -> bytes:
    font_title = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans-Bold.ttf"), 40)
    font_header = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans-Bold.ttf"), 30)
    font_body = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), 26)
    font_totals = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans-Bold.ttf"), 28)
    font_secondary = ImageFont.truetype(str(FONTS_DIR / "DejaVuSans.ttf"), 24)

    title = f"Отчёт за {ledger_date.strftime('%d.%m.%Y')}"

    if not cards:
        image = Image.new("RGB", (WIDTH, 220), BG)
        draw = ImageDraw.Draw(image)
        draw.text((MARGIN, MARGIN), title, font=font_title, fill=PRIMARY)
        draw.text((WIDTH / 2, 155), "нет данных", font=font_header, fill=SECONDARY, anchor="mm")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    full_cards = cards
    height = MARGIN + 72 + sum(294 + (len(c[3]) + len(c[4])) * LINE_H + CARD_GAP for c in cards) - CARD_GAP + MARGIN
    for tx_limit, pay_limit in ((30, 10), (20, 7), (12, 5), (6, 3), (3, 2), (1, 1)):
        if height <= MAX_HEIGHT:
            break
        cards = [
            (
                u,
                course,
                percent,
                [("", f"… ещё {tx_count - tx_limit} транзакций ранее")] + tx[-tx_limit:] if tx_count > tx_limit + 1 else tx,
                [("", f"… ещё {pay_count - pay_limit} выплат ранее")] + pay[-pay_limit:] if pay_count > pay_limit + 1 else pay,
                tx_count,
                pay_count,
                *rest,
            )
            for u, course, percent, tx, pay, tx_count, pay_count, *rest in full_cards
        ]
        height = MARGIN + 72 + sum(294 + (len(c[3]) + len(c[4])) * LINE_H + CARD_GAP for c in cards) - CARD_GAP + MARGIN
    if height > MAX_HEIGHT:
        cards = [
            (
                u,
                course,
                percent,
                [("", f"Транзакций: {tx_count}")],
                [("", f"Выплат: {pay_count}")],
                tx_count,
                pay_count,
                *rest,
            )
            for u, course, percent, tx, pay, tx_count, pay_count, *rest in cards
        ]
        height = MARGIN + 72 + sum(294 + (len(c[3]) + len(c[4])) * LINE_H + CARD_GAP for c in cards) - CARD_GAP + MARGIN

    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, MARGIN), title, font=font_title, fill=PRIMARY)

    y = MARGIN + 72
    for username, course, percent, tx_lines, pay_lines, _, _, total_rub, total_usdt, paid_usdt, need_to_pay in cards:
        lines = tx_lines + pay_lines
        card_h = 294 + len(lines) * LINE_H
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + card_h), radius=18, fill=CARD)

        left = MARGIN + PAD
        right = WIDTH - MARGIN - PAD
        cursor = y + PAD

        draw.text((left, cursor), username, font=font_header, fill=PRIMARY)
        draw.text(
            (left + draw.textlength(username, font=font_header) + 20, cursor + 6),
            f"курс {course:g} / {percent}%",
            font=font_secondary,
            fill=SECONDARY,
        )
        cursor += 46
        draw.line((left, cursor + 10, right, cursor + 10), fill=DIVIDER, width=2)
        cursor += 20

        for time_str, body in lines:
            if time_str:
                draw.text((left, cursor + 2), time_str, font=font_secondary, fill=SECONDARY)
                draw.text((left + 96, cursor), body, font=font_body, fill=PRIMARY)
            else:
                draw.text((left, cursor), body, font=font_body, fill=SECONDARY)
            cursor += LINE_H

        draw.line((left, cursor + 10, right, cursor + 10), fill=DIVIDER, width=2)
        cursor += 20

        for label, value, font, color in (
            ("Пополнения", f"{format_number(total_rub)} ₽", font_body, PRIMARY),
            ("Итого", f"{format_number(total_usdt)} USDT", font_body, PRIMARY),
            ("Выплачено", f"{format_number(paid_usdt)} USDT", font_body, PRIMARY),
            ("К выплате", f"{format_number(need_to_pay)} USDT", font_totals, POSITIVE if need_to_pay >= 0 else NEGATIVE),
        ):
            draw.text((left, cursor + 2), label, font=font_secondary, fill=SECONDARY)
            draw.text((right, cursor), value, font=font, fill=color, anchor="ra")
            cursor += LINE_H

        y += card_h + CARD_GAP

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def generate_report_photo(chat_id: int) -> tuple[bytes, str]:
    transactions = await get_transactions(chat_id)
    payments = await get_payments(chat_id)
    courses = await get_courses(chat_id)

    tx_by_user: dict[str, list[tuple[str, str]]] = {}
    pay_by_user: dict[str, list[tuple[str, str]]] = {}
    total_rub_by_user: dict[str, float] = {}
    total_usdt_by_user: dict[str, float] = {}
    paid_usdt_by_user: dict[str, float] = {}
    last_setting: dict[str, tuple[float, int]] = {}

    for t in transactions:
        u = t.username
        tx_by_user.setdefault(u, []).append(
            (t.timestamp.strftime("%H:%M"), f"+{format_number(t.amount_rub)} ₽ → {t.amount_usdt:.2f} USDT")
        )
        total_rub_by_user[u] = total_rub_by_user.get(u, 0.0) + t.amount_rub
        total_usdt_by_user[u] = total_usdt_by_user.get(u, 0.0) + t.amount_usdt
        last_setting[u] = (t.course, t.percent)

    for p in payments:
        u = p.username
        pay_by_user.setdefault(u, []).append(
            (p.timestamp.strftime("%H:%M"), f"выплата {p.amount_usdt:.2f} USDT ({format_number(p.amount_rub)} ₽)")
        )
        paid_usdt_by_user[u] = paid_usdt_by_user.get(u, 0.0) + p.amount_usdt
        if u not in last_setting:
            last_setting[u] = (p.course, 0)

    ledger_date = current_ledger_date()
    date_str = ledger_date.strftime("%d.%m.%Y")

    cards = []
    caption_lines = [f"<b>Отчёт за {date_str}</b>"]
    for username in sorted(set(tx_by_user) | set(pay_by_user)):
        course, percent = courses.get(username) or last_setting.get(username) or (0.0, 0)
        tx_lines = tx_by_user.get(username, [])
        pay_lines = pay_by_user.get(username, [])
        need_to_pay = total_usdt_by_user.get(username, 0.0) - paid_usdt_by_user.get(username, 0.0)
        cards.append(
            (
                username,
                course,
                percent,
                tx_lines,
                pay_lines,
                len(tx_lines),
                len(pay_lines),
                total_rub_by_user.get(username, 0.0),
                total_usdt_by_user.get(username, 0.0),
                paid_usdt_by_user.get(username, 0.0),
                need_to_pay,
            )
        )
        caption_lines.append(f"⏳ {escape(username)}: <b>{format_number(need_to_pay)} USDT</b>")

    png = await asyncio.to_thread(render_report_image, ledger_date, cards)

    if not cards:
        return png, f"<b>Отчёт за {date_str}</b>\n<i>нет данных</i>"

    caption = "\n".join(caption_lines)
    while len(caption) > 1024 and len(caption_lines) > 1:
        caption_lines.pop()
        caption = "\n".join(caption_lines) + "\n…"
    return png, caption
