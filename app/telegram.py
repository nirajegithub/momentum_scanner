from __future__ import annotations

import html
import os

import requests

from .config import DISCLAIMER, SETTINGS


def send(text, parse_mode=None):
    full = text.rstrip() + "\n\n" + DISCLAIMER
    if SETTINGS.dry_run:
        print(full)
        return True

    payload = {
        "chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "text": full,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    if not r.json().get("ok", True):
        raise RuntimeError("Telegram API returned failure")
    return True


def _money(value):
    return f"₹{float(value):,.2f}"


def _esc(value):
    return html.escape(str(value), quote=False)


def _time(value):
    return str(value).replace("+05:30", " IST")


def signal_message(s):
    buy = s["direction"] == "BUY"
    header = "🚀 BUY ALERT" if buy else "🔻 SELL ALERT"
    relation = "above" if buy else "below"
    return "\n".join([
        f"<b>{header}</b>",
        "",
        f"<b>{_esc(s['symbol'])}</b>",
        "",
        "📊 <b>Strategy:</b> B1 ORB + RVOL",
        "",
        "🕘 <b>09:15 ORB</b>",
        f"Time: {_esc(_time(s['orb_timestamp']))}",
        f"High: <b>{_money(s['orb_high'])}</b>",
        f"Low: <b>{_money(s['orb_low'])}</b>",
        f"Close: <b>{_money(s['orb_close'])}</b>",
        "",
        "🧱 <b>15M QUALITY SETUP</b>",
        f"Candle: {_esc(_time(s['setup_15m_timestamp']))}",
        f"15M Close: <b>{_money(s['setup_15m_close'])}</b>",
        f"RSI: <b>{float(s['setup_15m_rsi14']):.2f}</b>",
        f"RVOL: <b>{float(s['setup_15m_rvol']):.2f}x</b>",
        f"Quality: <b>{float(s['trade_quality_score']):.1f} / 7</b>",
        "",
        "✅ <b>5M CONFIRMATION</b>",
        f"Time: {_esc(_time(s['confirmation_5m_timestamp']))}",
        f"5M Close: <b>{_money(s['confirmation_5m_close'])}</b>",
        f"Rule: completed 5M close {relation} stored 15M {'HIGH' if buy else 'LOW'}",
        "",
        "💰 <b>TRADE</b>",
        f"Entry: <b>{_money(s['risk']['entry'])}</b>",
        f"SL: <b>{_money(s['risk']['sl'])}</b>",
        f"Risk: <b>{_money(s['risk']['risk'])}</b>",
        "",
        "🎯 <b>TARGETS</b>",
        f"T1 (2R): <b>{_money(s['risk']['t1'])}</b>",
        f"T2 (3R): <b>{_money(s['risk']['t2'])}</b>",
        f"T3 (4R): <b>{_money(s['risk']['t3'])}</b>",
    ])


def stop_update_message(s, new_stop, stage, basis):
    return "\n".join([
        "🔒 <b>STOP UPDATE</b>", "",
        f"<b>{_esc(s['symbol'])}</b>",
        f"New SL: <b>{_money(new_stop)}</b>",
        f"Status: {_esc(basis)}",
    ])


def exit_message(s, exit_price, reason, exit_time):
    entry = float(s["risk"]["entry"])
    points = float(exit_price) - entry if s["direction"] == "BUY" else entry - float(exit_price)
    return "\n".join([
        f"⚠️ <b>{_esc(s['symbol'])} {_esc(reason)}</b>",
        f"Points: <b>{points:+.2f}</b>",
        f"Entry: <b>{_money(entry)}</b>",
        f"Exit: <b>{_money(exit_price)}</b>",
        f"Time: {_esc(_time(exit_time))}",
    ])
