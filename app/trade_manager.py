from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import app.telegram_notify as tg
from app.state import load, save

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

PAPER_MODE            = os.environ.get("PAPER_MODE", "true").lower() == "true"
TRADE_QTY             = max(1, int(os.environ.get("TRADE_QTY", "1")))
MAX_SIGNAL_AGE_MIN    = int(os.environ.get("MAX_SIGNAL_AGE_MIN", "30"))
MAX_ENTRY_HHMM        = int(os.environ.get("MAX_ENTRY_HHMM", "1230"))
MAX_PENDING_MIN       = int(os.environ.get("MAX_PENDING_MIN", "15"))
MIN_TRAIL_INC         = float(os.environ.get("MIN_TRAIL_INC", "2.0"))
MAX_OPEN_POSITIONS    = int(os.environ.get("MAX_OPEN_POSITIONS", "5"))
PARTIAL_EXIT_T3       = os.environ.get("PARTIAL_EXIT_T3", "true").lower() == "true"
DAILY_LOSS_HALT_INR   = float(os.environ.get("DAILY_LOSS_HALT_INR", "-5000"))
STATUS_INTERVAL_MIN   = int(os.environ.get("STATUS_INTERVAL_MIN", "15"))
STATUS_SQUAREOFF_HHMM = int(os.environ.get("STATUS_SQUAREOFF_HHMM", "1510"))
ENTRY_CHASE_LIMIT_PCT = float(os.environ.get("ENTRY_CHASE_LIMIT_PCT", "0.015"))
MAX_ORDER_VALUE_INR   = float(os.environ.get("MAX_ORDER_VALUE_INR", "100000"))


def _now_ist() -> datetime:
    return datetime.now(IST)


def _hhmm(dt: datetime) -> int:
    return dt.hour * 100 + dt.minute


# ── Guards ────────────────────────────────────────────────────────────────────

def _fetch_active_ltps(dhan, signals: dict) -> dict[str, float]:
    """Return {security_id: ltp} for all ACTIVE signals. Fails-open (empty dict)."""
    sec_ids = [
        sig["security_id"]
        for sig in signals.values()
        if sig.get("status") == "ACTIVE" and sig.get("security_id")
    ]
    if not sec_ids:
        return {}
    try:
        rows = dhan.quote_batch(sec_ids)
        return {str(k): float(v["ltp"]) for k, v in rows.items() if v.get("ltp") is not None}
    except Exception as exc:
        LOG.warning("STATUS_LTP_FETCH_FAILED | %s", exc)
        return {}


def _should_send_status(state: dict) -> bool:
    """True if STATUS_INTERVAL_MIN has elapsed since last status and time < STATUS_SQUAREOFF_HHMM."""
    if _hhmm(_now_ist()) >= STATUS_SQUAREOFF_HHMM:
        return False
    active = any(s.get("status") == "ACTIVE" for s in state.get("signals", {}).values())
    if not active:
        return False
    last = state.get("last_status_time")
    if last is None:
        return True
    elapsed = (_now_ist() - datetime.fromisoformat(last)).total_seconds() / 60
    return elapsed >= STATUS_INTERVAL_MIN


def send_status_report(dhan, state: dict, paper: bool) -> None:
    """Fetch live LTPs and fire a Telegram portfolio status update."""
    if not _should_send_status(state):
        return
    ltps = _fetch_active_ltps(dhan, state.get("signals", {}))
    tg.live_status(state.get("signals", {}), ltps, _daily_closed_pnl(state), paper)
    state["last_status_time"] = _now_ist().isoformat()
    save(state)


def _daily_closed_pnl(state: dict) -> float:
    """Sum P&L in rupees (pts × qty) of all EXITED signals for today."""
    total = 0.0
    for sig in state.get("signals", {}).values():
        if sig.get("status") != "EXITED":
            continue
        entry = float(sig["risk"]["entry"])
        exit_ = float(sig.get("exit_price", entry))
        qty   = int(sig.get("qty", 1))
        pts   = (exit_ - entry) if sig["direction"] == "BUY" else (entry - exit_)
        total += pts * qty
    return total


