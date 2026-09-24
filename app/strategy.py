"""B1 ORB + RVOL strategy.

15M completed candle creates a pending setup only when all configured quality
filters pass. Entry is deliberately deferred to a later completed 5M candle.
"""
from __future__ import annotations

import logging
import math

from .config import SETTINGS
from .scoring import score_trade_quality

LOG = logging.getLogger(__name__)


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _rejected(symbol, reason, **details):
    """Log a rejection with its specific reason and return None."""
    if details:
        detail_str = " | " + " | ".join(f"{k}={v}" for k, v in details.items())
    else:
        detail_str = ""
    LOG.info("B1_FILTER_REJECTED | symbol=%s | reason=%s%s", symbol or "?", reason, detail_str)
    return None


def evaluate_b1_breakout(df15, orb, daily_close, daily_volume, symbol=None):
    """Evaluate one completed 15M candle against the fixed 09:15 ORB."""
    if df15 is None or df15.empty or orb is None:
        return _rejected(symbol, "NO_CANDLE_DATA")

    current = df15.iloc[-1]
    if len(df15) >= 2:
        previous = df15.iloc[-2]
    else:
        return _rejected(symbol, "INSUFFICIENT_CANDLE_HISTORY")

    required = ("open", "high", "low", "close", "rsi14", "rvol")
    if not all(_finite(current.get(k)) for k in required):
        missing = [k for k in required if not _finite(current.get(k))]
        return _rejected(symbol, "INDICATORS_UNAVAILABLE", missing=",".join(missing))
    if not _finite(previous.get("rsi14")):
        return _rejected(symbol, "PREVIOUS_RSI_UNAVAILABLE")
    if not _finite(daily_close) or not _finite(daily_volume):
        return _rejected(symbol, "DAILY_DATA_UNAVAILABLE")

    if float(daily_close) <= SETTINGS.min_price:
        return _rejected(symbol, "PRICE_TOO_LOW", daily_close=daily_close, min_price=SETTINGS.min_price)
    if float(daily_volume) <= SETTINGS.min_daily_volume:
        return _rejected(symbol, "DAILY_VOLUME_TOO_LOW", daily_volume=daily_volume, min_daily_volume=SETTINGS.min_daily_volume)

    close = float(current["close"])
    rsi_now = float(current["rsi14"])
    rsi_prev = float(previous["rsi14"])
    if close > float(orb["high"]):
        direction = "BUY"
        band_ok = SETTINGS.buy_rsi_min < rsi_now < SETTINGS.buy_rsi_max
    elif close < float(orb["low"]):
        direction = "SELL"
        band_ok = SETTINGS.sell_rsi_min < rsi_now < SETTINGS.sell_rsi_max
    else:
        # Caller already filters to breakout candles, but guard just in case.
        return _rejected(symbol, "NO_BREAKOUT", close=close, orb_high=orb["high"], orb_low=orb["low"])

    rvol = float(current["rvol"])
    if not band_ok:
        return _rejected(
            symbol, "RSI_OUT_OF_BAND", direction=direction, rsi=round(rsi_now, 2),
            band=f"{SETTINGS.buy_rsi_min}-{SETTINGS.buy_rsi_max}" if direction == "BUY"
            else f"{SETTINGS.sell_rsi_min}-{SETTINGS.sell_rsi_max}",
        )
    if rvol < SETTINGS.min_15m_rvol:
        return _rejected(symbol, "RVOL_TOO_LOW", rvol=round(rvol, 2), min_15m_rvol=SETTINGS.min_15m_rvol)

    body_ratio = float(current.get("body_ratio", 0))
    if body_ratio < SETTINGS.min_candle_body_ratio:
        return _rejected(symbol, "CANDLE_BODY_TOO_WEAK", body_ratio=round(body_ratio, 2),
                        min_ratio=SETTINGS.min_candle_body_ratio)

    ema8 = float(current.get("ema8", 0))
    if len(df15) >= SETTINGS.min_ema8_slope_bars + 1:
        ema8_prev = float(df15.iloc[-(SETTINGS.min_ema8_slope_bars + 1)].get("ema8", 0))
        if direction == "BUY" and ema8 <= ema8_prev:
            return _rejected(symbol, "EMA8_NOT_UPSLOPING", direction=direction,
                           ema8_now=round(ema8, 2), ema8_prev=round(ema8_prev, 2))
        elif direction == "SELL" and ema8 >= ema8_prev:
            return _rejected(symbol, "EMA8_NOT_DOWNSLOPING", direction=direction,
                           ema8_now=round(ema8, 2), ema8_prev=round(ema8_prev, 2))

    # EMA8 price alignment check disabled - insufficient filter value in live trading
    # if direction == "BUY" and close < ema8:
    #     return _rejected(symbol, "PRICE_BELOW_EMA8", close=round(close, 2), ema8=round(ema8, 2))
    # elif direction == "SELL" and close > ema8:
    #     return _rejected(symbol, "PRICE_ABOVE_EMA8", close=round(close, 2), ema8=round(ema8, 2))

    setup_ts = df15.index[-1]
    time_of_candle = setup_ts.hour * 100 + setup_ts.minute
    if 915 <= time_of_candle < 1000:
        min_rvol_time = SETTINGS.rvol_morning_0915_1000
    elif 1000 <= time_of_candle < 1200:
        min_rvol_time = SETTINGS.rvol_morning_1000_1200
    elif 1200 <= time_of_candle < 1400:
        min_rvol_time = SETTINGS.rvol_midday_1200_1400
    else:
        min_rvol_time = SETTINGS.rvol_close_1400_1530

    if rvol < min_rvol_time:
        return _rejected(symbol, "RVOL_BELOW_TIME_THRESHOLD", rvol=round(rvol, 2),
                        time_slot=f"{time_of_candle}", min_rvol=round(min_rvol_time, 2))

    consolidation_ok = False
    if len(df15) >= SETTINGS.consolidation_candles:
        consol_candles = df15.iloc[-(SETTINGS.consolidation_candles):]
        body_sizes = (consol_candles["close"] - consol_candles["open"]).abs()
        avg_body = body_sizes.mean()
        price_range = consol_candles["high"].max() - consol_candles["low"].min()
        max_body_range_pct = price_range / close * 100 if close > 0 else 999

        if avg_body < (close * SETTINGS.consolidation_body_pct / 100) and \
           price_range < (close * SETTINGS.consolidation_range_pct / 100):
            consolidation_ok = True

    if not consolidation_ok:
        return _rejected(symbol, "NO_CONSOLIDATION_BEFORE_BREAKOUT", consolidation_candles=SETTINGS.consolidation_candles)

    quality = score_trade_quality(df15, direction)
    score = float(quality.get("trade_quality_score", 0.0))
    # Trade quality score check disabled - insufficient filter value in live trading
    # if score < SETTINGS.min_trade_score or score > SETTINGS.max_trade_score:
    #     return _rejected(
    #         symbol, "SCORE_OUT_OF_RANGE", score=score,
    #         min_trade_score=SETTINGS.min_trade_score, max_trade_score=SETTINGS.max_trade_score,
    #     )

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


