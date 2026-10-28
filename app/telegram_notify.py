import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

_BOT_TOKEN           = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID             = os.environ.get("TELEGRAM_CHAT_ID", "")
_ENABLED             = bool(_BOT_TOKEN and _CHAT_ID)
BROKERAGE_PER_TRADE  = float(os.environ.get("BROKERAGE_PER_TRADE", "0"))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _send(text: str, retries: int = 2) -> bool:
    if not _ENABLED:
        LOG.info("TELEGRAM_DISABLED | %s", text[:80])
        return False
    url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"}
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=8)
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                retry_after = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(retry_after)
            else:
                LOG.warning("TELEGRAM_HTTP | status=%d | %s", r.status_code, r.text[:120])
        except Exception as exc:
            LOG.warning("TELEGRAM_ERROR | attempt=%d | %s", attempt + 1, exc)
            time.sleep(2)
    return False


def _now_str() -> str:
    return datetime.now(IST).strftime("%H:%M IST")


def _dir(signal: dict) -> str:
    """↑ for BUY, ↓ for SELL."""
    return "↑" if signal.get("direction") == "BUY" else "↓"


def _paper_tag(paper: bool) -> str:
    return "  <code>[P]</code>" if paper else ""


def _round_trip_cost(entry: float, qty: int) -> float:
    """
    Dhan intraday equity round-trip cost.
    Brokerage 0.03% per leg (max ₹20) · STT 0.025% sell · NSE 0.00297%
    GST 18% on (brokerage + exchange) · Stamp 0.003% buy
    """
    if BROKERAGE_PER_TRADE > 0:
        return BROKERAGE_PER_TRADE
    turnover   = entry * qty
    broker_one = min(20.0, 0.0003 * turnover)
    brokerage  = broker_one * 2
    stt        = 0.00025  * turnover
    exchange   = 0.0000297 * turnover * 2
    gst        = 0.18 * (brokerage + exchange)
    stamp      = 0.00003  * turnover
    return round(brokerage + stt + exchange + gst + stamp, 2)


def _inr(pts: float, qty: int) -> str:
    val  = pts * qty
    sign = "+" if val >= 0 else ""
    return f"{sign}₹{abs(val):,.2f}"


_DIV = "─" * 28   # section divider used in multi-section messages


# ── Public API ────────────────────────────────────────────────────────────────

def signal_detected(signal: dict) -> None:
    r        = signal["risk"]
    entry    = float(r["entry"])
    sl       = float(r["sl"])
    risk_pts = abs(entry - sl)
    rr       = abs(float(r["t1"]) - entry) / risk_pts if risk_pts else 0
    rvol     = signal.get("rvol_15m", "—")
    _send(
        f"🔍 <b>SIGNAL</b>  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}\n"
        f"Entry ₹{entry:,.2f}  ·  SL ₹{sl:,.2f}  ·  Risk {risk_pts:.1f} pts\n"
        f"T1 ₹{float(r['t1']):,.2f}  ·  T2 ₹{float(r['t2']):,.2f}  ·  T3 ₹{float(r['t3']):,.2f}\n"
        f"R:R 1:{rr:.1f}  ·  RVOL {rvol}×  ·  {_now_str()}"
    )


def order_placed(signal: dict, qty: int, order_id: str, paper: bool = True) -> None:
    r = signal["risk"]
    _send(
        f"📥 <b>ENTRY ORDER</b>{_paper_tag(paper)}  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}\n"
        f"{qty} share{'s' if qty > 1 else ''} @ ₹{float(r['entry']):,.2f}  ·  LIMIT MIS\n"
        f"Order <code>{order_id}</code>  ·  {_now_str()}"
    )


def order_filled(signal: dict, qty: int, fill_price: float, paper: bool = True) -> None:
    _send(
        f"✅ <b>FILLED</b>{_paper_tag(paper)}  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}\n"
        f"{qty} share{'s' if qty > 1 else ''} @ ₹{fill_price:,.2f}  ·  SL @ ₹{float(signal['risk']['sl']):,.2f}\n"
        f"{_now_str()}"
    )