def check_daily_halt(state: dict) -> bool:
    """
    If today's closed P&L (in rupees) ≤ DAILY_LOSS_HALT_INR, set
    trading_halted=True, fire Telegram, and return True.
    """
    if state.get("trading_halted"):
        return True
    pnl = _daily_closed_pnl(state)
    if pnl <= DAILY_LOSS_HALT_INR:
        state["trading_halted"] = True
        LOG.warning("DAILY_LOSS_HALT | pnl=Rs %.2f <= threshold=Rs %.2f", pnl, DAILY_LOSS_HALT_INR)
        tg.system_halt(f"Daily loss halt — P&L ₹{pnl:+.0f} ≤ threshold ₹{DAILY_LOSS_HALT_INR:.0f}")
        return True
    return False


def pre_trade_ok(signal: dict, state: dict) -> bool:
    """Return False (and fire Telegram) if the signal should not be entered."""
    now = _now_ist()

    if state.get("trading_halted"):
        tg.signal_skipped(signal, "DAILY_LOSS_HALT")
        return False

    if _hhmm(now) > MAX_ENTRY_HHMM:
        tg.signal_skipped(signal, f"PAST_ENTRY_CUTOFF {MAX_ENTRY_HHMM}")
        return False

    signal_time = signal.get("signal_time")
    if signal_time:
        age_min = (now - datetime.fromisoformat(signal_time)).total_seconds() / 60
        if age_min > MAX_SIGNAL_AGE_MIN:
            tg.signal_skipped(signal, f"STALE age={age_min:.0f}m > {MAX_SIGNAL_AGE_MIN}m")
            return False

    open_count = sum(
        1 for s in state.get("signals", {}).values()
        if s.get("status") == "ACTIVE"
    )
    if open_count >= MAX_OPEN_POSITIONS:
        tg.signal_skipped(signal, f"MAX_POSITIONS {open_count}/{MAX_OPEN_POSITIONS}")
        return False

    return True


def _margin_ok(dhan, signal: dict, qty: int) -> tuple[bool, str]:
    """Check Dhan margin_calculator for the actual margin required.

    Each stock has its own intraday leverage (not a uniform 5×), so we call
    Dhan's API for the exact figure. Fails open (returns True) when the API
    is unreachable — Dhan will reject the order itself if funds are short.
    """
    sec_id   = str(signal.get("security_id", ""))
    exch_seg = signal.get("exchange_segment", "NSE_EQ")
    direction = signal["direction"]
    entry    = float(signal["risk"]["entry"])

    required = dhan.get_margin_required(sec_id, exch_seg, direction, qty, entry)
    if required is None:
        LOG.warning("MARGIN_CHECK | %s | margin_calculator unavailable — failing open", signal["symbol"])
        return True, ""

    available = dhan.get_available_balance()
    if available is None:
        LOG.warning("MARGIN_CHECK | %s | get_fund_limits unavailable — failing open", signal["symbol"])
        return True, ""

    if available < required:
        reason = f"INSUFFICIENT_MARGIN required=₹{required:.0f} available=₹{available:.0f}"
        LOG.warning("MARGIN_CHECK | %s | %s", signal["symbol"], reason)
        return False, reason

    LOG.info("MARGIN_CHECK | %s | OK required=₹%.0f available=₹%.0f", signal["symbol"], required, available)
    return True, ""


