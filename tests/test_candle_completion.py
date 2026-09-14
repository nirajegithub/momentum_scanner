from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from app.candle_utils import completed_candles

IST = ZoneInfo("Asia/Kolkata")


def _bars(freq):
    idx = pd.date_range("2026-09-14 09:15", periods=4, freq=freq, tz=IST)
    return pd.DataFrame({"close": range(4)}, index=idx)


def test_5m_start_timestamp_is_not_completed_at_its_start():
    df = _bars("5min")
    result = completed_candles(df, datetime(2026, 9, 14, 9, 20, tzinfo=IST), 5)
    assert list(result.index.strftime("%H:%M")) == ["09:15"]


def test_15m_start_timestamp_is_not_completed_at_its_start():
    df = _bars("15min")
    result = completed_candles(df, datetime(2026, 9, 14, 9, 30, tzinfo=IST), 15)
    assert list(result.index.strftime("%H:%M")) == ["09:15"]


def test_15m_bar_is_completed_at_end_of_interval():
    df = _bars("15min")
    result = completed_candles(df, datetime(2026, 9, 14, 9, 45, tzinfo=IST), 15)
    assert list(result.index.strftime("%H:%M")) == ["09:15", "09:30"]


def test_5m_confirmation_cannot_use_bars_while_15m_setup_is_forming():
    df5 = _bars("5min").reindex(pd.date_range("2026-09-14 09:15", periods=8, freq="5min", tz=IST))
    setup_ts = pd.Timestamp("2026-09-14 09:30", tz=IST)
    setup_complete = setup_ts + pd.Timedelta(minutes=15)
    eligible = df5[df5.index >= setup_complete]
    assert list(eligible.index.strftime("%H:%M")) == ["09:45", "09:50"]
