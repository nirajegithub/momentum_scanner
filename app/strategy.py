"""B1 ORB + RVOL strategy.

15M completed candle creates a pending setup only when all configured quality
filters pass. Entry is deliberately deferred to a later completed 5M candle.
"""
from __future__ import annotations

import math

from .config import SETTINGS
from .scoring import score_trade_quality


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def evaluate_b1_breakout(df15, orb, daily_close, daily_volume):
    """Evaluate one completed 15M candle against the fixed 09:15 ORB."""
    if df15 is None or df15.empty or orb is None:
        return None

    current = df15.iloc[-1]
    if len(df15) >= 2:
        previous = df15.iloc[-2]
    else:
        return None

    required = ("open", "high", "low", "close", "rsi14", "rvol")
    if not all(_finite(current.get(k)) for k in required):
        return None
    if not _finite(previous.get("rsi14")):
        return None
    if not _finite(daily_close) or not _finite(daily_volume):
        return None

    if float(daily_close) <= SETTINGS.min_price:
        return None
    if float(daily_volume) <= SETTINGS.min_daily_volume:
        return None

    close = float(current["close"])
    if close > float(orb["high"]):
        direction = "BUY"
        rsi_ok = (
            SETTINGS.buy_rsi_min < float(current["rsi14"]) < SETTINGS.buy_rsi_max
            and float(current["rsi14"]) > float(previous["rsi14"])
        )
    elif close < float(orb["low"]):
        direction = "SELL"
        rsi_ok = (
            SETTINGS.sell_rsi_min < float(current["rsi14"]) < SETTINGS.sell_rsi_max
            and float(current["rsi14"]) < float(previous["rsi14"])
        )
    else:
        return None

    rvol = float(current["rvol"])
    if not rsi_ok:
        return None
    if rvol < SETTINGS.min_15m_rvol:
        return None

    quality = score_trade_quality(df15, direction)
    score = float(quality.get("trade_quality_score", 0.0))
    if score < SETTINGS.min_trade_score or score > SETTINGS.max_trade_score:
        return None

    setup_ts = df15.index[-1]
    completion = setup_ts
    # The current 15M dataframe uses candle-start labels. A 15M candle beginning
    # at 09:15 completes at 09:30, so all setup completion times are +15 minutes.
    try:
        completion = setup_ts + __import__("pandas").Timedelta(minutes=15)
    except Exception:
        pass

    result = {
        "direction": direction,
        "setup": "B1_ORB",
        "setup_15m_timestamp": setup_ts.isoformat(),
        "setup_15m_completion": completion.isoformat(),
        "setup_15m_open": float(current["open"]),
        "setup_15m_high": float(current["high"]),
        "setup_15m_low": float(current["low"]),
        "setup_15m_close": close,
        "setup_15m_rsi14": float(current["rsi14"]),
        "setup_15m_previous_rsi14": float(previous["rsi14"]),
        "setup_15m_rvol": rvol,
        "daily_close": float(daily_close),
        "daily_volume": float(daily_volume),
        "trade_quality_score": score,
        **quality,
    }
    return result


def t1_blocked(df5, confirmation_ts, entry, t1, direction):
    """Return True if T1 had already been touched before confirmation.

    This is a safety/diagnostic gate, not a replacement for the 5M close
    confirmation rule. The confirmation candle itself is excluded.
    """
    if df5 is None or df5.empty:
        return False
    rows = df5[df5.index < confirmation_ts]
    if rows.empty:
        return False
    target = float(t1)
    if direction == "BUY":
        return bool(rows["high"].astype(float).max() >= target)
    return bool(rows["low"].astype(float).min() <= target)