def sl_placed(signal: dict, sl_price: float, order_id: str, paper: bool = True) -> None:
    _send(
        f"🛡 <b>SL PLACED</b>{_paper_tag(paper)}  ·  {signal['symbol']}\n"
        f"Trigger ₹{sl_price:,.2f}  ·  SL-M MIS  ·  Order <code>{order_id}</code>"
    )


def target_hit(signal: dict, tier: str, ltp: float, qty: int, new_sl: float | None = None) -> None:
    icons    = {"T1_HIT": "🎯", "T2_HIT": "🎯🎯", "T3_HIT": "🎯🎯🎯"}
    icon     = icons.get(tier, "🎯")
    tier_lbl = tier.replace("_HIT", "")
    r        = signal["risk"]
    entry    = float(r["entry"])
    tier_key = {"T1_HIT": "t1", "T2_HIT": "t2", "T3_HIT": "t3"}.get(tier, "t1")
    t_val    = float(r[tier_key])
    pnl_pts  = (ltp - entry) if signal["direction"] == "BUY" else (entry - ltp)

    lines = [
        f"{icon} <b>{tier_lbl}</b>  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}",
        f"LTP ₹{ltp:,.2f}  ·  Target ₹{t_val:,.2f}",
        f"Unrealised  {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)}  ×  {qty})",
    ]
    if new_sl is not None:
        be_label = "Breakeven" if abs(new_sl - entry) < 0.01 else f"₹{new_sl:,.2f}"
        sl_note  = "trailing active" if tier == "T1_HIT" else f"{tier_lbl} floor"
        lines.append(f"✅ SL → {be_label}  ({sl_note})")
    lines.append(_now_str())
    _send("\n".join(lines))


def sl_hit(signal: dict, exit_price: float, qty: int) -> None:
    r       = signal["risk"]
    entry   = float(r["entry"])
    pnl_pts = (exit_price - entry) if signal["direction"] == "BUY" else (entry - exit_price)
    tier    = signal.get("highest_target_hit", "")
    tier_tag = f"  <code>[{tier.replace('_HIT','')} ✓]</code>" if tier else ""
    _send(
        f"🛑 <b>SL HIT</b>  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}{tier_tag}\n"
        f"Exit ₹{exit_price:,.2f}  ·  P&L  {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)})\n"
        f"{_now_str()}"
    )


def manual_exit(signal: dict, exit_price: float, qty: int, reason: str = "T3") -> None:
    r       = signal["risk"]
    entry   = float(r["entry"])
    pnl_pts = (exit_price - entry) if signal["direction"] == "BUY" else (entry - exit_price)
    _send(
        f"💰 <b>EXIT</b>  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}  <code>[{reason}]</code>\n"
        f"Exit ₹{exit_price:,.2f}  ·  P&L  {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)})\n"
        f"{_now_str()}"
    )


def square_off(signal: dict, exit_price: float, qty: int, paper: bool = True) -> None:
    r       = signal["risk"]
    entry   = float(r["entry"])
    pnl_pts = (exit_price - entry) if signal["direction"] == "BUY" else (entry - exit_price)
    tier    = signal.get("highest_target_hit", "")
    tier_tag = f"  <code>[{tier.replace('_HIT','')}]</code>" if tier else ""
    icon    = "🟢" if pnl_pts >= 0 else "🔴"
    _send(
        f"⏰ <b>SQUARE-OFF</b>{_paper_tag(paper)}  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}{tier_tag}\n"
        f"Exit ₹{exit_price:,.2f}  ·  {qty} share{'s' if qty > 1 else ''}  ·  15:05 IST\n"
        f"{icon}  {pnl_pts:+.1f} pts  ·  {_inr(pnl_pts, qty)}"
    )


