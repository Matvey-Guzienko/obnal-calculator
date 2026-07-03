from database import get_payments, get_transactions


def format_number(num: float) -> str:
    formatted = f"{num:,.2f}"
    if formatted.endswith(".00"):
        formatted = formatted[:-3]
    return formatted


async def generate_report(chat_id: int) -> str:
    transactions = await get_transactions(chat_id)
    payments = await get_payments(chat_id)

    trans_by_user: dict[str, list[str]] = {}
    total_rub_by_user: dict[str, float] = {}
    total_usdt_by_user: dict[str, float] = {}
    for t in transactions:
        u = t.username
        time_str = t.timestamp.strftime("%H:%M")
        trans_by_user.setdefault(u, []).append(
            f"<code>{time_str}</code> {format_number(t.amount_rub)}-{t.percent}%"
            f"={format_number(t.amount_after_percent)}/{t.course} "
            f"=<b>{t.amount_usdt:.2f}USDT</b> {u}"
        )
        total_rub_by_user[u] = total_rub_by_user.get(u, 0.0) + t.amount_rub
        total_usdt_by_user[u] = total_usdt_by_user.get(u, 0.0) + t.amount_usdt

    pay_by_user: dict[str, list[str]] = {}
    paid_usdt_by_user: dict[str, float] = {}
    for p in payments:
        u = p.username
        time_str = p.timestamp.strftime("%H:%M")
        pay_by_user.setdefault(u, []).append(
            f"<code>{time_str}</code> <b>{p.amount_usdt:.2f}</b> "
            f"({format_number(p.amount_rub)}) {u}"
        )
        paid_usdt_by_user[u] = paid_usdt_by_user.get(u, 0.0) + p.amount_usdt

    all_users = set(trans_by_user) | set(pay_by_user)
    if not all_users:
        return "<i>нет данных</i>"

    report_parts = []
    compact_parts = []
    for username in sorted(all_users):
        user_trans = trans_by_user.get(username, [])
        user_pays = pay_by_user.get(username, [])

        trans_text = "\n".join(user_trans) if user_trans else "<i>нет транзакций</i>"
        pay_text = "\n".join(user_pays) if user_pays else "<i>нет выплат</i>"

        total_rub = total_rub_by_user.get(username, 0.0)
        total_usdt = total_usdt_by_user.get(username, 0.0)
        paid_usdt = paid_usdt_by_user.get(username, 0.0)
        need_to_pay = total_usdt - paid_usdt

        totals_text = (
            f"🧾 Сумма пополнений {username}: <b>{format_number(total_rub)}</b>\n"
            f"💰 Общая сумма {username}: <b>{format_number(total_usdt)} USDT</b>\n"
            f"✅ Выплачено {username}: <b>{format_number(paid_usdt)} USDT</b>\n"
            f"⏳ Нужно выплатить {username}: <b>{format_number(need_to_pay)} USDT</b>"
        )

        report_parts.append(
            f"📊 <b>Количество транзакций {username}:</b> ({len(user_trans)})\n"
            f"<blockquote expandable>{trans_text}</blockquote>\n"
            f"💸 <b>PAY {username}:</b> ({len(user_pays)})\n"
            f"<blockquote expandable>{pay_text}</blockquote>\n"
            f"{totals_text}"
        )
        compact_parts.append(
            f"📊 <b>Количество транзакций {username}:</b> ({len(user_trans)})\n"
            f"💸 <b>PAY {username}:</b> ({len(user_pays)})\n"
            f"{totals_text}"
        )

    separator = "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    report = separator.join(report_parts)
    if len(report) > 3800:
        report = separator.join(compact_parts)
    return report