def should_place_entry(signal: dict, ltp: float) -> tuple[bool, str]:
    """
    Strict LIMIT logic: always place at signal entry price.
    Rejects if:
      - breakout already failed (LTP crossed original SL), or
      - price ran more than ENTRY_CHASE_LIMIT_PCT (default 1.5%) past entry
        (fill probability too low; a pullback that far likely means reversal)
    """
    r         = signal["risk"]
    orig_sl   = float(r.get("original_sl", r["sl"]))
    entry     = float(r["entry"])
    direction = signal["direction"]

    if direction == "BUY":
        if ltp <= orig_sl:
            return False, f"BREAKOUT_FAILED ltp={ltp:.2f} ≤ sl={orig_sl:.2f}"
        if ltp > entry * (1 + ENTRY_CHASE_LIMIT_PCT):
            return False, f"ENTRY_MISSED ltp={ltp:.2f} > entry+{ENTRY_CHASE_LIMIT_PCT*100:.1f}%={entry*(1+ENTRY_CHASE_LIMIT_PCT):.2f}"
    else:
        if ltp >= orig_sl:
            return False, f"BREAKOUT_FAILED ltp={ltp:.2f} ≥ sl={orig_sl:.2f}"
        if ltp < entry * (1 - ENTRY_CHASE_LIMIT_PCT):
            return False, f"ENTRY_MISSED ltp={ltp:.2f} < entry-{ENTRY_CHASE_LIMIT_PCT*100:.1f}%={entry*(1-ENTRY_CHASE_LIMIT_PCT):.2f}"
    return True, ""


# ── Order placement ───────────────────────────────────────────────────────────

def place_entry_order(dhan, signal: dict, qty: int, paper: bool) -> str | None:
    """Place LIMIT entry order. Returns order_id or None."""
    sym       = signal["symbol"]
    entry     = float(signal["risk"]["entry"])
    direction = signal["direction"]
    sec_id    = str(signal.get("security_id", ""))

    if paper:
        oid = f"PAPER_{sym}_{int(time.time())}"
        LOG.info("PAPER_ENTRY | %s %s | qty=%d | @%.2f | oid=%s", sym, direction, qty, entry, oid)
        tg.order_placed(signal, qty, oid, paper=True)
        return oid

    order_value = qty * entry
    if order_value > MAX_ORDER_VALUE_INR:
        reason = f"ORDER_VALUE_EXCEEDED ₹{order_value:,.0f} > limit ₹{MAX_ORDER_VALUE_INR:,.0f}"
        LOG.warning("ENTRY_BLOCKED | %s | %s", sym, reason)
        tg.signal_skipped(signal, reason)
        return None

    try:
        resp = dhan.place_order(
            security_id      = sec_id,
            exchange_segment = dhan.NSE,
            transaction_type = dhan.BUY if direction == "BUY" else dhan.SELL,
            quantity         = qty,
            order_type       = dhan.LIMIT,
            product_type     = dhan.INTRA,
            price            = entry,
        )
        oid = str((resp.get("data") or {}).get("orderId", ""))
        if not oid:
            raise ValueError(f"no orderId in response: {resp}")
        tg.order_placed(signal, qty, oid, paper=False)
        return oid
    except Exception as exc:
        LOG.error("ENTRY_ORDER_FAILED | %s | %s", sym, exc)
        tg.error_alert(f"Entry order failed — {sym}", str(exc))
        return None


def wait_for_fill(dhan, order_id: str, signal: dict, qty: int, paper: bool) -> float | None:
    """
    Poll until TRADED or MAX_PENDING_MIN timeout.
    Returns fill price, or None on timeout / rejection (order cancelled).
    """
    sym = signal["symbol"]

    if paper:
        fill = float(signal["risk"]["entry"])
        LOG.info("PAPER_FILL | %s | @%.2f", sym, fill)
        tg.order_filled(signal, qty, fill, paper=True)
        return fill

    # Cap at 2 minutes to avoid blocking the GHA runner across cycles
    deadline = time.time() + min(MAX_PENDING_MIN * 60, 120)
    while time.time() < deadline:
        try:
            data   = (dhan.get_order_by_id(order_id).get("data") or {})
            status = data.get("orderStatus", "")
            if status == "TRADED":
                fill = float(data.get("tradedPrice", signal["risk"]["entry"]))
                tg.order_filled(signal, qty, fill, paper=False)
                return fill
            if status in ("CANCELLED", "REJECTED"):
                LOG.warning("ORDER_%s | %s | oid=%s", status, sym, order_id)
                tg.signal_skipped(signal, f"ORDER_{status}")
                return None
        except Exception as exc:
            LOG.warning("POLL_ORDER | %s | %s", sym, exc)
        time.sleep(30)

    LOG.warning("ENTRY_TIMEOUT | %s | cancelling oid=%s", sym, order_id)
    try:
        dhan.cancel_order(order_id)
    except Exception as exc:
        LOG.error("CANCEL_FAILED | %s | %s", sym, exc)
    tg.signal_skipped(signal, "ENTRY_TIMEOUT — LIMIT not filled in 15 min")
    return None


