import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
_ENABLED   = bool(_BOT_TOKEN and _CHAT_ID)


# ── Internal sender ───────────────────────────────────────────────────────────

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
            # 429 = rate limit — back off
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


def _inr(pts: float, qty: int) -> str:
    val = pts * qty
    sign = "+" if val >= 0 else ""
    return f"{sign}₹{abs(val):,.2f}"


# ── Public API ────────────────────────────────────────────────────────────────

def signal_detected(signal: dict) -> None:
    """New ORB signal identified — before order placement."""
    r = signal["risk"]
    risk_pts = abs(float(r["entry"]) - float(r["sl"]))
    rr = abs(float(r["t1"]) - float(r["entry"])) / risk_pts if risk_pts else 0
    rvol = signal.get("rvol_15m", "—")
    _send(
        f"🔍 <b>SIGNAL</b>  ·  {signal['symbol']} {signal['direction']}\n"
        f"Entry: ₹{float(r['entry']):,.2f}  |  SL: ₹{float(r['sl']):,.2f}  |  Risk: {risk_pts:.1f} pts\n"
        f"T1: ₹{float(r['t1']):,.2f}  |  T2: ₹{float(r['t2']):,.2f}  |  T3: ₹{float(r['t3']):,.2f}\n"
        f"R:R → 1:{rr:.1f}  |  RVOL: {rvol}x  |  {_now_str()}"
    )


def order_placed(signal: dict, qty: int, order_id: str, paper: bool = True) -> None:
    """Entry order sent to broker."""
    r     = signal["risk"]
    label = "📝 PAPER" if paper else "📥 <b>ENTRY ORDER</b>"
    _send(
        f"{label}  ·  {signal['symbol']} {signal['direction']}\n"
        f"{qty} share{'s' if qty > 1 else ''} @ ₹{float(r['entry']):,.2f}  (LIMIT · INTRADAY)\n"
        f"Order ID: <code>{order_id}</code>  |  {_now_str()}"
    )


def order_filled(signal: dict, qty: int, fill_price: float, paper: bool = True) -> None:
    """Entry order confirmed filled."""
    label = "📝 PAPER FILL" if paper else "✅ <b>FILLED</b>"
    _send(
        f"{label}  ·  {signal['symbol']} {signal['direction']}\n"
        f"{qty} share{'s' if qty > 1 else ''} @ ₹{fill_price:,.2f}\n"
        f"SL placed @ ₹{float(signal['risk']['sl']):,.2f}  |  {_now_str()}"
    )


def sl_placed(signal: dict, sl_price: float, order_id: str, paper: bool = True) -> None:
    """SL order confirmed in the market."""
    label = "📝 PAPER SL" if paper else "🛡 <b>SL PLACED</b>"
    _send(
        f"{label}  ·  {signal['symbol']}\n"
        f"SL-M trigger @ ₹{sl_price:,.2f}  |  Order ID: <code>{order_id}</code>"
    )


def target_hit(signal: dict, tier: str, ltp: float, qty: int, new_sl: float | None = None) -> None:
    """T1 / T2 / T3 reached — includes SL modification info."""
    icons = {"T1_HIT": "🎯", "T2_HIT": "🎯🎯", "T3_HIT": "🎯🎯🎯"}
    icon  = icons.get(tier, "🎯")
    r     = signal["risk"]
    entry = float(r["entry"])
    tier_key = {"T1_HIT": "t1", "T2_HIT": "t2", "T3_HIT": "t3"}.get(tier, "t1")
    t_val = float(r[tier_key])
    pnl_pts = (ltp - entry) if signal["direction"] == "BUY" else (entry - ltp)

    lines = [
        f"{icon} <b>{tier.replace('_HIT','')}</b>  ·  {signal['symbol']} {signal['direction']}",
        f"LTP: ₹{ltp:,.2f}  |  Target: ₹{t_val:,.2f}",
        f"Unrealised: {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)}  ×  {qty} shares)",
    ]
    if new_sl is not None:
        be_label = "breakeven" if abs(new_sl - entry) < 0.01 else f"₹{new_sl:,.2f}"
        lines.append(f"✅ SL → {be_label}  ({tier.replace('_HIT','').replace('T1','trailing active')})")
    lines.append(_now_str())
    _send("\n".join(lines))


def sl_hit(signal: dict, exit_price: float, qty: int) -> None:
    """Stop-loss triggered — position closed."""
    r     = signal["risk"]
    entry = float(r["entry"])
    pnl_pts = (exit_price - entry) if signal["direction"] == "BUY" else (entry - exit_price)
    tier  = signal.get("highest_target_hit", "")
    note  = f"  ·  was {tier.replace('_HIT','')} ✓" if tier else ""
    _send(
        f"🛑 <b>SL HIT</b>  ·  {signal['symbol']} {signal['direction']}{note}\n"
        f"Exit @ ₹{exit_price:,.2f}  |  P&L: {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)})\n"
        f"{_now_str()}"
    )


