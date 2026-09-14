from __future__ import annotations

import os
import requests

from .config import DISCLAIMER


def send(text):
    full = text.rstrip() + "\n\n" + DISCLAIMER
    if os.getenv("DRY_RUN", "true").lower() == "true":
        print(full)
        return True
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": full},
        timeout=20,
    )
    r.raise_for_status()
    if not r.json().get("ok", True):
        raise RuntimeError("Telegram API returned failure")
    return True


def _money(value):
    return f"₹{float(value):,.2f}"


def signal_message(s):
    header = "🚀 BUY ALERT" if s["direction"] == "BUY" else "🔻 SELL ALERT"
    return "\n".join([
        header,
        "",
        str(s["symbol"]),
        "",
        "Strategy: B1 ORB + RVOL",
        f"ORB: {s['orb_timestamp']}",
        f"Breakout 15M: {s['setup_15m_timestamp']}",
        f"Signal/Entry available: {s['setup_15m_completion']}",
        "",
        f"Entry: {_money(s['risk']['entry'])}",
        f"SL: {_money(s['risk']['sl'])}",
        f"T1: {_money(s['risk']['t1'])}",
        f"T2: {_money(s['risk']['t2'])}",
        f"T3: {_money(s['risk']['t3'])}",
        "",
        f"ORB High: {_money(s['orb_high'])}",
        f"ORB Low: {_money(s['orb_low'])}",
        f"15M Close: {_money(s['setup_15m_close'])}",
        f"15M RSI: {float(s['setup_15m_rsi14']):.2f}",
        f"15M RVOL: {float(s['setup_15m_rvol']):.2f}x",
        f"Quality: {float(s['trade_quality_score']):.1f}",
        "",
        "Rule: first completed 15M close outside 09:15 ORB + RSI + Quality ≥ 3 + RVOL ≥ 1.2",
    ])


def stop_update_message(s, new_stop, stage, basis):
    return "\n".join(["🔒 STOP UPDATE", "", str(s["symbol"]), f"New SL: {_money(new_stop)}", f"Status: {basis}"])


def exit_message(s, exit_price, reason, exit_time):
    entry = float(s["risk"]["entry"])
    points = float(exit_price) - entry if s["direction"] == "BUY" else entry - float(exit_price)
    return f"⚠️ {s['symbol']} {reason}\nPoints: {points:+.2f}\nEntry: {_money(entry)}\nExit: {_money(exit_price)}\nTime: {exit_time}"