def place_sl_order(dhan, signal: dict, qty: int, paper: bool) -> str | None:
    """
    Place SL-M at original_sl. On failure → _emergency_exit() immediately.
    Returns sl_order_id or None.
    """
    sym      = signal["symbol"]
    orig_sl  = float(signal["risk"].get("original_sl", signal["risk"]["sl"]))
    sec_id   = str(signal.get("security_id", ""))
    direction = signal["direction"]

    if paper:
        oid = f"PAPER_SL_{sym}_{int(time.time())}"
        LOG.info("PAPER_SL | %s | trigger=%.2f | oid=%s", sym, orig_sl, oid)
        tg.sl_placed(signal, orig_sl, oid, paper=True)
        return oid

    try:
        resp = dhan.place_order(
            security_id      = sec_id,
            exchange_segment = dhan.NSE,
            transaction_type = dhan.SELL if direction == "BUY" else dhan.BUY,
            quantity         = qty,
            order_type       = dhan.SL_M,
            product_type     = dhan.INTRA,
            price            = 0,
            trigger_price    = orig_sl,
        )
        oid = str((resp.get("data") or {}).get("orderId", ""))
        if not oid:
            raise ValueError(f"no orderId in SL response: {resp}")
        tg.sl_placed(signal, orig_sl, oid, paper=False)
        return oid
    except Exception as exc:
        LOG.error("SL_ORDER_FAILED | %s | %s — emergency exit", sym, exc)
        tg.error_alert(f"SL order FAILED — {sym} — emergency exit triggered", str(exc))
        _emergency_exit(dhan, signal, qty, paper)
        return None


def _emergency_exit(dhan, signal: dict, qty: int, paper: bool = False) -> None:
    """Market order to close position when SL placement fails."""
    sym       = signal["symbol"]
    sec_id    = str(signal.get("security_id", ""))
    direction = signal["direction"]
    LOG.critical("EMERGENCY_EXIT | %s | market close qty=%d | paper=%s", sym, qty, paper)
    if paper:
        signal["status"]      = "EXITED"
        signal["exit_reason"] = "EMERGENCY_EXIT_SL_FAILED_PAPER"
        LOG.info("PAPER_EMERGENCY_EXIT | %s | no real order placed", sym)
        return
    try:
        dhan.place_order(
            security_id      = sec_id,
            exchange_segment = dhan.NSE,
            transaction_type = dhan.SELL if direction == "BUY" else dhan.BUY,
            quantity         = qty,
            order_type       = dhan.MARKET,
            product_type     = dhan.INTRA,
            price            = 0,
        )
        signal["status"]      = "EXITED"
        signal["exit_reason"] = "EMERGENCY_EXIT_SL_FAILED"
        LOG.info("EMERGENCY_EXIT_OK | %s", sym)
    except Exception as exc:
        LOG.critical("EMERGENCY_EXIT_FAILED | %s | MANUAL CLOSE REQUIRED | %s", sym, exc)
        tg.error_alert(f"EMERGENCY EXIT FAILED — {sym} — MANUAL CLOSE REQUIRED", str(exc))