def daily_summary(trades: list[dict], qty: int, paper: bool = True) -> None:
    """End-of-day summary.  Each trade: {symbol, pnl_pts, entry, qty}"""
    if not trades:
        _send(f"📊 No trades today  ·  {_now_str()}")
        return

    wins      = [t for t in trades if t["pnl_pts"] >= 0]
    losses    = [t for t in trades if t["pnl_pts"] < 0]
    gross_pts = sum(t["pnl_pts"] for t in trades)
    gross_inr = sum(t["pnl_pts"] * t.get("qty", qty) for t in trades)
    brokerage = sum(_round_trip_cost(t.get("entry", 0), t.get("qty", qty)) for t in trades)
    net_inr   = gross_inr - brokerage
    wr        = len(wins) / len(trades) * 100
    best      = max(trades, key=lambda t: t["pnl_pts"])
    worst     = min(trades, key=lambda t: t["pnl_pts"])
    net_icon  = "🟢" if net_inr >= 0 else "🔴"
    label     = "PAPER  " if paper else ""
    date_str  = datetime.now(IST).strftime("%a %d %b")

    _send(
        f"📊 <b>{label}DAY SUMMARY</b>  ·  {date_str}\n"
        f"{_DIV}\n"
        f"{len(trades)} trades  ·  {len(wins)}W / {len(losses)}L  ·  WR {wr:.0f}%\n"
        f"{_DIV}\n"
        f"Gross      {gross_pts:+.1f} pts   {gross_inr:+,.0f} ₹\n"
        f"Brokerage  −₹{brokerage:,.2f}   ({len(trades)} trades)\n"
        f"{_DIV}\n"
        f"{net_icon} Net        ₹{net_inr:+,.2f}\n"
        f"{_DIV}\n"
        f"↑ Best   {best['symbol']:12s}  {best['pnl_pts']:+.1f} pts\n"
        f"↓ Worst  {worst['symbol']:12s}  {worst['pnl_pts']:+.1f} pts"
    )


def signal_skipped(signal: dict, reason: str, ltp: float | None = None) -> None:
    ltp_line = f"LTP ₹{ltp:,.2f}  →  Entry ₹{float(signal['risk']['entry']):,.2f}\n" if ltp else ""
    _send(
        f"⏭ <b>SKIPPED</b>  ·  {signal['symbol']}  {_dir(signal)}{signal['direction']}\n"
        f"{ltp_line}"
        f"Reason  {reason}  ·  {_now_str()}"
    )


def manual_trade_adopted(sym: str, direction: str, entry: float, sl: float, qty: int) -> None:
    dir_arrow = "↑" if direction == "BUY" else "↓"
    _send(
        f"🤝 <b>MANUAL TRADE ADOPTED</b>  ·  {sym}  {dir_arrow}{direction}\n"
        f"Entry ₹{entry:,.2f}  ·  Default SL ₹{sl:,.2f}  (1% fallback)\n"
        f"Qty {qty}  ·  ⚠️ Verify SL in runtime_state.json\n"
        f"{_now_str()}"
    )


def trade_drift_alert(sym: str, drift_type: str, detail: str) -> None:
    _send(
        f"⚠️ <b>TRADE DRIFT</b>  ·  {sym}  <code>[{drift_type}]</code>\n"
        f"{detail}\n"
        f"{_now_str()}"
    )


def manual_exit_detected(sym: str, direction: str, sl_cancelled: bool = False) -> None:
    dir_arrow = "↑" if direction == "BUY" else "↓"
    sl_note   = "SL cancelled ✓" if sl_cancelled else "⚠️ Check SL manually in DhanHQ"
    _send(
        f"👤 <b>MANUAL EXIT</b>  ·  {sym}  {dir_arrow}{direction}\n"
        f"Closed outside bot  ·  {sl_note}\n"
        f"{_now_str()}"
    )


def error_alert(context: str, error: str) -> None:
    _send(
        f"⚠️ <b>ERROR</b>  ·  {context}\n"
        f"<code>{error[:300]}</code>\n"
        f"{_now_str()}"
    )


def system_start(paper: bool = True) -> None:
    mode = "PAPER MODE 📝" if paper else "🟠 LIVE MODE"
    _send(f"🟢 <b>Bot started</b>  ·  {mode}  ·  {_now_str()}")


def system_halt(reason: str) -> None:
    _send(
        f"🔴 <b>TRADING HALTED</b>\n"
        f"{reason}\n"
        f"{_now_str()}"
    )
