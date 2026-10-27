from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import app.telegram_notify as tg
from app.state import save

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)

DRIFT_THRESHOLD_PCT = 2.0  # alert if actual fill drifts >2% from signal entry


def reconcile(dhan, state: dict, qty: int, paper: bool) -> None:
    """
    Run at the START of every 5-min cycle.
    1. Fetch live positions from broker.
    2. For each ACTIVE signal: detect manual exits.
    3. For each broker position with no matching ACTIVE signal: adopt as manual trade.
    4. For ENTRY_PLACED signals: check if broker already has the position (F-3 guard).
    """
    if paper:
        _reconcile_paper(state)
        return

    try:
        resp      = dhan.get_positions()
        positions = {p["tradingSymbol"]: p for p in (resp.get("data") or [])}
    except Exception as exc:
        LOG.error("RECONCILE_FETCH_FAILED | %s", exc)
        tg.error_alert("Reconcile: failed to fetch positions", str(exc))
        return

    signals = state.get("signals", {})

    # 1. Check each ACTIVE signal against broker positions
    for key, sig in list(signals.items()):
        if sig.get("status") != "ACTIVE":
            continue
        sym = sig["symbol"]
        if sym not in positions:
            _mark_manually_exited(dhan, sig, paper=False)
            save(state)
        else:
            _check_drift(sig, positions[sym])

    # 2. Detect F-3: ENTRY_PLACED but position already exists → cancel pending LIMIT
    for key, sig in list(signals.items()):
        if sig.get("status") != "ENTRY_PLACED":
            continue
        sym = sig["symbol"]
        if sym in positions:
            LOG.warning("F3_DUPLICATE_POSITION | %s | cancelling pending LIMIT", sym)
            oid = sig.get("entry_order_id")
            if oid:
                try:
                    dhan.cancel_order(oid)
                except Exception as exc:
                    LOG.error("F3_CANCEL_FAILED | %s | %s", sym, exc)
            sig["status"]      = "SKIPPED"
            sig["skip_reason"] = "F3_DUPLICATE_POSITION_CANCELLED_LIMIT"
            tg.error_alert(f"F-3 duplicate position — {sym} — pending LIMIT cancelled", "")
            save(state)

    # 3. Adopt unknown broker positions as manually entered
    active_syms = {sig["symbol"] for sig in signals.values() if sig.get("status") == "ACTIVE"}
    for sym, pos in positions.items():
        if sym in active_syms:
            continue
        _adopt_manual(state, sym, pos, qty)
        save(state)


def _reconcile_paper(state: dict) -> None:
    """Paper mode: no broker calls; check SL/target hit via last_ltp written by signal_monitor."""
    signals = state.get("signals", {})
    for key, sig in list(signals.items()):
        if sig.get("status") != "ACTIVE":
            continue
        ltp = sig.get("last_ltp")
        if ltp is None:
            continue
        ltp       = float(ltp)
        sl        = float(sig["risk"]["sl"])
        direction = sig["direction"]
        if direction == "BUY"  and ltp <= sl:
            _paper_sl_hit(sig, ltp)
        elif direction == "SELL" and ltp >= sl:
            _paper_sl_hit(sig, ltp)


def _paper_sl_hit(sig: dict, ltp: float) -> None:
    sym = sig["symbol"]
    sl  = float(sig["risk"]["sl"])
    LOG.info("PAPER_SL_HIT | %s | sl=%.2f | ltp=%.2f", sym, sl, ltp)
    sig["status"]      = "EXITED"
    sig["exit_price"]  = sl
    sig["exit_reason"] = "SL_HIT"
    sig["exit_time"]   = datetime.now(IST).isoformat()
    tg.sl_hit(sig, sig.get("qty", 1), ltp, paper=True)


def _mark_manually_exited(dhan, sig: dict, paper: bool) -> None:
    """
    Position no longer visible in broker — user exited manually.
    Cancel orphaned SL order FIRST, then mark EXITED.
    """
    sym    = sig["symbol"]
    sl_oid = sig.get("sl_order_id")

    sl_cancelled = False
    if sl_oid and not paper:
        try:
            dhan.cancel_order(sl_oid)
            sl_cancelled = True
            LOG.info("ORPHANED_SL_CANCELLED | %s | sl_oid=%s", sym, sl_oid)
        except Exception as exc:
            LOG.error("ORPHANED_SL_CANCEL_FAILED | %s | %s | MANUAL CANCEL NEEDED", sym, exc)
            tg.error_alert(f"Orphaned SL cancel FAILED — {sym} — CANCEL MANUALLY: {sl_oid}", str(exc))

    sig["status"]      = "EXITED"
    sig["exit_reason"] = "MANUAL_EXIT"
    sig["exit_time"]   = datetime.now(IST).isoformat()
    LOG.info("MANUAL_EXIT_DETECTED | %s", sym)
    tg.manual_exit_detected(sym, sig.get("direction", "?"), sl_cancelled=sl_cancelled)


def _check_drift(sig: dict, pos: dict) -> None:
    """Alert if broker fill price drifted significantly from signal entry."""
    sym        = sig["symbol"]
    expected   = float(sig["risk"]["entry"])
    actual     = float(pos.get("buyAvg") or pos.get("sellAvg") or expected)
    drift_pct  = abs(actual - expected) / expected * 100
    if drift_pct > DRIFT_THRESHOLD_PCT:
        LOG.warning("FILL_DRIFT | %s | expected=%.2f actual=%.2f drift=%.1f%%",
                    sym, expected, actual, drift_pct)
        tg.trade_drift_alert(sym, expected, actual, drift_pct)


def _adopt_manual(state: dict, sym: str, pos: dict, qty: int) -> None:
    """
    Broker position exists but no ACTIVE signal — user entered manually.
    Create a synthetic ACTIVE signal so trade_manager can manage it.
    """
    direction = "BUY" if float(pos.get("netQty", 0)) > 0 else "SELL"
    fill      = float(pos.get("buyAvg") or pos.get("sellAvg") or 0)
    if not fill:
        LOG.warning("ADOPT_MANUAL_NO_PRICE | %s — skipping", sym)
        return

    # Synthetic 2% SL; user can adjust via Telegram or manual state edit
    sl = round(fill * 0.98, 2) if direction == "BUY" else round(fill * 1.02, 2)

    key = f"{sym}_MANUAL_{int(datetime.now(IST).timestamp())}"
    state.setdefault("signals", {})[key] = {
        "symbol"       : sym,
        "direction"    : direction,
        "status"       : "ACTIVE",
        "live_managed" : True,
        "manual_adopted": True,
        "fill_price"   : fill,
        "qty"          : qty,
        "risk": {
            "entry"      : fill,
            "sl"         : sl,
            "original_sl": sl,
            "t1"         : fill,
            "t2"         : fill,
            "t3"         : fill,
        },
        "signal_time"  : datetime.now(IST).isoformat(),
    }
    LOG.info("MANUAL_TRADE_ADOPTED | %s | %s | fill=%.2f | sl=%.2f", sym, direction, fill, sl)
    tg.manual_trade_adopted(sym, direction, fill, sl)