def modify_sl_order(dhan, signal: dict, new_sl: float, paper: bool) -> bool:
    """
    Move SL-M trigger to new_sl. Skips if improvement < MIN_TRAIL_INC (rate-limit guard).
    """
    sym         = signal["symbol"]
    direction   = signal["direction"]
    current_sl  = float(signal["risk"]["sl"])
    sl_order_id = signal.get("sl_order_id")

    improvement = (new_sl - current_sl) if direction == "BUY" else (current_sl - new_sl)
    if improvement < MIN_TRAIL_INC:
        return False

    if paper:
        LOG.info("PAPER_SL_MODIFY | %s | %.2f → %.2f", sym, current_sl, new_sl)
        signal["risk"]["sl"] = new_sl
        return True

    if not sl_order_id:
        LOG.warning("SL_MODIFY_NO_ORDER | %s", sym)
        return False

    try:
        dhan.modify_order(
            order_id      = sl_order_id,
            order_type    = dhan.SL_M,
            quantity      = signal.get("qty", TRADE_QTY),
            price         = 0,
            trigger_price = new_sl,
        )
        signal["risk"]["sl"] = new_sl
        LOG.info("SL_MODIFIED | %s | %.2f → %.2f", sym, current_sl, new_sl)
        return True
    except Exception as exc:
        LOG.error("SL_MODIFY_FAILED | %s | %s", sym, exc)
        tg.error_alert(f"SL modify failed — {sym}", str(exc))
        return False


# ── Partial exit at T3 ───────────────────────────────────────────────────────

def _partial_exit_t3(dhan, signal: dict, ltp: float, paper: bool) -> None:
    """
    At T3 hit: exit 50% qty at market, trail remaining 50%.
    Skipped if qty=1 (can't split) or already done (t3_partial_done flag).
    """
    if signal.get("t3_partial_done"):
        return

    qty = int(signal.get("qty", TRADE_QTY))
    if qty < 2:
        LOG.info("PARTIAL_EXIT_SKIP | %s | qty=%d — cannot split", signal["symbol"], qty)
        tg.signal_skipped(signal, "T3_PARTIAL_SKIP qty=1 (holding full position)")
        signal["t3_partial_done"] = True
        return

    exit_qty      = qty // 2
    remaining_qty = qty - exit_qty
    sym           = signal["symbol"]
    direction     = signal["direction"]
    sec_id        = str(signal.get("security_id", ""))

    if not paper:
        try:
            dhan.place_order(
                security_id      = sec_id,
                exchange_segment = dhan.NSE,
                transaction_type = dhan.SELL if direction == "BUY" else dhan.BUY,
                quantity         = exit_qty,
                order_type       = dhan.MARKET,
                product_type     = dhan.INTRA,
                price            = 0,
            )
        except Exception as exc:
            LOG.error("PARTIAL_EXIT_FAILED | %s | %s", sym, exc)
            tg.error_alert(f"T3 partial exit failed — {sym}", str(exc))
            signal["t3_partial_done"] = True
            return

        # Reduce SL order qty to match remaining position
        sl_oid = signal.get("sl_order_id")
        if sl_oid:
            try:
                dhan.modify_order(
                    order_id      = sl_oid,
                    order_type    = dhan.SL_M,
                    quantity      = remaining_qty,
                    price         = 0,
                    trigger_price = float(signal["risk"]["sl"]),
                )
            except Exception as exc:
                LOG.warning("PARTIAL_EXIT_SL_QTY_MODIFY_FAILED | %s | %s", sym, exc)

    entry   = float(signal["risk"]["entry"])
    pnl_pts = (ltp - entry) if direction == "BUY" else (entry - ltp)
    LOG.info("PARTIAL_EXIT_T3 | %s | exit_qty=%d | remaining=%d | ltp=%.2f | pnl=%.2f pts",
             sym, exit_qty, remaining_qty, ltp, pnl_pts)
    tg.manual_exit(signal, ltp, exit_qty, reason=f"T3 PARTIAL ({exit_qty} of {qty})")

    signal["qty"]             = remaining_qty
    signal["t3_partial_done"] = True


# ── TSL ───────────────────────────────────────────────────────────────────────