def manual_exit(signal: dict, exit_price: float, qty: int, reason: str = "T3") -> None:
    """Partial or full exit at target (T3 close, etc.)."""
    r     = signal["risk"]
    entry = float(r["entry"])
    pnl_pts = (exit_price - entry) if signal["direction"] == "BUY" else (entry - exit_price)
    _send(
        f"💰 <b>EXIT ({reason})</b>  ·  {signal['symbol']} {signal['direction']}\n"
        f"Exit @ ₹{exit_price:,.2f}  |  P&L: {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)})\n"
        f"{_now_str()}"
    )


def square_off(signal: dict, exit_price: float, qty: int, paper: bool = True) -> None:
    """15:10 auto square-off."""
    r     = signal["risk"]
    entry = float(r["entry"])
    pnl_pts = (exit_price - entry) if signal["direction"] == "BUY" else (entry - exit_price)
    label = "📝 PAPER SQUAREOFF" if paper else "⏰ <b>SQUARE-OFF</b>"
    tier  = signal.get("highest_target_hit", "")
    tier_note = f"  ·  {tier.replace('_HIT','')}" if tier else ""
    _send(
        f"{label}  ·  {signal['symbol']} {signal['direction']}{tier_note}\n"
        f"Exit @ ₹{exit_price:,.2f}  (15:10 auto)  |  {qty} share{'s' if qty > 1 else ''}\n"
        f"P&L: {pnl_pts:+.1f} pts  ({_inr(pnl_pts, qty)})\n"
        f"{_now_str()}"
    )


def daily_summary(
    trades: list[dict],
    qty: int,
    paper: bool = True,
) -> None:
    """End-of-day summary sent after square-off."""
    if not trades:
        _send(f"📊 No trades today  |  {_now_str()}")
        return

    wins   = [t for t in trades if t["pnl_pts"] >= 0]
    losses = [t for t in trades if t["pnl_pts"] < 0]
    total  = sum(t["pnl_pts"] for t in trades)
    wr     = len(wins) / len(trades) * 100
    best   = max(trades, key=lambda t: t["pnl_pts"])
    worst  = min(trades, key=lambda t: t["pnl_pts"])
    label  = "📝 PAPER " if paper else ""

    _send(
        f"📊 {label}<b>DAY SUMMARY</b>  ·  {datetime.now(IST).strftime('%a %d %b')}\n"
        f"Trades: {len(trades)}  |  {len(wins)}W/{len(losses)}L  |  WR: {wr:.0f}%\n"
        f"P&L: {total:+.1f} pts  ({_inr(total, qty)}  ×  qty {qty})\n"
        f"Best:  {best['symbol']} {best['pnl_pts']:+.1f} pts\n"
        f"Worst: {worst['symbol']} {worst['pnl_pts']:+.1f} pts"
    )


def manual_trade_adopted(sym: str, direction: str, entry: float, sl: float, qty: int) -> None:
    """Bot detected a manual trade in DhanHQ and adopted it."""
    _send(
        f"🤝 <b>MANUAL TRADE ADOPTED</b>  ·  {sym} {direction}\n"
        f"Entry: ₹{entry:,.2f}  |  Default SL: ₹{sl:,.2f}  (1% fallback)\n"
        f"Qty: {qty}  |  ⚠️ Verify SL in runtime_state.json\n"
        f"{_now_str()}"
    )


def trade_drift_alert(sym: str, drift_type: str, detail: str) -> None:
    """Position qty or entry price differs from what the bot placed."""
    _send(
        f"⚠️ <b>TRADE DRIFT</b>  ·  {sym}\n"
        f"Type: {drift_type}\n"
        f"{detail}\n"
        f"{_now_str()}"
    )


def manual_exit_detected(sym: str, direction: str, sl_cancelled: bool = False) -> None:
    """User closed a bot-managed position outside the bot — signal archived."""
    sl_note = "  ·  SL order cancelled ✓" if sl_cancelled else "  ·  ⚠️ Check SL order manually"
    _send(
        f"👤 <b>MANUAL EXIT</b>  ·  {sym} {direction}\n"
        f"Position closed outside bot — signal archived{sl_note}\n"
        f"{_now_str()}"
    )


def signal_skipped(signal: dict, reason: str, ltp: float | None = None) -> None:
    """Signal not entered — breakout failed, too late, stale, or R:R too poor."""
    ltp_line = f"LTP: ₹{ltp:,.2f}  →  Entry: ₹{float(signal['risk']['entry']):,.2f}\n" if ltp else ""
    _send(
        f"⏭ <b>SKIPPED</b>  ·  {signal['symbol']} {signal['direction']}\n"
        f"{ltp_line}"
        f"Reason: {reason}  |  {_now_str()}"
    )


def error_alert(context: str, error: str) -> None:
    """Send error/exception alert to channel."""
    _send(
        f"⚠️ <b>ERROR</b>  ·  {context}\n"
        f"<code>{error[:300]}</code>\n"
        f"{_now_str()}"
    )


def system_start(paper: bool = True) -> None:
    mode = "PAPER MODE 📝" if paper else "🟠 LIVE MODE"
    _send(f"🟢 <b>Scanner started</b>  ·  {mode}  |  {_now_str()}")


def system_halt(reason: str) -> None:
    _send(f"🔴 <b>TRADING HALTED</b>  ·  {reason}  |  {_now_str()}")
