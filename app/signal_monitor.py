import logging
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


def monitor_active_signals(state, current_prices):
    """
    Monitor active signals against current market prices.
    Check if SL or targets were hit and update signal status.

    Args:
        state: Current application state with signals
        current_prices: Dict of {symbol: ltp}

    Returns:
        Updated state with modified signal statuses
    """
    now = datetime.now(IST)

    for signal_key, signal in list(state.get("signals", {}).items()):
        # Only monitor ACTIVE signals
        if signal.get("status") != "ACTIVE":
            continue

        symbol = signal["symbol"]
        direction = signal["direction"]

        # Get current LTP
        ltp = current_prices.get(symbol)
        if ltp is None:
            continue

        ltp = float(ltp)
        entry = float(signal["risk"]["entry"])
        sl = float(signal["risk"]["sl"])
        t1 = float(signal["risk"]["t1"])
        t2 = float(signal["risk"]["t2"])
        t3 = float(signal["risk"]["t3"])

        # Initialize tracking fields
        if "price_history" not in signal:
            signal["price_history"] = []
        signal["price_history"].append({"time": now.isoformat(), "ltp": ltp})

        # Log informative status line
        if direction == "BUY":
            sl_gap = ltp - sl
            t1_gap = ltp - t1
            t2_gap = ltp - t2
            t3_gap = ltp - t3
            sl_status = f"SL@{sl:.2f}({sl_gap:+.2f})" if sl_gap > 0 else f"SL@{sl:.2f}(BREACHED!)"
            t1_status = f"T1@{t1:.2f}({t1_gap:+.2f})" if t1_gap < 0 else f"T1@{t1:.2f}(HIT!)"
            t2_status = f"T2@{t2:.2f}({t2_gap:+.2f})" if t2_gap < 0 else f"T2@{t2:.2f}(HIT!)"
            t3_status = f"T3@{t3:.2f}({t3_gap:+.2f})" if t3_gap < 0 else f"T3@{t3:.2f}(HIT!)"
        else:  # SELL
            sl_gap = sl - ltp
            t1_gap = t1 - ltp
            t2_gap = t2 - ltp
            t3_gap = t3 - ltp
            sl_status = f"SL@{sl:.2f}({sl_gap:+.2f})" if sl_gap > 0 else f"SL@{sl:.2f}(BREACHED!)"
            t1_status = f"T1@{t1:.2f}({t1_gap:+.2f})" if t1_gap < 0 else f"T1@{t1:.2f}(HIT!)"
            t2_status = f"T2@{t2:.2f}({t2_gap:+.2f})" if t2_gap < 0 else f"T2@{t2:.2f}(HIT!)"
            t3_status = f"T3@{t3:.2f}({t3_gap:+.2f})" if t3_gap < 0 else f"T3@{t3:.2f}(HIT!)"

        LOG.info(
            "SIGNAL_STATUS | %s | %s | LTP: %.2f | %s | %s | %s | %s",
            symbol, direction, ltp, sl_status, t1_status, t2_status, t3_status,
        )

        # BUY direction
        if direction == "BUY":
            # Check SL first (exit immediately if breached)
            if ltp <= sl:
                if not signal.get("sl_hit"):
                    signal["status"] = "EXITED"
                    signal["exit_price"] = sl
                    signal["exit_reason"] = "SL_HIT"
                    signal["sl_hit"] = True
                    signal["exit_time"] = now.isoformat()
                    LOG.info(
                        "SIGNAL_SL_HIT | %s | BUY | entry=%.2f | sl=%.2f | ltp=%.2f",
                        symbol, entry, sl, ltp,
                    )
                continue

            # Check targets (in reverse order: highest first)
            if ltp >= t3 and not signal.get("highest_target_hit"):
                signal["highest_target_hit"] = "T3_HIT"
                LOG.info(
                    "SIGNAL_TARGET_HIT | %s | BUY | T3 | target=%.2f | ltp=%.2f",
                    symbol, t3, ltp,
                )
            elif ltp >= t2 and not signal.get("highest_target_hit"):
                signal["highest_target_hit"] = "T2_HIT"
                LOG.info(
                    "SIGNAL_TARGET_HIT | %s | BUY | T2 | target=%.2f | ltp=%.2f",
                    symbol, t2, ltp,
                )
            elif ltp >= t1 and not signal.get("highest_target_hit"):
                signal["highest_target_hit"] = "T1_HIT"
                LOG.info(
                    "SIGNAL_TARGET_HIT | %s | BUY | T1 | target=%.2f | ltp=%.2f",
                    symbol, t1, ltp,
                )

        # SELL direction
        else:
            # Check SL first (exit immediately if breached)
            if ltp >= sl:
                if not signal.get("sl_hit"):
                    signal["status"] = "EXITED"
                    signal["exit_price"] = sl
                    signal["exit_reason"] = "SL_HIT"
                    signal["sl_hit"] = True
                    signal["exit_time"] = now.isoformat()
                    LOG.info(
                        "SIGNAL_SL_HIT | %s | SELL | entry=%.2f | sl=%.2f | ltp=%.2f",
                        symbol, entry, sl, ltp,
                    )
                continue

            # Check targets (in reverse order: lowest first)
            if ltp <= t3 and not signal.get("highest_target_hit"):
                signal["highest_target_hit"] = "T3_HIT"
                LOG.info(
                    "SIGNAL_TARGET_HIT | %s | SELL | T3 | target=%.2f | ltp=%.2f",
                    symbol, t3, ltp,
                )
            elif ltp <= t2 and not signal.get("highest_target_hit"):
                signal["highest_target_hit"] = "T2_HIT"
                LOG.info(
                    "SIGNAL_TARGET_HIT | %s | SELL | T2 | target=%.2f | ltp=%.2f",
                    symbol, t2, ltp,
                )
            elif ltp <= t1 and not signal.get("highest_target_hit"):
                signal["highest_target_hit"] = "T1_HIT"
                LOG.info(
                    "SIGNAL_TARGET_HIT | %s | SELL | T1 | target=%.2f | ltp=%.2f",
                    symbol, t1, ltp,
                )

    return state