def _apply_tsl(dhan, signal: dict, paper: bool) -> None:
    """
    Step-based TSL: reads highest_target_hit (set by signal_monitor.py) and
    moves SL to the appropriate floor, plus continuous trail when active.
    """
    tier = signal.get("highest_target_hit", "")
    if not tier:
        return

    r         = signal["risk"]
    entry     = float(r["entry"])
    direction = signal["direction"]
    orig_sl   = float(r.get("original_sl", r["sl"]))
    ltp       = signal.get("last_ltp")
    if ltp is None:
        return
    ltp = float(ltp)

    t1 = float(r["t1"])
    t2 = float(r["t2"])

    # Floor SL based on tier
    if tier == "T1_HIT":
        floor_sl = entry
    elif tier == "T2_HIT":
        floor_sl = t1
    elif tier == "T3_HIT":
        floor_sl = t2
    else:
        return

    # Partial exit at T3 (50% qty) — before activating trail
    if tier == "T3_HIT" and PARTIAL_EXIT_T3:
        _partial_exit_t3(dhan, signal, ltp, paper)

    # Activate trailing on T1
    if not signal.get("trailing_active") and tier in ("T1_HIT", "T2_HIT", "T3_HIT"):
        signal["trailing_active"] = True
        signal["trail_distance"]  = abs(entry - orig_sl)
        tg.target_hit(signal, tier, ltp, signal.get("qty", TRADE_QTY), new_sl=floor_sl)

    # Continuous trail on top of floor
    trail_dist = signal.get("trail_distance", abs(entry - orig_sl))
    if direction == "BUY":
        trail_sl = ltp - trail_dist
        new_sl   = max(floor_sl, trail_sl)
    else:
        trail_sl = ltp + trail_dist
        new_sl   = min(floor_sl, trail_sl)

    modify_sl_order(dhan, signal, new_sl, paper)


# ── Main entry point ──────────────────────────────────────────────────────────

def _refresh_ltps(dhan, state: dict) -> None:
    """
    Fetch current LTPs for all ACTIVE signals and write them onto the signal
    dicts as last_ltp.  Also runs signal_monitor so T1/T2/T3/SL hits are
    detected and highest_target_hit is set before _apply_tsl() runs.
    """
    from app.main import _fetch_current_prices
    from app.signal_monitor import monitor_active_signals

    has_active = any(
        s.get("status") == "ACTIVE" for s in state.get("signals", {}).values()
    )
    if not has_active:
        return

    current_prices = _fetch_current_prices(dhan, state)
    if current_prices:
        state["current_prices"] = current_prices
        monitor_active_signals(state, current_prices)
        LOG.info("LTP_REFRESH | updated %d symbols", len(current_prices))
    else:
        LOG.warning("LTP_REFRESH | no prices returned — last_ltp unchanged")