def momentum_surge_qualifies(setup, direction):
    """Check if setup qualifies for early 5M confirmation via momentum surge.

    Early entry triggered when:
    - RVOL > 3.5 (strong volume surge)
    - BUY: RSI > 60 (strong upside momentum)
    - SELL: RSI < 40 (strong downside momentum)
    """
    rvol = float(setup.get("setup_15m_rvol", 0))
    rsi = float(setup.get("setup_15m_rsi14", 0))

    if rvol <= 3.5:
        return False

    if direction == "BUY":
        return rsi > 60
    elif direction == "SELL":
        return rsi < 40

    return False


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


def market_trend_aligned(nifty_df, direction):
    """Check if Nifty50 trend aligns with trade direction.

    Returns True if:
    - BUY: Nifty50 is in uptrend (last 3 closes > previous 3 closes average)
    - SELL: Nifty50 is in downtrend (last 3 closes < previous 3 closes average)
    """
    if nifty_df is None or nifty_df.empty or len(nifty_df) < 6:
        return True  # Assume aligned if data unavailable

    closes = nifty_df["close"].astype(float).tail(6).values
    recent_avg = closes[-3:].mean()
    previous_avg = closes[:3].mean()

    if direction == "BUY":
        return recent_avg > previous_avg
    elif direction == "SELL":
        return recent_avg < previous_avg

    return True
