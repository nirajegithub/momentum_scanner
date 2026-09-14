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