def run(dhan, state: dict, qty: int = TRADE_QTY, paper: bool = PAPER_MODE) -> None:
    """
    Called by live-trade.yml every 5 min.
      0. Reconcile positions (detect manual trades / exits)
      1. Refresh LTPs for ACTIVE signals (sets last_ltp + detects T1/T2/T3 hits)
      2. Poll Telegram commands (/halt /resume /squareoff /status)
         — LTPs are fresh so /status reports accurate open P&L
      3. Place entries for NEW signals (scan window only)
      4. Apply TSL for ACTIVE signals
    """
    from app.position_tracker import reconcile
    from app.telegram_cmd import poll_and_process, register_commands
    register_commands()

    # Step 0: reconcile before anything else
    reconcile(dhan, state, qty, paper)
    save(state)

    # Step 1: refresh LTPs so TSL and /status both have current prices
    _refresh_ltps(dhan, state)
    save(state)

    # Step 2: Telegram command poll (non-blocking, timeout=0; LTPs now fresh)
    poll_and_process(dhan, state, paper)

    now  = _now_ist()
    hhmm = _hhmm(now)

    # Step 3: entry placement
    check_daily_halt(state)   # sets trading_halted if threshold crossed
    if hhmm <= MAX_ENTRY_HHMM:
        for key, signal in list(state.get("signals", {}).items()):
            if signal.get("status") != "NEW":
                continue

            if not pre_trade_ok(signal, state):
                signal["status"] = "SKIPPED"
                save(state)
                continue

            ltp = state.get("current_prices", {}).get(signal["symbol"])
            if ltp is not None:
                ok, reason = should_place_entry(signal, float(ltp))
                if not ok:
                    signal["status"] = "SKIPPED"
                    tg.signal_skipped(signal, reason, ltp=float(ltp))
                    save(state)
                    continue

            if not paper:
                ok, reason = _margin_ok(dhan, signal, qty)
                if not ok:
                    signal["status"] = "SKIPPED"
                    tg.signal_skipped(signal, reason)
                    save(state)
                    continue

            order_id = place_entry_order(dhan, signal, qty, paper)
            if not order_id:
                signal["status"] = "SKIPPED"
                save(state)
                continue

            signal["entry_order_id"] = order_id
            signal["status"]         = "ENTRY_PLACED"
            save(state)

            fill_price = wait_for_fill(dhan, order_id, signal, qty, paper)
            if fill_price is None:
                signal["status"] = "SKIPPED"
                save(state)
                continue

            signal["fill_price"]   = fill_price
            signal["qty"]          = qty
            signal["live_managed"] = True  # tells signal_monitor.py to skip paper SL writes

            sl_oid = place_sl_order(dhan, signal, qty, paper)
            if sl_oid:
                signal["sl_order_id"] = sl_oid
                signal["status"]      = "ACTIVE"
            # if sl_oid is None, _emergency_exit already fired inside place_sl_order
            save(state)

    # Step 3b: fill polling for live orders placed inline by scanner
    # (ENTRY_PLACED signals: order fired, waiting for TRADED status)
    for key, signal in list(state.get("signals", {}).items()):
        if signal.get("status") != "ENTRY_PLACED":
            continue
        oid = signal.get("entry_order_id", "")
        fill = wait_for_fill(dhan, oid, signal, qty, paper)
        if fill:
            signal["fill_price"] = fill
            signal["qty"]        = qty
            signal["live_managed"] = True
            sl_oid = place_sl_order(dhan, signal, qty, paper)
            if sl_oid:
                signal["sl_order_id"] = sl_oid
                signal["status"]      = "ACTIVE"
            else:
                # _emergency_exit fired inside place_sl_order; mark closed
                signal["status"] = "EXITED"
        else:
            signal["status"] = "SKIPPED"
        save(state)

    # Step 4: TSL management
    for key, signal in list(state.get("signals", {}).items()):
        if signal.get("status") == "ACTIVE":
            _apply_tsl(dhan, signal, paper)

    save(state)

    # Step 5: periodic live status report
    send_status_report(dhan, state, paper)


def main() -> None:
    import logging as _logging
    from app.dhan_client import DhanClient

    from zoneinfo import ZoneInfo as _ZoneInfo
    _IST = _ZoneInfo("Asia/Kolkata")

    class _ISTFormatter(_logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from datetime import datetime as _dt
            t = _dt.fromtimestamp(record.created, tz=_IST)
            return t.strftime(datefmt or "%Y-%m-%d %H:%M:%S IST")

    _handler = _logging.StreamHandler()
    _handler.setFormatter(_ISTFormatter("%(asctime)s | %(levelname)s | %(message)s"))
    _logging.root.addHandler(_handler)
    _logging.root.setLevel(os.getenv("LOG_LEVEL", "INFO"))

    from datetime import time as dtime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    market_open  = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=5,  second=0, microsecond=0)
    if not (market_open <= now <= market_close):
        LOG.info("Outside market hours — nothing to do")
        return

    dhan  = DhanClient()
    state = load(now.date())
    paper = state.get("paper_mode", PAPER_MODE)
    if os.environ.get("ANNOUNCE_START", "true").lower() != "false":
        tg.system_start(paper=paper)
    run(dhan, state, qty=TRADE_QTY, paper=paper)


if __name__ == "__main__":
    main()
