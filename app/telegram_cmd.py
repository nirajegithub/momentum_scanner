"""
Telegram command poller — runs at the start of every trade_manager cycle.

Supported commands (sent to the bot's chat):
  /halt       Stop new entries  (sets state["trading_halted"] = True)
  /resume     Re-enable entries (sets state["trading_halted"] = False)
  /squareoff  Close all open positions at market immediately
  /status     Report open positions + today's P&L
  /paper on   Switch to paper/simulated mode
  /paper off  Switch to live trading mode

Security: only messages from TELEGRAM_CHAT_ID are processed.
Last processed update_id is stored in state["_tg_update_id"] so
commands are never replayed across GHA cycles.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import app.telegram_notify as tg
from app.state import save

IST       = ZoneInfo("Asia/Kolkata")
LOG       = logging.getLogger(__name__)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = (os.environ.get("TELEGRAM_PERSONAL_CHAT_ID")
             or os.environ.get("TELEGRAM_CHAT_ID", ""))
TRADE_QTY = int(os.environ.get("TRADE_QTY", "1"))

_BOT_COMMANDS = [
    {"command": "status",    "description": "Open positions + today P&L"},
    {"command": "paper",     "description": "Toggle paper mode: /paper on | off"},
    {"command": "halt",      "description": "Stop new entries"},
    {"command": "resume",    "description": "Re-enable entries"},
    {"command": "squareoff", "description": "Close all open positions now"},
]


# ── Telegram API helpers ──────────────────────────────────────────────────────

def register_commands() -> None:
    """Push command menu to Telegram (idempotent — safe to call every run)."""
    if not BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
            json={"commands": _BOT_COMMANDS},
            timeout=8,
        )
    except Exception as exc:
        LOG.warning("TG_SET_COMMANDS_FAILED | %s", exc)


def _get_updates(offset: int) -> list:
    if not BOT_TOKEN:
        return []
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 0, "limit": 20},
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json().get("result", [])
    except Exception as exc:
        LOG.warning("TG_POLL_FAILED | %s", exc)
    return []


def _reply(text: str) -> None:
    if not (BOT_TOKEN and CHAT_ID):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception as exc:
        LOG.warning("TG_REPLY_FAILED | %s", exc)


def _now_str() -> str:
    return datetime.now(IST).strftime("%H:%M IST")


# ── Command handlers ──────────────────────────────────────────────────────────

def _cmd_halt(state: dict) -> None:
    state["trading_halted"] = True
    LOG.warning("CMD_HALT | trading halted via Telegram command")
    _reply(f"🔴 <b>TRADING HALTED</b>  ·  Manual /halt command\nNo new entries will be placed.  |  {_now_str()}")


def _cmd_resume(state: dict) -> None:
    state["trading_halted"] = False
    LOG.info("CMD_RESUME | trading resumed via Telegram command")
    _reply(f"🟢 <b>TRADING RESUMED</b>  ·  /resume command\nNew entries enabled.  |  {_now_str()}")


def _cmd_paper(state: dict, text: str) -> bool:
    """Set paper_mode override in state. Returns True if state was modified."""
    arg = (text.strip().lower().split() + [""])[1]
    if arg == "on":
        state["paper_mode"] = True
        LOG.warning("CMD_PAPER_ON | paper mode enabled via Telegram")
        _reply(
            f"📄 <b>PAPER MODE ON</b>  ·  Simulated orders only\n"
            f"No real trades will be placed.  |  {_now_str()}"
        )
        return True
    elif arg == "off":
        state["paper_mode"] = False
        LOG.warning("CMD_PAPER_OFF | LIVE trading enabled via Telegram")
        _reply(
            f"🔴 <b>PAPER MODE OFF — LIVE ACTIVE</b>\n"
            f"Real orders will be placed on Dhan.  |  {_now_str()}"
        )
        return True
    else:
        current = state.get("paper_mode")
        if current is None:
            mode_str = "env default (check workflow)"
        elif current:
            mode_str = "ON  (paper / simulated)"
        else:
            mode_str = "OFF  ⚠️  LIVE TRADING"
        _reply(
            f"📄 Paper mode: <b>{mode_str}</b>\n"
            f"/paper on  → safe / simulated\n"
            f"/paper off → live orders  |  {_now_str()}"
        )
        return False


def _cmd_squareoff(dhan, state: dict, paper: bool) -> None:
    from app.square_off import square_off_all
    LOG.warning("CMD_SQUAREOFF | manual square-off triggered via Telegram")
    _reply(f"⏰ <b>MANUAL SQUARE-OFF</b> triggered  ·  Closing all open positions…  |  {_now_str()}")
    square_off_all(dhan, state, qty=TRADE_QTY, paper=paper)


def _cmd_status(state: dict) -> None:
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    signals   = state.get("signals", {})

    active  = [s for s in signals.values() if s.get("status") == "ACTIVE"]
    exited  = [s for s in signals.values()
               if s.get("status") == "EXITED"
               and (s.get("exit_time") or s.get("signal_time", "")).startswith(today_str)]
    skipped = [s for s in signals.values()
               if s.get("status") == "SKIPPED"
               and s.get("signal_time", "").startswith(today_str)]

    # Open positions P&L (uses last_ltp set by _refresh_ltps)
    pnl_open   = 0.0
    lines_open = []
    for s in sorted(active, key=lambda x: x["symbol"]):
        entry = float(s["risk"]["entry"])
        ltp   = float(s.get("last_ltp") or entry)
        pts   = (ltp - entry) if s["direction"] == "BUY" else (entry - ltp)
        pnl_open += pts
        tier  = s.get("highest_target_hit", "")
        tier_tag = f"  <code>[{tier.replace('_HIT','')}✓]</code>" if tier else ""
        icon  = "🟢" if pts >= 0 else "🔴"
        dir_arrow = "↑" if s["direction"] == "BUY" else "↓"
        lines_open.append(
            f"  {icon} {s['symbol']} {dir_arrow}{tier_tag}  {pts:+.1f} pts  ·  ₹{ltp:,.0f}"
        )

    # Closed P&L (today only; exit_price is accurate post _refresh_ltps fix)
    pnl_closed = 0.0
    for s in exited:
        entry      = float(s["risk"]["entry"])
        exit_price = float(s.get("exit_price") or entry)
        pts        = (exit_price - entry) if s["direction"] == "BUY" else (entry - exit_price)
        pnl_closed += pts

    halted   = state.get("trading_halted", False)
    halt_tag = "🔴 <b>HALTED</b>" if halted else "🟢 Entries active"
    paper_st = state.get("paper_mode")
    paper_tag = "📄 paper" if paper_st else ("🔴 LIVE" if paper_st is False else "📄 paper (default)")
    date_str = datetime.now(IST).strftime("%a %d %b")

    msg = f"📋 <b>STATUS</b>  ·  {date_str}  ·  {_now_str()}\n{halt_tag}  ·  {paper_tag}\n"

    if active:
        msg += f"\n<b>Open ({len(active)})</b>  ·  unrealised {pnl_open:+.1f} pts\n"
        msg += "\n".join(lines_open) + "\n"
    else:
        msg += "\nNo open positions\n"

    closed_icon = "🟢" if pnl_closed >= 0 else "🔴"
    msg += (
        f"\n{closed_icon} Closed today  {len(exited)} trades  ·  {pnl_closed:+.1f} pts"
    )
    if skipped:
        msg += f"\n⏭ Skipped  {len(skipped)}"

    _reply(msg)


# ── Main entry point ──────────────────────────────────────────────────────────

def poll_and_process(dhan, state: dict, paper: bool) -> None:
    """
    Called once per trade_manager cycle.
    Fetches new Telegram updates, processes recognized commands,
    saves state if modified.
    """
    if not (BOT_TOKEN and CHAT_ID):
        return

    offset   = int(state.get("_tg_update_id", 0))
    updates  = _get_updates(offset)
    modified = False

    for update in updates:
        uid = update.get("update_id", 0)
        state["_tg_update_id"] = uid + 1   # advance offset regardless

        msg    = update.get("message") or update.get("channel_post") or {}
        text   = (msg.get("text") or "").strip()
        sender = str(msg.get("chat", {}).get("id", ""))

        # Only process commands from the configured chat
        if sender != str(CHAT_ID):
            LOG.debug("TG_CMD_IGNORED | from=%s (not authorised)", sender)
            continue

        cmd = text.split()[0].lower().split("@")[0] if text else ""
        LOG.info("TG_CMD | cmd=%s | from_chat=%s", cmd or "(none)", sender)

        if cmd == "/halt":
            _cmd_halt(state)
            modified = True
        elif cmd == "/resume":
            _cmd_resume(state)
            modified = True
        elif cmd == "/squareoff":
            _cmd_squareoff(dhan, state, paper)
            modified = True
        elif cmd == "/status":
            _cmd_status(state)
        elif cmd == "/paper":
            if _cmd_paper(state, text):
                modified = True
        elif text.startswith("/"):
            _reply(
                f"❓ Unknown command: <code>{text[:40]}</code>\n"
                f"Available: /halt  /resume  /squareoff  /status  /paper on|off"
            )

    if modified:
        save(state)
