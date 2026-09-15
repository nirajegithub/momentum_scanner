from __future__ import annotations

import html
import os

import requests

from .config import DISCLAIMER


def send(text, parse_mode=None):
    full = text.rstrip() + "\n\n" + DISCLAIMER
    if os.getenv("DRY_RUN", "true").lower() == "true":
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
    # Keep the exact timestamp in state/logs, but make Telegram easier to read.
    text = str(value)
    return text.replace("+05:30", " IST")


def signal_message(s):
    """Build the B1 alert as Telegram HTML with deliberate line breaks."""
    buy = s["direction"] == "BUY"
    header = "🚀 BUY ALERT" if buy else "🔻 SELL ALERT"
    direction_arrow = "↑" if buy else "↓"

    return "\n".join([
        f"<b>{header}</b>",
        "",
        f"<b>{_esc(s['symbol'])}</b>",
        "",
        "📊 <b>Strategy:</b> B1 ORB + RVOL",
        "",
        "🕘 <b>ORB</b>",
        f"Time: {_esc(_time(s['orb_timestamp']))}",
        f"High: <b>{_money(s['orb_high'])}</b>",
        f"Low: <b>{_money(s['orb_low'])}</b>",
        f"Close: <b>{_money(s['orb_close'])}</b>",
        "",
        "🚨 <b>BREAKOUT</b>",
        f"15M candle: {_esc(_time(s['setup_15m_timestamp']))}",
        f"15M close: <b>{_money(s['setup_15m_close'])}</b>",
        f"Signal available: {_esc(_time(s['setup_15m_completion']))}",
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
        "",
        "📈 <b>FILTERS</b>",
        f"RSI: <b>{float(s['setup_15m_rsi14']):.2f} {direction_arrow}</b>",
        f"RVOL: <b>{float(s['setup_15m_rvol']):.2f}x</b>",
        f"Quality: <b>{float(s['trade_quality_score']):.1f} / 7</b>",
        "",
        "📋 <b>RULE</b>",
        "First completed 15M close outside 09:15 ORB",
        "+ RSI + Quality ≥ 3 + RVOL ≥ 1.2",
    ])


def stop_update_message(s, new_stop, stage, basis):
    return "\n".join([
        "🔒 <b>STOP UPDATE</b>",
        "",
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
