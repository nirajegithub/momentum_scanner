from __future__ import annotations

import pandas as pd
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def as_ist_index(df):
    if df is None or df.empty:
        return pd.DataFrame()
    x = df.copy()
    x.index = pd.to_datetime(x.index)
    if x.index.tz is None:
        x.index = x.index.tz_localize(IST)
    else:
        x.index = x.index.tz_convert(IST)
    return x.sort_index()


def completed_candles(df, ts, interval_minutes):
    """Return only candles whose full interval has ended by *ts*.

    Dhan timestamps are candle-start timestamps. A candle stamped 09:30 for
    a 15-minute series represents 09:30-09:45, so it is not completed at
    09:30.
    """
    x = as_ist_index(df)
    if x.empty:
        return x
    cutoff = pd.Timestamp(ts)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize(IST)
    else:
        cutoff = cutoff.tz_convert(IST)
    completed_at = x.index + pd.Timedelta(minutes=int(interval_minutes))
    return x[completed_at <= cutoff]


def resample_session_ohlcv(df, interval_minutes=15):
    """Build NSE intraday OHLCV bars using candle-start timestamps.

    The NSE regular session starts at 09:15 IST. Dhan's minute data is
    therefore grouped into session-aligned intervals such as 09:15-09:30
    and 09:30-09:45. The returned index is the interval start, which is
    the convention used by the live B1 state machine.
    """
    x = as_ist_index(df)
    if x.empty:
        return x
    interval = int(interval_minutes)
    if interval <= 0:
        raise ValueError("interval_minutes must be positive")

    out = (
        x.resample(
            f"{interval}min",
            origin="start_day",
            offset="15min",
            label="right",
            closed="left",
        )
        .agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        .dropna(subset=["open", "high", "low", "close"])
    )

    # Convert right-edge labels to candle-start labels.
    out.index = out.index - pd.Timedelta(minutes=interval)

    # Keep only regular-session candle starts.
    market_open = pd.Timestamp("09:15").time()
    market_close = pd.Timestamp("15:30").time()
    out = out[(out.index.time >= market_open) & (out.index.time < market_close)]
    return out
