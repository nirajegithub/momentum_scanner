from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import app.telegram_notify as tg
from app.state import load, save

IST       = ZoneInfo("Asia/Kolkata")
LOG       = logging.getLogger(__name__)
PAPER_MODE = os.environ.get("PAPER_MODE", "true").lower() == "true"
TRADE_QTY  = int(os.environ.get("TRADE_QTY", "1"))


def square_off_all(dhan, state: dict, qty: int, paper: bool) -> None:
    """
    Close every open MIS position at market price.
    Called by square-off.yml at 15:05 IST (09:35 UTC).
    """
    signals = state.get("signals", {})
    now     = datetime.now(IST)

    for key, sig in list(signals.items()):
        if sig.get("status") not in ("ACTIVE", "ENTRY_PLACED"):
            continue

        sym       = sig["symbol"]
        direction = sig["direction"]

        # Cancel orphaned SL before squaring off
        sl_oid = sig.get("sl_order_id")
        if sl_oid and not paper:
            try:
                dhan.cancel_order(sl_oid)
                LOG.info("SQUARE_OFF_SL_CANCELLED | %s | sl_oid=%s", sym, sl_oid)
            except Exception as exc:
                LOG.warning("SQUARE_OFF_SL_CANCEL_FAILED | %s | %s", sym, exc)

        if paper:
            exit_price = sig.get("last_ltp") or float(sig["risk"]["entry"])
            LOG.info("PAPER_SQUARE_OFF | %s | %s | @%.2f", sym, direction, float(exit_price))
        else:
            sec_id = str(sig.get("security_id", ""))
            try:
                dhan.place_order(
                    security_id      = sec_id,
                    exchange_segment = dhan.NSE,
                    transaction_type = dhan.SELL if direction == "BUY" else dhan.BUY,
                    quantity         = sig.get("qty", qty),
                    order_type       = dhan.MARKET,
                    product_type     = dhan.INTRA,
                    price            = 0,
                )
                exit_price = sig.get("last_ltp") or float(sig["risk"]["entry"])
                LOG.info("SQUARE_OFF_OK | %s | %s", sym, direction)
            except Exception as exc:
                LOG.error("SQUARE_OFF_FAILED | %s | %s | MANUAL CLOSE REQUIRED", sym, exc)
                tg.error_alert(f"Square-off FAILED — {sym} — MANUAL CLOSE REQUIRED", str(exc))
                continue

        sig["status"]      = "EXITED"
        sig["exit_price"]  = float(exit_price)
        sig["exit_reason"] = "EOD_SQUARE_OFF"
        sig["exit_time"]   = now.isoformat()
        tg.square_off(sig, sig.get("qty", qty), float(exit_price), paper=paper)

    save(state)


def _compute_daily_summary(state: dict) -> dict:
    """Aggregate today's closed signals into P&L stats."""
    signals  = state.get("signals", {})
    total    = won = lost = skipped = 0
    pnl_pts  = 0.0

    for sig in signals.values():
        status = sig.get("status")
        if status == "SKIPPED":
            skipped += 1
            continue
        if status != "EXITED":
            continue
        total += 1
        entry = float(sig["risk"]["entry"])
        exit_ = float(sig.get("exit_price", entry))
        qty   = int(sig.get("qty", 1))
        pts   = (exit_ - entry) if sig["direction"] == "BUY" else (entry - exit_)
        pnl_pts += pts
        if pts >= 0:
            won  += 1
        else:
            lost += 1

    return {
        "total"  : total,
        "won"    : won,
        "lost"   : lost,
        "skipped": skipped,
        "pnl_pts": round(pnl_pts, 2),
    }


def main() -> None:
    import logging as _logging
    _logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    from app.dhan_client import DhanClient

    now   = datetime.now(IST)
    dhan  = DhanClient()
    state = load(now.date())

    square_off_all(dhan, state, qty=TRADE_QTY, paper=PAPER_MODE)

    summary = _compute_daily_summary(state)
    tg.daily_summary(
        date     = now.date().isoformat(),
        total    = summary["total"],
        won      = summary["won"],
        lost     = summary["lost"],
        skipped  = summary["skipped"],
        pnl_pts  = summary["pnl_pts"],
        paper    = PAPER_MODE,
    )
    LOG.info(
        "DAILY_SUMMARY | date=%s | total=%d | won=%d | lost=%d | skipped=%d | pnl=%.2f pts",
        now.date(), summary["total"], summary["won"], summary["lost"],
        summary["skipped"], summary["pnl_pts"],
    )


if __name__ == "__main__":
    main()
